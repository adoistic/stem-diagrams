"""Deterministic figure extraction from born-digital PDFs — no OCR, no ML.

Three signals, all geometric:
  1. embedded images (get_images)      -> raster/photo/exported figures
  2. vector-path clusters (get_drawings) -> native TikZ/PGF line art
  3. caption anchoring (get_text)        -> validate + rescue missed regions

Returns candidate figure crops as PIL images plus provenance. A downstream
classifier decides which are proper diagrams.
"""

import io
import re

import fitz
from PIL import Image

CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?\.?\s*\d+)", re.IGNORECASE)


def _merge_rects(rects, gap=14):
    rects = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        while rects:
            r = fitz.Rect(rects.pop())
            grew = True
            while grew:
                grew = False
                rem = []
                for s in rects:
                    ri = fitz.Rect(r.x0 - gap, r.y0 - gap, r.x1 + gap, r.y1 + gap)
                    if ri.intersects(s):
                        r |= s
                        grew = True
                        changed = True
                    else:
                        rem.append(s)
                rects = rem
            out.append(r)
        rects = out
    return rects


def _overlap_frac(a, b):
    inter = a & b
    if inter.is_empty:
        return 0.0
    return abs(inter) / min(abs(a), abs(b) or 1)


def _clip_to_pil(page, rect, dpi):
    pix = page.get_pixmap(clip=rect, dpi=dpi)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _caption_below(blocks, rect):
    """The figure caption is the text just under the figure. Take the nearest
    text block below the figure that horizontally overlaps it; if it reads like
    a caption ("Figure 3 ..."), append the following paragraph too. Purely
    positional — no model, no summarization."""
    below = []
    for b in blocks:
        bx0, by0, bx1, by1, txt = b[0], b[1], b[2], b[3], b[4].strip()
        if not txt:
            continue
        if rect.y1 - 3 <= by0 <= rect.y1 + 260 and not (bx1 < rect.x0 or bx0 > rect.x1):
            below.append((by0, txt))
    below.sort()
    if not below:
        return ""
    # prefer an explicit caption ("Figure 3 ...") within the search band; take it
    # plus the following paragraph. Otherwise fall back to the nearest block.
    for i, (_y, t) in enumerate(below):
        if re.match(r"(?i)(fig(ure)?|table|scheme)\b", t):
            cap = t + (" " + below[i + 1][1] if i + 1 < len(below) else "")
            return re.sub(r"\s+", " ", cap).strip()[:800]
    return re.sub(r"\s+", " ", below[0][1]).strip()[:800]


def extract_page(page, min_area_frac=0.03, max_area_frac=0.92, dpi=150,
                 min_pt=55, max_aspect=6.0):
    """Return candidate figure dicts for one page:
    {method, bbox, area_frac, image (PIL)}."""
    W, H = page.rect.width, page.rect.height
    parea = W * H
    page_clip = fitz.Rect(0, 0, W, H)
    cands = []

    # 1) embedded images
    img_rects = []
    for im in page.get_images(full=True):
        for r in page.get_image_rects(im[0]):
            r = r & page_clip
            if r.is_empty:
                continue
            af = abs(r) / parea
            if min_area_frac <= af <= max_area_frac and r.width > min_pt and r.height > min_pt:
                asp = max(r.width, r.height) / max(1, min(r.width, r.height))
                if asp <= max_aspect:
                    img_rects.append(r)
                    cands.append({"method": "image", "bbox": r, "area_frac": af})

    # 2) vector clusters (skip regions already covered by an embedded image)
    dr = [d["rect"] for d in page.get_drawings()
          if d["rect"].width > 3 and d["rect"].height > 3]
    for c in _merge_rects(dr):
        c = c & page_clip
        if c.is_empty:
            continue
        af = abs(c) / parea
        if not (min_area_frac <= af <= max_area_frac):
            continue
        if c.width <= min_pt or c.height <= min_pt:
            continue
        if max(c.width, c.height) / max(1, min(c.width, c.height)) > max_aspect:
            continue
        if any(_overlap_frac(c, ir) > 0.6 for ir in img_rects):
            continue
        cands.append({"method": "vector", "bbox": c, "area_frac": af})

    # dedupe near-duplicate candidates (keep larger)
    cands.sort(key=lambda x: -x["area_frac"])
    kept = []
    for c in cands:
        if all(_overlap_frac(c["bbox"], k["bbox"]) < 0.6 for k in kept):
            kept.append(c)

    # render crops + grab the caption below each figure (deterministic)
    blocks = page.get_text("blocks")
    for c in kept:
        b = c["bbox"]
        pad = fitz.Rect(max(0, b.x0 - 4), max(0, b.y0 - 4),
                        min(W, b.x1 + 4), min(H, b.y1 + 4))
        c["image"] = _clip_to_pil(page, pad, dpi)
        c["caption"] = _caption_below(blocks, b)
        c["bbox"] = [round(b.x0), round(b.y0), round(b.x1), round(b.y1)]
    return kept


def has_captions(page):
    return any(CAPTION_RE.match(b[4]) for b in page.get_text("blocks"))


def extract_pdf(pdf_path, max_pages=0, **kw):
    """Yield (page_no, candidate) for every figure candidate in the PDF."""
    with fitz.open(pdf_path) as doc:
        n = doc.page_count if not max_pages else min(doc.page_count, max_pages)
        for pno in range(n):
            page = doc[pno]
            for cand in extract_page(page, **kw):
                cand["page"] = pno + 1
                yield pno + 1, cand
