"""Combine detected diagram pages from many papers into one PDF per OCR batch.

The batch PDF keeps the original vector pages (no rasterization), so Mistral
OCR sees full quality, and a manifest [(arxiv_id, page_no), ...] records which
batch page came from which paper. Page k (0-based) of the batch PDF is
manifest[k] — that is the entire mapping contract.
"""

import logging

import fitz

import config

log = logging.getLogger(__name__)


def build_batch_pdf(manifest, pdf_path_for):
    """Assemble the pages in `manifest` into a single PDF; returns pdf bytes.

    manifest: list of (arxiv_id, page_no) tuples, page_no 1-based.
    pdf_path_for: callable arxiv_id -> Path of that paper's source PDF.
    Pages whose source PDF is missing/corrupt are SKIPPED — the caller must
    pass a manifest it is prepared to shrink (use validate_manifest first).
    """
    out = fitz.open()
    for arxiv_id, page_no in manifest:
        src = fitz.open(pdf_path_for(arxiv_id))
        out.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
        src.close()
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data


def validate_manifest(manifest, pdf_path_for):
    """Drop manifest entries whose source PDF can't be opened or is too short.
    Returns (valid_manifest, dropped)."""
    valid, dropped = [], []
    cache = {}
    for arxiv_id, page_no in manifest:
        if arxiv_id not in cache:
            try:
                with fitz.open(pdf_path_for(arxiv_id)) as doc:
                    cache[arxiv_id] = doc.page_count
            except Exception as exc:
                log.warning("batch: cannot open %s (%s)", arxiv_id, exc)
                cache[arxiv_id] = 0
        if 1 <= page_no <= cache[arxiv_id]:
            valid.append((arxiv_id, page_no))
        else:
            dropped.append((arxiv_id, page_no))
    return valid, dropped


def split_oversized(manifest, pdf_path_for, max_mb=None):
    """Build batch PDFs, splitting the manifest in half recursively whenever
    the assembled PDF exceeds max_mb. Yields (sub_manifest, pdf_bytes)."""
    max_bytes = (max_mb or config.OCR_BATCH_MAX_MB) * 1024 * 1024
    data = build_batch_pdf(manifest, pdf_path_for)
    if len(data) <= max_bytes or len(manifest) <= 1:
        yield manifest, data
        return
    mid = len(manifest) // 2
    log.info("batch: %d pages -> %.1f MB, splitting", len(manifest), len(data) / 1e6)
    yield from split_oversized(manifest[:mid], pdf_path_for, max_mb)
    yield from split_oversized(manifest[mid:], pdf_path_for, max_mb)
