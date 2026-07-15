"""Run Mistral OCR on a page image and save the images it extracts."""

import base64
import logging
import time

import requests

import config
from pipeline.page_renderer import to_data_uri

log = logging.getLogger(__name__)

RETRYABLE_STATUS = (429, 500, 502, 503, 504)


class MissingAPIKeyError(RuntimeError):
    pass


def ocr_page(page_image_path, retries=4):
    """OCR a single page image; returns the raw Mistral OCR response dict."""
    if not config.MISTRAL_API_KEY:
        raise MissingAPIKeyError("MISTRAL_API_KEY is empty — fill it in .env")

    payload = {
        "model": config.MISTRAL_OCR_MODEL,
        "document": {"type": "image_url", "image_url": to_data_uri(page_image_path)},
        "include_image_base64": True,
    }
    headers = {
        "Authorization": f"Bearer {config.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                config.MISTRAL_OCR_URL, json=payload, headers=headers, timeout=180
            )
            if resp.status_code in RETRYABLE_STATUS:
                raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("Mistral OCR failed (%s); retry %d/%d in %ds",
                        exc, attempt, retries, wait)
            time.sleep(wait)


def extract_markdown(ocr_response):
    return "\n\n".join(p.get("markdown", "") for p in ocr_response.get("pages", []))


def save_images(ocr_response, dest_dir, filename_prefix):
    """Save every base64-encoded image in the OCR response; return saved paths."""
    saved = []
    counter = 0
    for page in ocr_response.get("pages", []):
        for img in page.get("images", []):
            b64 = img.get("image_base64") or ""
            if not b64:
                continue
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[1]
            counter += 1
            img_id = img.get("id", "")
            ext = img_id.rsplit(".", 1)[-1].lower() if "." in img_id else "jpeg"
            if ext not in ("png", "jpg", "jpeg", "webp"):
                ext = "jpeg"
            path = dest_dir / f"{filename_prefix}_{counter:02d}.{ext}"
            path.write_bytes(base64.b64decode(b64))
            saved.append(path)
    return saved
