#!/usr/bin/env python3
"""Render manifest PDF pages to JPEG images for classifier training.

Reads ml/data/pages_manifest.csv (arxiv_id,page_no,has_diagram,field,pdf_path,
split) and rasterizes each referenced page to a JPEG on the external drive, so
the page-level classifier can train directly on page renders.

Rendering MUST match production exactly: fitz's get_pixmap(dpi=...) then
tobytes("jpeg", jpg_quality=...), same as render_page_uri() in
../pipeline/page_renderer.py and the RENDER_DPI/JPEG_QUALITY constants in
../config.py (dpi=110, quality=80).

Resumable: rows whose output JPEG already exists are skipped without opening
their PDF. Remaining rows are grouped by pdf_path so each PDF is opened once
per worker, then parallelized across PDFs with a multiprocessing.Pool. The
output drive is ExFAT, so per-page reads/writes are wrapped individually and
counted as failures rather than crashing the run.

Usage:
  python render_pages.py                  # render everything in the manifest
  python render_pages.py --limit 40       # smoke test
  python render_pages.py --workers 4
"""

import argparse
import csv
import logging
import multiprocessing
import os
from collections import defaultdict
from pathlib import Path

import fitz

log = logging.getLogger("render_pages")

# Must match production: pipeline/page_renderer.py render_page_uri() and
# config.py RENDER_DPI / JPEG_QUALITY.
DPI = 110
JPEG_QUALITY = 80

ML_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ML_DIR / "data" / "pages_manifest.csv"
DEFAULT_OUT_DIR = Path("/Volumes/One Touch/stem_diagrams_data/ml_pages/")


def out_name(arxiv_id, page_no):
    return f"{arxiv_id.replace('/', '_')}_p{page_no:03d}.jpg"


def load_manifest(manifest_path, out_dir, limit):
    """Group manifest rows by pdf_path, dropping rows already rendered.

    Returns (jobs, skipped): jobs is a list of (pdf_path, pages) where pages
    is [(arxiv_id, page_no, dest_path), ...]; skipped is how many rows already
    had their output JPEG on disk.
    """
    by_pdf = defaultdict(list)
    skipped = 0
    with open(manifest_path, newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if limit and i >= limit:
                break
            page_no = int(row["page_no"])
            dest = out_dir / out_name(row["arxiv_id"], page_no)
            if dest.exists():
                skipped += 1
                continue
            by_pdf[row["pdf_path"]].append((row["arxiv_id"], page_no, dest))
    return list(by_pdf.items()), skipped


def render_group(job):
    """Render every requested page of one PDF; return (rendered, failed)."""
    pdf_path, pages = job
    rendered = failed = 0
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        log.warning("cannot open %s: %s", pdf_path, exc)
        return rendered, len(pages)

    try:
        with doc:
            for arxiv_id, page_no, dest in pages:
                try:
                    pix = doc[page_no - 1].get_pixmap(dpi=DPI)
                    dest.write_bytes(pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY))
                    rendered += 1
                except Exception as exc:
                    # unreadable page or a transient ExFAT I/O hiccup — skip it
                    failed += 1
                    log.warning("failed %s p.%d (%s): %s",
                                arxiv_id, page_no, pdf_path, exc)
    except Exception as exc:
        # something went wrong closing/iterating the doc itself; count
        # whatever wasn't already tallied as failed rather than crash
        failed += len(pages) - rendered - failed
        log.warning("group failed %s: %s", pdf_path, exc)
    return rendered, failed


def _init_worker():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s", datefmt="%H:%M:%S")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                        help="pages_manifest.csv path")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help="directory to write rendered JPEGs into")
    parser.add_argument("--limit", type=int, default=0,
                        help="only render the first N manifest rows (0 = all)")
    parser.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 2),
                        help="worker processes (one PDF opened at a time per worker)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s", datefmt="%H:%M:%S")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs, skipped = load_manifest(Path(args.manifest), out_dir, args.limit)
    n_rows = skipped + sum(len(pages) for _, pages in jobs)
    log.info("manifest: %d rows, %d already rendered, %d PDFs to open (workers=%d)",
             n_rows, skipped, len(jobs), args.workers)

    rendered = failed = 0
    if jobs:
        with multiprocessing.Pool(args.workers, initializer=_init_worker) as pool:
            for i, (r, f) in enumerate(pool.imap_unordered(render_group, jobs), start=1):
                rendered += r
                failed += f
                if i % 50 == 0 or i == len(jobs):
                    log.info("progress: %d/%d PDFs done (rendered=%d failed=%d)",
                             i, len(jobs), rendered, failed)

    log.info("done: rendered=%d skipped-existing=%d failed=%d", rendered, skipped, failed)
    print(f"rendered={rendered} skipped-existing={skipped} failed={failed}")


if __name__ == "__main__":
    main()
