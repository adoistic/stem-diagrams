"""Cheap local pre-filter for figure images extracted by Mistral OCR.

Rejects obvious junk crops (blank pages, tiny slivers, logos, thin banner
strips) before spending an LLM call to label them. No network calls; pure
Pillow/stdlib checks on the file already on disk.
"""

import logging
import os
from collections import Counter

from PIL import Image

log = logging.getLogger(__name__)

MIN_FILE_BYTES = 8 * 1024
MIN_DIM_PX = 80
MAX_ASPECT_RATIO = 8
DOWNSAMPLE_MAX_PX = 256
BLANK_STDDEV_THRESHOLD = 8.0
CONTENT_PIXEL_DELTA = 16
MIN_CONTENT_FRACTION = 0.02


def _downsampled_grayscale(image):
    """Return a grayscale copy of image, downsampled to fit DOWNSAMPLE_MAX_PX."""
    gray = image.convert("L")
    long_side = max(gray.width, gray.height)
    if long_side > DOWNSAMPLE_MAX_PX:
        scale = DOWNSAMPLE_MAX_PX / long_side
        new_size = (max(1, round(gray.width * scale)), max(1, round(gray.height * scale)))
        gray = gray.resize(new_size)
    return gray


def _pixel_stddev(gray):
    pixels = gray.tobytes()
    n = len(pixels)
    if n == 0:
        return 0.0
    mean = sum(pixels) / n
    variance = sum((p - mean) ** 2 for p in pixels) / n
    return variance ** 0.5


def _content_fraction(gray):
    pixels = gray.tobytes()
    n = len(pixels)
    if n == 0:
        return 0.0
    modal_value, _ = Counter(pixels).most_common(1)[0]
    off_modal = sum(1 for p in pixels if abs(p - modal_value) > CONTENT_PIXEL_DELTA)
    return off_modal / n


def local_reject_reason(image_path):
    """Return "" if the image passes cheap local checks, else a short
    kebab-case reason string. Never raises — any internal error returns ""
    (pass) so a filter bug can't drop good data."""
    try:
        try:
            size = os.path.getsize(image_path)
        except OSError:
            return ""
        if size < MIN_FILE_BYTES:
            return "tiny-file"

        try:
            with Image.open(image_path) as img:
                img.verify()
            with Image.open(image_path) as img:
                width, height = img.width, img.height
                gray = _downsampled_grayscale(img)
        except Exception:
            return "unreadable"

        if width < MIN_DIM_PX or height < MIN_DIM_PX:
            return "tiny-dims"

        long_side = max(width, height)
        short_side = max(1, min(width, height))
        if long_side / short_side > MAX_ASPECT_RATIO:
            return "extreme-aspect"

        if _pixel_stddev(gray) < BLANK_STDDEV_THRESHOLD:
            return "near-blank"

        if _content_fraction(gray) < MIN_CONTENT_FRACTION:
            return "low-content"

        return ""
    except Exception:
        log.debug("local_reject_reason: unexpected error on %s", image_path, exc_info=True)
        return ""


if __name__ == "__main__":
    import random
    import tempfile

    def _save(img, suffix, quality=90):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        img.save(path, quality=quality)
        return path

    def _check(label, path, expected_reasons):
        reason = local_reject_reason(path)
        size = os.path.getsize(path)
        ok = reason in expected_reasons
        status = "OK" if ok else "UNEXPECTED"
        print(f"[{status}] {label}: reason={reason!r} size={size}B -> {path}")
        return ok

    random.seed(0)
    all_ok = True

    # (a) near-white 500x500 JPEG -> near-blank or low-content.
    # A perfectly flat white image JPEG-compresses to well under the
    # tiny-file floor, so add a whisper of noise (stddev ~1-2, still far
    # below BLANK_STDDEV_THRESHOLD) purely to keep the encoded file large
    # enough to reach the near-blank/low-content checks.
    white_pixels = [
        (v, v, v) for v in (255 - random.randint(0, 4) for _ in range(500 * 500))
    ]
    white_img = Image.new("RGB", (500, 500))
    white_img.putdata(white_pixels)
    white_path = _save(white_img, ".jpg")
    all_ok &= _check("white image", white_path, {"near-blank", "low-content"})

    # (b) 500x500 random noise -> passes all checks
    noise_pixels = [
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(500 * 500)
    ]
    noise_img = Image.new("RGB", (500, 500))
    noise_img.putdata(noise_pixels)
    noise_path = _save(noise_img, ".jpg", quality=95)
    if os.path.getsize(noise_path) < MIN_FILE_BYTES:
        # bump size if JPEG compression somehow shrank it below the floor
        noise_img.save(noise_path, quality=100)
    all_ok &= _check("random noise image", noise_path, {""})

    # (c) 2000x100 noisy strip -> extreme-aspect
    strip_pixels = [
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(2000 * 100)
    ]
    strip_img = Image.new("RGB", (2000, 100))
    strip_img.putdata(strip_pixels)
    strip_path = _save(strip_img, ".jpg", quality=95)
    all_ok &= _check("noisy strip image", strip_path, {"extreme-aspect"})

    # (d) 50x50 noisy image -> tiny-file or tiny-dims
    small_pixels = [
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(50 * 50)
    ]
    small_img = Image.new("RGB", (50, 50))
    small_img.putdata(small_pixels)
    small_path = _save(small_img, ".jpg", quality=95)
    all_ok &= _check("tiny noisy image", small_path, {"tiny-file", "tiny-dims"})

    for p in (white_path, noise_path, strip_path, small_path):
        try:
            os.remove(p)
        except OSError:
            pass

    if not all_ok:
        print("image_filter self-test FAILED")
        exit(1)

    print("image_filter self-test OK")
    exit(0)
