#!/usr/bin/env python3
"""Extract frozen-backbone image embeddings and cache them to disk.

Runs a chosen pretrained vision backbone over every image in a manifest CSV
(image_id, path, ... — extra columns are ignored) and writes L2-normalized
embeddings to ml/cache/, so downstream probe classifiers (crops now, page
renders later) can train instantly against a fixed feature matrix instead of
re-running the backbone every time.

Backbones:
  siglip2     google/siglip2-base-patch16-224 (transformers AutoModel,
              get_image_features()) — also serves zero-shot later, but this
              script only caches plain image features.
  dinov2      timm vit_base_patch14_reg4_dinov2.lvd142m (ungated)
  dinov3      timm vit_base_patch16_dinov3.lvd1689m — added because timm
              1.0.28 hosts these ungated (unlike Meta's gated facebook/dinov3
              repos); dinov2 remains the safe default regardless.
  mobileclip  timm fastvit_mci* (Apple MobileCLIP image towers); falls back
              to timm mobilenetv4_conv_medium.e500_r256_in1k if none of the
              fastvit_mci* pretrained tags load.

Usage:
  python extract_embeddings.py --backbone siglip2
  python extract_embeddings.py --backbone dinov2 --manifest data/pages_manifest_crops.csv
  python extract_embeddings.py --backbone mobileclip --force
"""

import argparse
import csv
import hashlib
import json
import logging
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ML_DIR = Path(__file__).resolve().parent
CACHE_DIR = ML_DIR / "cache"
DEFAULT_MANIFEST = ML_DIR / "data" / "crops_manifest.csv"

log = logging.getLogger(__name__)

BATCH_SIZE_MPS = 64
BATCH_SIZE_CPU = 32
PROGRESS_EVERY = 500

SIGLIP2_MODEL = "google/siglip2-base-patch16-224"
DINOV2_MODEL = "vit_base_patch14_reg4_dinov2.lvd142m"
DINOV3_MODEL = "vit_base_patch16_dinov3.lvd1689m"
MOBILECLIP_FALLBACK = "mobilenetv4_conv_medium.e500_r256_in1k"


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_manifest_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _build_timm_model(model_name, device):
    """Load a timm model with its recommended eval transform; return an
    embed_batch(pil_images) -> np.ndarray[N, D] closure."""
    import timm
    from timm.data import create_transform, resolve_model_data_config

    model = timm.create_model(model_name, pretrained=True, num_classes=0)
    model.eval()
    model.to(device=device, dtype=torch.float32)
    data_cfg = resolve_model_data_config(model=model)
    transform = create_transform(**data_cfg, is_training=False)

    def embed_batch(images):
        batch = torch.stack([transform(img.convert("RGB")) for img in images])
        batch = batch.to(device=device, dtype=torch.float32)
        with torch.no_grad():
            feats = model(batch)
        return feats.float().cpu().numpy()

    return embed_batch


def _build_siglip2(device):
    from transformers import AutoModel, AutoProcessor

    model = AutoModel.from_pretrained(SIGLIP2_MODEL)
    model.eval()
    model.to(device=device, dtype=torch.float32)
    processor = AutoProcessor.from_pretrained(SIGLIP2_MODEL)

    def embed_batch(images):
        inputs = processor(images=images, return_tensors="pt")
        inputs = {k: v.to(device=device) for k, v in inputs.items()}
        with torch.no_grad():
            out = model.get_image_features(**inputs)
        # Some transformers versions wrap this in BaseModelOutputWithPooling
        # (via @can_return_tuple) instead of returning the tensor directly.
        feats = out if torch.is_tensor(out) else out.pooler_output
        return feats.float().cpu().numpy()

    return embed_batch, SIGLIP2_MODEL


def _build_mobileclip(device):
    import timm

    candidates = timm.list_models("fastvit_mci*", pretrained=True)
    for name in candidates:
        try:
            embed_batch = _build_timm_model(name, device)
        except Exception:
            log.warning("mobileclip candidate %s failed to load, trying next", name,
                        exc_info=True)
            continue
        print(f"[mobileclip] using MobileCLIP backbone: {name}")
        return embed_batch, name

    print(f"[mobileclip] no fastvit_mci* candidate loaded; falling back to "
          f"{MOBILECLIP_FALLBACK}")
    embed_batch = _build_timm_model(MOBILECLIP_FALLBACK, device)
    return embed_batch, MOBILECLIP_FALLBACK


def get_backbone(backbone, device):
    """Return (embed_batch(pil_images) -> np.ndarray[N, D], resolved_model_name)."""
    if backbone == "siglip2":
        return _build_siglip2(device)
    if backbone == "dinov2":
        return _build_timm_model(DINOV2_MODEL, device), DINOV2_MODEL
    if backbone == "dinov3":
        return _build_timm_model(DINOV3_MODEL, device), DINOV3_MODEL
    if backbone == "mobileclip":
        return _build_mobileclip(device)
    raise ValueError(f"unknown backbone: {backbone}")


def extract(backbone, manifest_path, force):
    manifest_path = Path(manifest_path)
    manifest_sha = _sha256_file(manifest_path)
    cache_path = CACHE_DIR / f"{backbone}_{manifest_path.stem}.npz"
    sidecar_path = cache_path.with_suffix(".json")

    if cache_path.exists() and not force:
        log.info("cache already exists, skipping (use --force to overwrite): %s", cache_path)
        return cache_path

    # EMB_DEVICE=cpu overrides — torch-MPS occasionally wedges on Metal after
    # other GPU processes were killed; CPU is reliable for this one-off cache.
    import os
    device = os.getenv("EMB_DEVICE") or (
        "mps" if torch.backends.mps.is_available() else "cpu")
    batch_size = BATCH_SIZE_MPS if device == "mps" else BATCH_SIZE_CPU
    log.info("backbone=%s device=%s batch_size=%d", backbone, device, batch_size)

    rows = _read_manifest_rows(manifest_path)
    log.info("manifest rows: %d (%s)", len(rows), manifest_path)

    embed_batch, model_name = get_backbone(backbone, device)
    log.info("resolved model: %s", model_name)

    ids = []
    chunks = []
    n_skipped = 0
    batch_imgs = []
    batch_ids = []

    def flush():
        if not batch_imgs:
            return
        feats = embed_batch(batch_imgs)
        chunks.append(feats)
        ids.extend(batch_ids)
        batch_imgs.clear()
        batch_ids.clear()

    for i, row in enumerate(rows, 1):
        img_path = row["path"]
        try:
            with Image.open(img_path) as im:
                img = im.convert("RGB")
        except Exception as e:
            log.warning("unreadable image, skipping: %s (%s)", img_path, e)
            n_skipped += 1
            continue

        batch_imgs.append(img)
        batch_ids.append(int(row["image_id"]))
        if len(batch_imgs) >= batch_size:
            flush()

        if i % PROGRESS_EVERY == 0:
            log.info("processed %d/%d images (%d skipped)", i, len(rows), n_skipped)

    flush()

    if not chunks:
        log.error("no embeddings produced (all images unreadable?); aborting")
        sys.exit(1)

    embeddings = np.concatenate(chunks, axis=0).astype(np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = embeddings / norms
    ids_arr = np.array(ids, dtype=np.int64)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(cache_path, ids=ids_arr, embeddings=embeddings)
    sidecar = {
        "backbone": backbone,
        "model_name": model_name,
        "dim": int(embeddings.shape[1]),
        "n": int(embeddings.shape[0]),
        "device": device,
        "manifest_sha256": manifest_sha,
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    log.info("wrote %s: %d x %d embeddings (%d skipped)", cache_path,
              embeddings.shape[0], embeddings.shape[1], n_skipped)
    log.info("wrote %s", sidecar_path)
    return cache_path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backbone", required=True,
                         choices=["siglip2", "dinov2", "dinov3", "mobileclip"])
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for noisy in ("urllib3", "httpx", "huggingface_hub", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    extract(args.backbone, args.manifest, args.force)


if __name__ == "__main__":
    main()
