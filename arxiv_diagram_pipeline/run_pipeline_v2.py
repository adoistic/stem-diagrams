#!/usr/bin/env python3
"""v2 pipeline: parallel, resumable, quality-filtered — targets N proper diagrams.

Architecture (all overlapped, all resumable via state.db):
  harvester thread   arXiv search per field, registers papers (round-robin)
  downloader thread  fetches PDFs (3s arXiv politeness), registers pages
  llm pool           page-diagram detection + image classify/label
                     (MAX_WORKERS concurrent OpenRouter calls)
  ocr pool           batched Mistral OCR: diagram pages from many papers are
                     combined into one PDF per batch; a manifest maps batch
                     page k -> (arxiv_id, page_no)
  main thread        scheduler: reaps futures, writes SQLite, keeps queues full

Every result is committed to SQLite the moment it arrives, so Ctrl-C, crashes,
or exhausted API credits lose at most the calls in flight. Re-running resumes.

Usage:
  python run_pipeline_v2.py                     # target from .env (default 30000)
  python run_pipeline_v2.py --target 500
  python run_pipeline_v2.py --export-only
"""

import argparse
import json
import logging
import shutil
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
from pipeline import (arxiv_client, diagram_detector, diagram_labeler,
                      excel_exporter, image_filter, mistral_ocr, page_renderer,
                      pdf_batcher)
from pipeline import openrouter_client
from pipeline.state_db import StateDB

log = logging.getLogger("v2")

FATAL_ERRORS = (openrouter_client.CreditsExhaustedError,
                openrouter_client.MissingAPIKeyError,
                mistral_ocr.CreditsExhaustedError,
                mistral_ocr.MissingAPIKeyError)


class FatalPipelineError(RuntimeError):
    pass


def pdf_path_of(field, arxiv_id):
    return config.PAPERS_V2_DIR / field / (arxiv_id.replace("/", "_") + ".pdf")


def field_display(field_key):
    return config.FIELDS[field_key]["name"]


# --------------------------------------------------------------------------
# background threads
# --------------------------------------------------------------------------

def harvest_loop(db, stop, state):
    """Keep a rolling buffer of registered papers in the funnel.

    Deliberately does NOT front-load the whole projected need: bursting deep
    pagination gets us 429-throttled by arXiv. The downloader consumes ~20
    papers/min at most, so a ~1500-paper buffer is hours of runway."""
    while not stop.is_set():
        c = db.counts()
        remaining = state["target"] - c["labeled"]
        if remaining <= 0:
            return
        est_yield = 3.0
        if c["papers_downloaded"] >= 30 and c["labeled"] >= 30:
            est_yield = max(0.5, c["labeled"] / c["papers_downloaded"])
        needed = int(remaining / est_yield * 1.3)
        buffer_target = min(needed, 1500)
        if c["papers_pending"] >= buffer_target:
            stop.wait(60)
            continue
        added_total = 0
        throttled = False
        for key, field in config.FIELDS.items():
            if stop.is_set():
                return
            offset = int(db.get_meta(f"harvest_offset_{key}", "0"))
            try:
                papers = list(arxiv_client.search_paginated(
                    field["query"], 200, page_size=200,
                    delay=config.ARXIV_DELAY_SECONDS, start_offset=offset))
            except arxiv_client.TemporarilyUnavailable as exc:
                log.warning("[harvest] %s: %s", field["name"], exc)
                throttled = True
                continue
            added = db.add_papers(key, papers)
            db.set_meta(f"harvest_offset_{key}", offset + len(papers))
            added_total += added
            log.info("[harvest] %s: +%d papers (offset now %d)",
                     field["name"], added, offset + len(papers))
        if throttled:
            log.warning("[harvest] arXiv is throttling us; next round in 10 min")
            stop.wait(600)
        elif added_total == 0:
            log.warning("[harvest] arXiv supply exhausted for all fields")
            state["harvest_exhausted"] = True
            stop.wait(600)
        else:
            state["harvest_exhausted"] = False
            stop.wait(60)


def download_loop(db, stop, state):
    """Fetch pending papers one at a time (arXiv politeness), register pages."""
    while not stop.is_set():
        c = db.counts()
        if c["pages_pending"] > config.DOWNLOAD_BACKLOG_PAGES:
            state["dl_idle"] = "backlog"
            stop.wait(15)
            continue
        if c["labeled"] >= state["target"]:
            state["dl_idle"] = "target-met"
            stop.wait(15)
            continue
        paper = db.next_pending_paper()
        if paper is None:
            state["dl_idle"] = "no-pending-papers"
            stop.wait(10)
            continue
        state["dl_idle"] = ""
        dest = pdf_path_of(paper["field"], paper["arxiv_id"])
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                arxiv_client.download_pdf(
                    paper["pdf_url"], dest, config.ARXIV_DELAY_SECONDS,
                    arxiv_id=paper["arxiv_id"])
            n_pages = page_renderer.page_count(dest)
            if config.MAX_PAGES_PER_PAPER:
                n_pages = min(n_pages, config.MAX_PAGES_PER_PAPER)
            db.mark_paper_downloaded(paper["arxiv_id"], n_pages)
        except Exception as exc:
            if "429" in str(exc):
                # arXiv rate limit — leave the paper queued and cool off
                log.warning("[download] arXiv rate-limited; pausing 2 min "
                            "(%s stays queued)", paper["arxiv_id"])
                stop.wait(120)
            else:
                db.mark_paper_failed(paper["arxiv_id"], exc)
                log.warning("[download] %s failed: %s", paper["arxiv_id"], exc)


# --------------------------------------------------------------------------
# pool workers (return results; ALL DB writes happen on the main thread)
# --------------------------------------------------------------------------

def screen_worker(job):
    """Stage 1: free local graphics check, then the cheap screening model."""
    import fitz

    pdf = pdf_path_of(job["field"], job["arxiv_id"])
    with fitz.open(pdf) as doc:
        page = doc[job["page_no"] - 1]
        has_graphics = bool(page.get_images()) or bool(page.get_drawings())
    if not has_graphics:
        # pure text page (references, proofs) — a diagram needs graphics objects
        return {"has_diagram": False, "skipped": "no-graphics"}, 0.0
    uri = page_renderer.render_page_uri(
        pdf, job["page_no"], config.RENDER_DPI, config.JPEG_QUALITY)
    return diagram_detector.detect_uri(
        uri, job["page_no"], job["title"], field_display(job["field"]),
        model=config.SCREEN_MODEL)


def confirm_worker(job):
    """Stage 2: the main model re-judges pages the screener flagged."""
    pdf = pdf_path_of(job["field"], job["arxiv_id"])
    uri = page_renderer.render_page_uri(
        pdf, job["page_no"], config.RENDER_DPI, config.JPEG_QUALITY)
    return diagram_detector.detect_uri(
        uri, job["page_no"], job["title"], field_display(job["field"]))


def label_worker(job):
    detect = {}
    try:
        detect = json.loads(job["detect_json"] or "{}")
    except ValueError:
        pass
    diagram_context = "\n".join(
        f"- {d.get('type', 'diagram')}: {d.get('description', '')}"
        for d in detect.get("diagrams", []))
    if detect.get("page_summary"):
        diagram_context += f"\nPage summary: {detect['page_summary']}"
    return diagram_labeler.classify_and_label(
        Path(job["file_path"]), job["page_no"], job["title"],
        field_display(job["field"]), job["ocr_md"] or "", diagram_context)


def ocr_worker(batch):
    return mistral_ocr.ocr_pdf(Path(batch["pdf_path"]))


# --------------------------------------------------------------------------
# completion handlers (main thread)
# --------------------------------------------------------------------------

def _result_or_fatal(fut):
    try:
        return fut.result(), None
    except FATAL_ERRORS as exc:
        raise FatalPipelineError(str(exc))
    except Exception as exc:  # transient — recorded, retried next run
        return None, exc


def reject_dir_move(db_field, file_path):
    dest_dir = config.REJECTS_V2_DIR / db_field
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(file_path).name
    try:
        shutil.move(str(file_path), dest)
        return dest
    except OSError as exc:
        log.warning("could not move reject %s: %s", file_path, exc)
        return Path(file_path)


def handle_screen(db, job, fut):
    result, exc = _result_or_fatal(fut)
    if exc is not None:
        db.set_page_failed(job["arxiv_id"], job["page_no"], exc)
        log.warning("[screen] %s p.%d failed: %s", job["arxiv_id"], job["page_no"], exc)
        return
    detection, cost = result
    db.set_page_screened(job["arxiv_id"], job["page_no"],
                         bool(detection["has_diagram"]), json.dumps(detection), cost)


def handle_confirm(db, job, fut):
    result, exc = _result_or_fatal(fut)
    if exc is not None:
        db.set_page_failed(job["arxiv_id"], job["page_no"], exc)
        log.warning("[confirm] %s p.%d failed: %s", job["arxiv_id"], job["page_no"], exc)
        return
    detection, cost = result
    db.set_page_detected(job["arxiv_id"], job["page_no"],
                         detection["has_diagram"], json.dumps(detection), cost)


def handle_label(db, job, fut):
    result, exc = _result_or_fatal(fut)
    if exc is not None:
        if isinstance(exc, FileNotFoundError):
            # image file is gone for good — don't retry forever
            db.set_image_rejected(job["image_id"], "local:file-missing")
        else:
            db.set_image_failed(job["image_id"], exc)
        log.warning("[label] image %d failed: %s", job["image_id"], exc)
        return
    verdict, cost = result
    if verdict["is_diagram"] and verdict["label"].strip():
        db.set_image_labeled(job["image_id"], verdict["diagram_type"],
                             verdict["title"], verdict["label"], cost)
    else:
        reason = "llm:" + (verdict["reject_reason"].strip() or "not-a-diagram")
        new_path = reject_dir_move(job["field"], job["file_path"])
        db.set_image_rejected(job["image_id"], reason, cost, new_path)


def handle_ocr(db, batch, fut, field_of):
    result, exc = _result_or_fatal(fut)
    if exc is not None:
        db.mark_batch_failed(batch["batch_id"], exc)
        log.warning("[ocr] batch %d failed: %s", batch["batch_id"], exc)
        return
    manifest = json.loads(batch["manifest_json"])
    n_images = 0
    for page in result.get("pages", []):
        idx = page.get("index", -1)
        if not 0 <= idx < len(manifest):
            continue
        arxiv_id, page_no = manifest[idx]
        db.set_page_ocr_md(arxiv_id, page_no, page.get("markdown", ""))
        field = field_of(arxiv_id)
        dest_dir = config.IMAGES_V2_DIR / field
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_id = arxiv_id.replace("/", "_")
        for i, img in enumerate(page.get("images", []), start=1):
            stem = f"{safe_id}_p{page_no:03d}_{i:02d}"
            path = mistral_ocr.save_one_image(img, dest_dir, stem)
            if path is None:
                continue
            n_images += 1
            local_reason = image_filter.local_reject_reason(path)
            if local_reason:
                new_path = reject_dir_move(field, path)
                db.add_image(arxiv_id, page_no, batch["batch_id"], new_path,
                             status="rejected", reject_reason=f"local:{local_reason}")
            else:
                db.add_image(arxiv_id, page_no, batch["batch_id"], path)
    db.mark_batch_done(batch["batch_id"])
    log.info("[ocr] batch %d done: %d pages -> %d images",
             batch["batch_id"], len(manifest), n_images)


# --------------------------------------------------------------------------
# batching
# --------------------------------------------------------------------------

def build_batches(db, manifest_pages, field_of):
    """Validate, assemble (splitting oversized), register and write batch PDFs."""
    def path_for(arxiv_id):
        return pdf_path_of(field_of(arxiv_id), arxiv_id)

    valid, dropped = pdf_batcher.validate_manifest(manifest_pages, path_for)
    for arxiv_id, page_no in dropped:
        db.mark_page_unbatchable(arxiv_id, page_no, "source pdf missing/short")
    if not valid:
        return
    config.OCR_BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(valid), config.OCR_BATCH_PAGES):
        chunk = valid[i:i + config.OCR_BATCH_PAGES]
        for sub_manifest, data in pdf_batcher.split_oversized(chunk, path_for):
            batch_id = db.create_batch(sub_manifest)
            path = config.OCR_BATCHES_DIR / f"batch_{batch_id:05d}.pdf"
            path.write_bytes(data)
            db.set_batch_built(batch_id, path)
            log.info("[batch] built batch %d (%d pages, %.1f MB)",
                     batch_id, len(sub_manifest), len(data) / 1e6)


def rebuild_incomplete_batches(db, field_of):
    """After a crash: batches stuck in 'building', or 'pending' with a missing
    PDF file, are reassembled from their manifests."""
    def path_for(arxiv_id):
        return pdf_path_of(field_of(arxiv_id), arxiv_id)

    stuck = db.batches_with_status("building")
    stuck += [b for b in db.batches_with_status("pending")
              if not (b["pdf_path"] and Path(b["pdf_path"]).exists())]
    for b in stuck:
        manifest = [tuple(x) for x in json.loads(b["manifest_json"])]
        valid, _ = pdf_batcher.validate_manifest(manifest, path_for)
        if not valid:
            db.mark_batch_failed(b["batch_id"], "no valid pages on rebuild")
            continue
        data = pdf_batcher.build_batch_pdf(valid, path_for)
        config.OCR_BATCHES_DIR.mkdir(parents=True, exist_ok=True)
        path = config.OCR_BATCHES_DIR / f"batch_{b['batch_id']:05d}.pdf"
        path.write_bytes(data)
        db.set_batch_built(b["batch_id"], path)
        log.info("[batch] rebuilt batch %d after interrupted run", b["batch_id"])


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def do_export(db):
    images_dir = config.OUTPUT_V2_DIR / "diagram_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in db.labeled_rows():
        src = Path(r["file_path"])
        if not src.exists():
            continue
        flat_name = f"diagram_{r['image_id']:06d}{src.suffix.lower()}"
        flat = images_dir / flat_name
        if not flat.exists():
            shutil.copyfile(src, flat)
        rows.append({
            "field": field_display(r["field"]),
            "arxiv_id": r["arxiv_id"],
            "paper_title": r["paper_title"],
            "authors": r["authors"],
            "published": r["published"],
            "abs_url": r["abs_url"],
            "pdf_url": r["pdf_url"],
            "page_number": r["page_no"],
            "source_image_path": str(src),
            "image_file": flat_name,
            "diagram_type": r["diagram_type"],
            "diagram_title": r["diagram_title"],
            "label": r["label"],
        })
    if not rows:
        log.warning("[export] nothing labeled yet")
        return
    with_path, without_path = excel_exporter.export_v2(
        iter(rows), config.OUTPUT_V2_DIR, total_hint=len(rows))
    log.info("[export] %d diagrams -> %s", len(rows), with_path)
    log.info("[export] %d diagrams -> %s", len(rows), without_path)


# --------------------------------------------------------------------------
# main scheduler
# --------------------------------------------------------------------------

def run(args):
    db = StateDB()
    n_pages, n_images, n_batches = db.reset_transient_failures()
    if any((n_pages, n_images, n_batches)):
        log.info("requeued failures from last run: %d pages, %d images, %d batches",
                 n_pages, n_images, n_batches)

    field_cache = {}

    def field_of(arxiv_id):
        if arxiv_id not in field_cache:
            field_cache[arxiv_id] = db.paper(arxiv_id)["field"]
        return field_cache[arxiv_id]

    rebuild_incomplete_batches(db, field_of)

    state = {"target": args.target, "dl_idle": "", "harvest_exhausted": False}
    stop = threading.Event()
    threads = [
        threading.Thread(target=harvest_loop, args=(db, stop, state),
                         name="harvest", daemon=True),
        threading.Thread(target=download_loop, args=(db, stop, state),
                         name="download", daemon=True),
    ]
    for t in threads:
        t.start()

    llm_pool = ThreadPoolExecutor(max_workers=args.max_workers)
    ocr_pool = ThreadPoolExecutor(max_workers=config.OCR_CONCURRENCY)
    inflight = {}          # future -> (kind, payload)
    inflight_pages = set()
    inflight_images = set()
    inflight_batches = set()
    exit_code = 0
    last_status = 0.0

    def llm_inflight():
        return sum(1 for k, _ in inflight.values()
                   if k in ("screen", "confirm", "label"))

    try:
        while True:
            for fut in [f for f in list(inflight) if f.done()]:
                kind, payload = inflight.pop(fut)
                if kind == "screen":
                    handle_screen(db, payload, fut)
                    inflight_pages.discard((payload["arxiv_id"], payload["page_no"]))
                elif kind == "confirm":
                    handle_confirm(db, payload, fut)
                    inflight_pages.discard((payload["arxiv_id"], payload["page_no"]))
                elif kind == "label":
                    handle_label(db, payload, fut)
                    inflight_images.discard(payload["image_id"])
                elif kind == "ocr":
                    handle_ocr(db, payload, fut, field_of)
                    inflight_batches.discard(payload["batch_id"])

            labeled = db.labeled_count()
            if labeled >= args.target:
                log.info("TARGET REACHED: %d labeled diagrams", labeled)
                break

            # fill LLM slots — labels first (each one directly advances target),
            # then confirms (closest to product), then screens
            slots = args.max_workers * 2 - llm_inflight()
            if slots > 0:
                for job in db.pending_images(slots, exclude=inflight_images):
                    inflight_images.add(job["image_id"])
                    inflight[llm_pool.submit(label_worker, job)] = ("label", job)
                    slots -= 1
            if slots > 0:
                for job in db.screened_pages(slots, exclude=inflight_pages):
                    inflight_pages.add((job["arxiv_id"], job["page_no"]))
                    inflight[llm_pool.submit(confirm_worker, job)] = ("confirm", job)
                    slots -= 1
            if slots > 0:
                for job in db.pending_pages(slots, exclude=inflight_pages):
                    inflight_pages.add((job["arxiv_id"], job["page_no"]))
                    inflight[llm_pool.submit(screen_worker, job)] = ("screen", job)

            # batch diagram pages for OCR
            unbatched = db.unbatched_diagram_pages(config.OCR_BATCH_PAGES * 4)
            stall = (not inflight and db.counts()["images_pending"] == 0)
            if len(unbatched) >= config.OCR_BATCH_PAGES or (unbatched and stall):
                build_batches(db, unbatched, field_of)

            # keep the OCR pool fed
            ocr_slots = config.OCR_CONCURRENCY - sum(
                1 for k, _ in inflight.values() if k == "ocr")
            if ocr_slots > 0:
                for batch in db.batches_with_status("pending", ocr_slots * 2):
                    if batch["batch_id"] in inflight_batches or ocr_slots <= 0:
                        continue
                    inflight_batches.add(batch["batch_id"])
                    inflight[ocr_pool.submit(ocr_worker, batch)] = ("ocr", batch)
                    ocr_slots -= 1

            # supply exhausted?
            c = db.counts()
            drained = (not inflight and c["pages_pending"] == 0
                       and c["images_pending"] == 0 and c["batches_pending"] == 0
                       and c["papers_pending"] == 0)
            if drained and state["harvest_exhausted"]:
                log.warning("supply exhausted at %d labeled diagrams", labeled)
                break
            if time.monotonic() - last_status > 30:
                last_status = time.monotonic()
                log.info(
                    "STATUS labeled %d/%d | rejected %d | papers %d/%d dl | "
                    "pages %d todo (%d diag) | imgs %d todo | batches %d | "
                    "$%.2f | dl:%s",
                    c["labeled"], args.target, c["rejected"],
                    c["papers_downloaded"], c["papers_total"],
                    c["pages_pending"], c["pages_diagram"],
                    c["images_pending"], c["batches_pending"],
                    c["cost"], state["dl_idle"] or "active")
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.warning("interrupted — all completed work is saved; rerun to resume")
        exit_code = 130
    except FatalPipelineError as exc:
        log.error("FATAL: %s", exc)
        log.error("The pipeline stopped cleanly — nothing was lost. "
                  "Fix the cause (e.g. top up credits) and rerun the same "
                  "command to resume exactly where it stopped.")
        exit_code = 3
    finally:
        stop.set()
        llm_pool.shutdown(wait=False, cancel_futures=True)
        ocr_pool.shutdown(wait=False, cancel_futures=True)

    if exit_code == 0:
        do_export(db)
    c = db.counts()
    log.info("FINAL: %d labeled, %d rejected, %d papers, $%.2f spent",
             c["labeled"], c["rejected"], c["papers_downloaded"], c["cost"])
    return exit_code


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, default=config.TARGET_DIAGRAMS,
                        help="stop after this many accepted diagrams")
    parser.add_argument("--max-workers", type=int, default=config.MAX_WORKERS,
                        help="concurrent OpenRouter calls")
    parser.add_argument("--export-only", action="store_true",
                        help="just rebuild the Excel files from state.db")
    args = parser.parse_args()

    config.LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(config.LOG_DIR / "v2_run.log")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    def _sigterm(_signo, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _sigterm)

    if args.export_only:
        do_export(StateDB())
        return
    sys.exit(run(args))


if __name__ == "__main__":
    main()
