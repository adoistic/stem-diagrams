#!/usr/bin/env python3
"""ArXiv diagram extraction & labeling pipeline.

Stages (run in order, each resumable / skip-if-done):
  download  search arXiv per field, download PDFs + metadata
  detect    render each page, ask OpenRouter (xiaomi/mimo-v2.5-pro) for diagrams
  ocr       Mistral OCR on diagram pages, save extracted images
  label     send each diagram image + context back to the LLM for labeling
  export    copy images to a flat folder, write the two Excel files

Usage:
  python run_pipeline.py                                     # all stages
  python run_pipeline.py --papers-per-field 3
  python run_pipeline.py --fields robotics_automation telecommunications
  python run_pipeline.py --stages detect ocr --max-pages 10
"""

import argparse
import json
import logging
import shutil
import sys

import config
from pipeline import arxiv_client, excel_exporter, page_renderer

log = logging.getLogger("pipeline")

STAGES = ["download", "detect", "ocr", "label", "export"]

DIAGRAM_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def paper_dir(field_key, arxiv_id):
    return config.PAPERS_DIR / field_key / arxiv_id.replace("/", "_")


def iter_papers(field_keys):
    """Yield (field_key, paper_dir, metadata) for every downloaded paper."""
    for key in field_keys:
        field_dir = config.PAPERS_DIR / key
        if not field_dir.is_dir():
            continue
        for pdir in sorted(field_dir.iterdir()):
            meta_path = pdir / "metadata.json"
            if (pdir / "paper.pdf").exists() and meta_path.exists():
                try:
                    yield key, pdir, json.loads(meta_path.read_text())
                except (OSError, ValueError) as exc:
                    log.error("[iter_papers] unreadable %s (skipping): %s", meta_path, exc)


def stage_download(field_keys, papers_per_field):
    for key in field_keys:
        field = config.FIELDS[key]
        log.info("[download] searching arXiv: %s", field["name"])
        # Over-fetch: fresh submissions sometimes have no PDF yet, so keep
        # spare candidates until the per-field quota is met.
        papers = arxiv_client.search(
            field["query"], papers_per_field * 3, config.ARXIV_DELAY_SECONDS
        )
        if not papers:
            log.warning("[download] no results for %s", field["name"])
            continue
        downloaded = 0
        for meta in papers:
            if downloaded >= papers_per_field:
                break
            pdir = paper_dir(key, meta["arxiv_id"])
            pdf_path = pdir / "paper.pdf"
            meta_path = pdir / "metadata.json"
            if pdf_path.exists() and meta_path.exists():
                log.info("[download] already have %s", meta["arxiv_id"])
                downloaded += 1
                continue
            pdir.mkdir(parents=True, exist_ok=True)
            try:
                arxiv_client.download_pdf(
                    meta["pdf_url"], pdf_path, config.ARXIV_DELAY_SECONDS,
                    arxiv_id=meta["arxiv_id"],
                )
            except Exception as exc:
                log.error("[download] %s failed: %s", meta["arxiv_id"], exc)
                if not any(pdir.iterdir()):
                    pdir.rmdir()
                continue
            meta["field"] = key
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
            downloaded += 1
            log.info("[download] %s — %.70s", meta["arxiv_id"], meta["title"])
        if downloaded < papers_per_field:
            log.warning("[download] %s: only %d/%d papers downloaded",
                        field["name"], downloaded, papers_per_field)


def stage_detect(field_keys, max_pages):
    from pipeline import diagram_detector

    for key, pdir, meta in iter_papers(field_keys):
        pdf_path = pdir / "paper.pdf"
        pages_dir = pdir / "pages"
        analysis_dir = pdir / "analysis"
        try:
            n_pages = page_renderer.page_count(pdf_path)
        except Exception as exc:
            log.error("[detect] %s: can't open PDF (skipping): %s", meta["arxiv_id"], exc)
            continue
        if max_pages:
            n_pages = min(n_pages, max_pages)
        for page in range(1, n_pages + 1):
            out_path = analysis_dir / f"page_{page:03d}.json"
            if out_path.exists():
                continue
            try:
                img_path = pages_dir / f"page_{page:03d}.jpg"
                if not img_path.exists():
                    pages_dir.mkdir(exist_ok=True)
                    page_renderer.render_page(
                        pdf_path, page, img_path, config.RENDER_DPI, config.JPEG_QUALITY
                    )
                result = diagram_detector.detect(
                    img_path, page, meta["title"], config.FIELDS[key]["name"]
                )
                analysis_dir.mkdir(exist_ok=True)
                out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
                log.info(
                    "[detect] %s p.%d/%d has_diagram=%s",
                    meta["arxiv_id"], page, n_pages, result["has_diagram"],
                )
            except Exception as exc:
                _abort_if_missing_key(exc)
                log.error("[detect] %s p.%d failed (will retry next run): %s",
                          meta["arxiv_id"], page, exc)


def iter_diagram_pages(field_keys):
    """Yield (field_key, paper_dir, meta, page_number, analysis) for diagram pages."""
    for key, pdir, meta in iter_papers(field_keys):
        analysis_dir = pdir / "analysis"
        if not analysis_dir.is_dir():
            continue
        for a_path in sorted(analysis_dir.glob("page_*.json")):
            try:
                analysis = json.loads(a_path.read_text())
            except (OSError, ValueError) as exc:
                log.error("[iter_diagram_pages] unreadable %s (skipping): %s", a_path, exc)
                continue
            if analysis.get("has_diagram"):
                page = int(a_path.stem.split("_")[1])
                yield key, pdir, meta, page, analysis


def stage_ocr(field_keys):
    from pipeline import mistral_ocr

    for key, pdir, meta, page, _analysis in iter_diagram_pages(field_keys):
        ocr_dir = pdir / "ocr"
        diagrams_dir = pdir / "diagrams"
        ocr_json = ocr_dir / f"page_{page:03d}.json"
        if ocr_json.exists():
            continue
        page_img = pdir / "pages" / f"page_{page:03d}.jpg"
        try:
            response = mistral_ocr.ocr_page(page_img)
            ocr_dir.mkdir(exist_ok=True)
            diagrams_dir.mkdir(exist_ok=True)
            ocr_json.write_text(json.dumps(response, indent=2, ensure_ascii=False))
            markdown = mistral_ocr.extract_markdown(response)
            (ocr_dir / f"page_{page:03d}.md").write_text(markdown)
            saved = mistral_ocr.save_images(response, diagrams_dir, f"page_{page:03d}")
            if not saved:
                # OCR found no embedded images — keep the full page render so the
                # detected diagram still gets labeled.
                fallback = diagrams_dir / f"page_{page:03d}_full.jpg"
                shutil.copyfile(page_img, fallback)
                saved = [fallback]
            log.info("[ocr] %s p.%d → %d image(s)", meta["arxiv_id"], page, len(saved))
        except Exception as exc:
            _abort_if_missing_key(exc)
            log.error("[ocr] %s p.%d failed (will retry next run): %s",
                      meta["arxiv_id"], page, exc)


def stage_label(field_keys):
    from pipeline import diagram_labeler

    for key, pdir, meta, page, analysis in iter_diagram_pages(field_keys):
        ocr_md = pdir / "ocr" / f"page_{page:03d}.md"
        if not ocr_md.exists():
            continue  # ocr stage hasn't processed this page yet
        try:
            page_text = ocr_md.read_text()[: config.OCR_CONTEXT_CHARS]
        except OSError as exc:
            log.error("[label] %s p.%d: unreadable %s (skipping): %s",
                      meta["arxiv_id"], page, ocr_md, exc)
            continue
        diagram_context = "\n".join(
            f"- {d.get('type', 'diagram')}: {d.get('description', '')}"
            for d in analysis.get("diagrams", [])
        )
        if analysis.get("page_summary"):
            diagram_context += f"\nPage summary: {analysis['page_summary']}"

        labels_dir = pdir / "labels"
        for img_path in sorted((pdir / "diagrams").glob(f"page_{page:03d}_*")):
            if img_path.suffix.lower() not in DIAGRAM_IMAGE_EXTS:
                continue
            out_path = labels_dir / f"{img_path.stem}.json"
            if out_path.exists():
                continue
            try:
                result = diagram_labeler.label(
                    img_path, page, meta["title"], config.FIELDS[key]["name"],
                    page_text, diagram_context,
                )
                result["image_file"] = img_path.name
                labels_dir.mkdir(exist_ok=True)
                out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
                log.info("[label] %s %s — %.60s",
                         meta["arxiv_id"], img_path.name, result["title"])
            except Exception as exc:
                _abort_if_missing_key(exc)
                log.error("[label] %s failed (will retry next run): %s", img_path.name, exc)


def stage_export(field_keys):
    images_dir = config.OUTPUT_DIR / "diagram_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for key, pdir, meta in iter_papers(field_keys):
        labels_dir = pdir / "labels"
        if not labels_dir.is_dir():
            continue
        for label_path in sorted(labels_dir.glob("page_*.json")):
            try:
                label_data = json.loads(label_path.read_text())
            except (OSError, ValueError) as exc:
                log.error("[export] unreadable %s (skipping): %s", label_path, exc)
                continue
            src_img = pdir / "diagrams" / label_data["image_file"]
            if not src_img.exists():
                continue
            page = int(label_path.stem.split("_")[1])
            # Flat, anonymously named copy so the without-source sheet doesn't
            # leak the paper via the file path.
            flat_name = f"diagram_{len(rows) + 1:04d}{src_img.suffix.lower()}"
            shutil.copyfile(src_img, images_dir / flat_name)
            rows.append({
                "field": config.FIELDS[key]["name"],
                "arxiv_id": meta["arxiv_id"],
                "paper_title": meta["title"],
                "authors": "; ".join(meta.get("authors", [])),
                "published": meta.get("published", ""),
                "abs_url": meta.get("abs_url", ""),
                "pdf_url": meta.get("pdf_url", ""),
                "page_number": page,
                "source_image_path": str(src_img.relative_to(config.DATA_DIR)),
                "image_file": flat_name,
                "diagram_type": label_data.get("diagram_type", ""),
                "diagram_title": label_data.get("title", ""),
                "label": label_data.get("label", ""),
            })

    if not rows:
        log.warning("[export] no labeled diagrams found — nothing to export")
        return
    with_path, without_path = excel_exporter.export(rows, config.OUTPUT_DIR)
    log.info("[export] %d diagrams → %s", len(rows), with_path)
    log.info("[export] %d diagrams → %s", len(rows), without_path)


def _abort_if_missing_key(exc):
    from pipeline.mistral_ocr import MissingAPIKeyError as MistralKeyError
    from pipeline.openrouter_client import MissingAPIKeyError as OpenRouterKeyError

    if isinstance(exc, (MistralKeyError, OpenRouterKeyError)):
        sys.exit(f"ERROR: {exc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fields", nargs="+", choices=sorted(config.FIELDS),
                        default=sorted(config.FIELDS),
                        help="field keys to process (default: all six)")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=STAGES,
                        help="pipeline stages to run (default: all)")
    parser.add_argument("--papers-per-field", type=int,
                        default=config.PAPERS_PER_FIELD)
    parser.add_argument("--max-pages", type=int, default=0,
                        help="limit pages analyzed per paper (0 = all)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    if "download" in args.stages:
        stage_download(args.fields, args.papers_per_field)
    if "detect" in args.stages:
        stage_detect(args.fields, args.max_pages)
    if "ocr" in args.stages:
        stage_ocr(args.fields)
    if "label" in args.stages:
        stage_label(args.fields)
    if "export" in args.stages:
        stage_export(args.fields)


if __name__ == "__main__":
    main()
