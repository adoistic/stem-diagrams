#!/usr/bin/env python3
"""Honest latency/throughput bench for classifier backbone candidates on this
Apple Silicon Mac (mps) and its CPU -- for the paper's speed-vs-accuracy claims.

Measures, per model spec:
  - cold load time (construct model + load weights)
  - single-image latency (PIL open + preprocess + forward), p50/p95 over
    5 warmup + 30 timed reps
  - batch throughput at batch sizes 32 and 128 (1 warmup + 3 timed reps),
    images/sec, preprocessing included
  - peak process RSS (resource.getrusage)

Runs every model on both "mps" and "cpu" and writes one JSON per model to
ml/results/latency_{name}.json.

Sample images live on a slow external USB drive; a cold read there is
~30-160ms, which would swamp backbone compute entirely. We pre-warm the OS
file cache for the sampled images before any timing starts so the numbers
reflect model speed, not the drive's seek time.
"""

import argparse
import gc
import glob
import json
import logging
import os
import platform
import random
import resource
import sys
import time
from pathlib import Path

import torch
from PIL import Image

ML_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ML_DIR.parent))
from pipeline.image_filter import _downsampled_grayscale, _pixel_stddev  # noqa: E402

log = logging.getLogger(__name__)

IMAGES_ROOT = Path("/Volumes/One Touch/stem_diagrams_data/images_v2")
RESULTS_DIR = ML_DIR / "results"
IMAGE_EXTS = (".jpg", ".jpeg")
SAMPLE_SEED = 20260716

N_WARMUP_SINGLE = 5
N_REPS_SINGLE = 30
BATCH_SIZES = (32, 128)
N_WARMUP_BATCH = 1
N_REPS_BATCH = 3


def gather_images(n_images):
    """Glob jpg/jpeg files under IMAGES_ROOT, skip AppleDouble ._ files, and
    return a reproducible random sample of n_images paths, pre-warmed into
    the OS file cache so later timing reflects compute, not disk seeks."""
    paths = []
    for ext in IMAGE_EXTS:
        paths.extend(glob.glob(str(IMAGES_ROOT / "**" / f"*{ext}"), recursive=True))
    paths = sorted(p for p in paths if not os.path.basename(p).startswith("._"))
    if not paths:
        raise SystemExit(f"no images found under {IMAGES_ROOT}")

    rng = random.Random(SAMPLE_SEED)
    if len(paths) <= n_images:
        log.warning("only %d images found under %s, wanted %d -- sampling with repeats",
                    len(paths), IMAGES_ROOT, n_images)
        sample = [paths[i % len(paths)] for i in range(n_images)]
    else:
        sample = rng.sample(paths, n_images)

    log.info("sampled %d images (of %d found) under %s", len(sample), len(paths), IMAGES_ROOT)

    log.info("pre-warming OS file cache for sampled images (drive is a slow external USB HDD; "
             "a cold read there is 30-160ms and would swamp backbone timings)")
    for p in sample:
        try:
            with open(p, "rb") as f:
                f.read()
        except OSError:
            log.warning("failed to pre-warm %s", p, exc_info=True)

    return sample


def peak_rss_mb():
    """resource.getrusage ru_maxrss is bytes on macOS, KB on Linux."""
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return ru / (1024 * 1024)
    return ru / 1024


def percentile(values, pct):
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ---------------------------------------------------------------------------
# heuristic (no torch): mirrors pipeline/image_filter.py's cheap local
# pre-filter cost -- PIL-open + grayscale + downsample + stddev.
# ---------------------------------------------------------------------------

def _heuristic_process(path):
    with Image.open(path) as img:
        gray = _downsampled_grayscale(img)
        return _pixel_stddev(gray)


def bench_heuristic(image_paths):
    log.info("benchmarking heuristic (pure PIL/stdlib, no torch, no device)")
    t0 = time.perf_counter()
    load_seconds = time.perf_counter() - t0  # no model/weights to load

    for p in image_paths[:N_WARMUP_SINGLE]:
        _heuristic_process(p)

    single_ms = []
    for i in range(N_REPS_SINGLE):
        p = image_paths[i % len(image_paths)]
        t0 = time.perf_counter()
        _heuristic_process(p)
        single_ms.append((time.perf_counter() - t0) * 1000)

    single_stats = {
        "p50_ms": percentile(single_ms, 50),
        "p95_ms": percentile(single_ms, 95),
        "mean_ms": sum(single_ms) / len(single_ms),
        "n_reps": N_REPS_SINGLE,
    }

    batch_stats = {}
    for bs in BATCH_SIZES:
        batch_paths = [image_paths[i % len(image_paths)] for i in range(bs)]

        for _ in range(N_WARMUP_BATCH):
            for p in batch_paths:
                _heuristic_process(p)

        rep_rates = []
        for _ in range(N_REPS_BATCH):
            t0 = time.perf_counter()
            for p in batch_paths:
                _heuristic_process(p)
            elapsed = time.perf_counter() - t0
            rep_rates.append(bs / elapsed)
        batch_stats[str(bs)] = {
            "images_per_sec": sum(rep_rates) / len(rep_rates),
            "reps_images_per_sec": rep_rates,
        }

    return {
        "load_seconds": load_seconds,
        "single_image": single_stats,
        "batch": batch_stats,
        "peak_rss_mb": peak_rss_mb(),
    }


# ---------------------------------------------------------------------------
# torch backbones: each loader returns
#   (resolved_name, params_millions, load_seconds, preprocess_fn, forward_fn)
# preprocess_fn(list_of_pil_images) -> batched tensor on device
# forward_fn(batched_tensor) -> runs the no_grad forward pass
# ---------------------------------------------------------------------------

def _load_timm_backbone(name, device):
    import timm

    t0 = time.perf_counter()
    model = timm.create_model(name, pretrained=True, num_classes=0)
    model.eval()
    model.to(device)
    load_seconds = time.perf_counter() - t0
    if device == "mps":
        torch.mps.synchronize()

    params_millions = sum(p.numel() for p in model.parameters()) / 1e6
    data_config = timm.data.resolve_model_data_config(model)
    transform = timm.data.create_transform(**data_config, is_training=False)

    def preprocess(pil_images):
        tensors = [transform(img.convert("RGB")) for img in pil_images]
        return torch.stack(tensors).to(device)

    def forward(x):
        with torch.no_grad():
            return model(x)

    return name, params_millions, load_seconds, preprocess, forward


def load_dinov2(device):
    return _load_timm_backbone("vit_base_patch14_reg4_dinov2.lvd142m", device)


def load_efficientnet(device):
    return _load_timm_backbone("efficientnet_b0.ra_in1k", device)


def load_mobileclip(device):
    import timm

    candidates = timm.list_models("fastvit_mci*", pretrained=True)
    if candidates:
        name = candidates[0]
        try:
            result = _load_timm_backbone(name, device)
            print(f"mobileclip: resolved to fastvit_mci variant {name}")
            log.info("mobileclip: resolved to fastvit_mci variant %s", name)
            return result
        except Exception:
            log.warning("mobileclip: %s failed to load, falling back", name, exc_info=True)

    fallback = "mobilenetv4_conv_medium.e500_r256_in1k"
    print(f"mobileclip: no usable fastvit_mci* pretrained weights, falling back to {fallback}")
    log.info("mobileclip: falling back to %s", fallback)
    return _load_timm_backbone(fallback, device)


def load_siglip2(device):
    from transformers import AutoModel, AutoProcessor

    name = "google/siglip2-base-patch16-224"
    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(name)
    model = AutoModel.from_pretrained(name)
    model.eval()
    model.to(device)
    load_seconds = time.perf_counter() - t0
    if device == "mps":
        torch.mps.synchronize()

    params_millions = sum(p.numel() for p in model.parameters()) / 1e6

    def preprocess(pil_images):
        inputs = processor(images=pil_images, return_tensors="pt")
        return inputs["pixel_values"].to(device)

    def forward(pixel_values):
        with torch.no_grad():
            return model.get_image_features(pixel_values=pixel_values)

    return name, params_millions, load_seconds, preprocess, forward


LOADERS = {
    "siglip2": load_siglip2,
    "dinov2": load_dinov2,
    "mobileclip": load_mobileclip,
    "efficientnet_b0": load_efficientnet,
}
MODEL_CHOICES = sorted(LOADERS) + ["heuristic"]


def bench_device(device, image_paths, load_seconds, preprocess, forward):
    def sync():
        if device == "mps":
            torch.mps.synchronize()

    sync()
    for p in image_paths[:N_WARMUP_SINGLE]:
        img = Image.open(p).convert("RGB")
        forward(preprocess([img]))
    sync()

    single_ms = []
    for i in range(N_REPS_SINGLE):
        p = image_paths[i % len(image_paths)]
        sync()
        t0 = time.perf_counter()
        img = Image.open(p).convert("RGB")
        x = preprocess([img])
        forward(x)
        sync()
        single_ms.append((time.perf_counter() - t0) * 1000)

    single_stats = {
        "p50_ms": percentile(single_ms, 50),
        "p95_ms": percentile(single_ms, 95),
        "mean_ms": sum(single_ms) / len(single_ms),
        "n_reps": N_REPS_SINGLE,
    }

    batch_stats = {}
    for bs in BATCH_SIZES:
        batch_paths = [image_paths[i % len(image_paths)] for i in range(bs)]

        def run_batch_once():
            imgs = [Image.open(p).convert("RGB") for p in batch_paths]
            x = preprocess(imgs)
            forward(x)
            sync()

        sync()
        for _ in range(N_WARMUP_BATCH):
            run_batch_once()
        sync()

        rep_rates = []
        for _ in range(N_REPS_BATCH):
            t0 = time.perf_counter()
            run_batch_once()
            elapsed = time.perf_counter() - t0
            rep_rates.append(bs / elapsed)
        batch_stats[str(bs)] = {
            "images_per_sec": sum(rep_rates) / len(rep_rates),
            "reps_images_per_sec": rep_rates,
        }

    return {
        "load_seconds": load_seconds,
        "single_image": single_stats,
        "batch": batch_stats,
        "peak_rss_mb": peak_rss_mb(),
    }


def run_full_benchmark(model_key, image_paths):
    if model_key == "heuristic":
        r_mps = bench_heuristic(image_paths)
        note = ("heuristic is pure PIL/stdlib (no torch); device is not "
                "applicable, numbers are identical under mps/cpu -- kept "
                "for JSON schema consistency with the torch backbones")
        r_cpu = dict(r_mps)
        r_mps = dict(r_mps, note=note)
        r_cpu = dict(r_cpu, note=note)
        resolved_name = "heuristic (PIL local pre-filter, mirrors pipeline/image_filter.py)"
        return {"mps": r_mps, "cpu": r_cpu}, resolved_name, 0.0

    load_fn = LOADERS[model_key]
    results = {}
    resolved_name = None
    params_millions = None
    for device in ("mps", "cpu"):
        if device == "mps" and not torch.backends.mps.is_available():
            log.warning("mps not available on this machine -- skipping mps run for %s", model_key)
            results["mps"] = None
            continue
        log.info("=== benchmarking %s on %s ===", model_key, device)
        gc.collect()
        if device == "mps":
            torch.mps.empty_cache()
        name, params, load_seconds, preprocess, forward = load_fn(device)
        resolved_name = name
        params_millions = params
        results[device] = bench_device(device, image_paths, load_seconds, preprocess, forward)
        del preprocess, forward
        gc.collect()

    return results, resolved_name, params_millions


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, choices=MODEL_CHOICES,
                        help="backbone spec to benchmark")
    parser.add_argument("--n-images", type=int, default=128,
                        help="number of sample images to draw for timing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s", datefmt="%H:%M:%S")

    log.info("machine: %s | torch %s", platform.platform(), torch.__version__)
    log.info("mps available: %s", torch.backends.mps.is_available())

    image_paths = gather_images(args.n_images)

    results, resolved_name, params_millions = run_full_benchmark(args.model, image_paths)

    payload = {
        "model": args.model,
        "model_name": resolved_name,
        "params_millions": params_millions,
        "n_images": args.n_images,
        "timestamp": time.time(),
        "machine": f"{platform.platform()} | torch {torch.__version__}",
        "mps": results.get("mps"),
        "cpu": results.get("cpu"),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"latency_{args.model}.json"
    out_path.write_text(json.dumps(payload, indent=2))
    log.info("wrote %s", out_path)

    for device in ("mps", "cpu"):
        r = results.get(device)
        if not r:
            continue
        log.info(
            "%s/%s: load=%.2fs single p50=%.1fms p95=%.1fms "
            "batch32=%.1f img/s batch128=%.1f img/s peak_rss=%.0fMB",
            args.model, device, r["load_seconds"],
            r["single_image"]["p50_ms"], r["single_image"]["p95_ms"],
            r["batch"]["32"]["images_per_sec"], r["batch"]["128"]["images_per_sec"],
            r["peak_rss_mb"])


if __name__ == "__main__":
    main()
