"""Render PDF pages to JPEG images with PyMuPDF."""

import base64

import fitz


def page_count(pdf_path):
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_page(pdf_path, page_number, dest_path, dpi=110, quality=80):
    """Render one page (1-based) to a JPEG file."""
    with fitz.open(pdf_path) as doc:
        pix = doc[page_number - 1].get_pixmap(dpi=dpi)
        dest_path.write_bytes(pix.tobytes("jpeg", jpg_quality=quality))
    return dest_path


def to_data_uri(image_path):
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    suffix = image_path.suffix.lstrip(".").lower()
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{b64}"
