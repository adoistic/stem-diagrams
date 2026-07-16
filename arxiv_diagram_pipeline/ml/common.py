"""Shared utilities for the classifier experiments.

Conventions (see research/fable_ml_method.md):
- every experiment appends a JSON row to ml/results/ and one line to RESULTS.md
- test-split predictions are SAVED but never evaluated here; evaluate.py is
  the only reader of test/gold outcomes
"""

import csv
import hashlib
import json
import time
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
CACHE_DIR = ML_DIR / "cache"
RESULTS_DIR = ML_DIR / "results"
PREDS_DIR = ML_DIR / "preds"

CLASSES = ["diagram", "data_plot", "photo", "fragment_junk"]
CLS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}


def load_crops_manifest():
    rows = []
    with open(DATA_DIR / "crops_manifest.csv") as f:
        for r in csv.DictReader(f):
            r["image_id"] = int(r["image_id"])
            rows.append(r)
    return rows


def load_pages_manifest():
    rows = []
    with open(DATA_DIR / "pages_manifest.csv") as f:
        for r in csv.DictReader(f):
            r["page_no"] = int(r["page_no"])
            r["has_diagram"] = int(r["has_diagram"])
            rows.append(r)
    return rows


def manifest_sha():
    return hashlib.sha256(
        (DATA_DIR / "splits.json").read_bytes()).hexdigest()[:16]


def load_embeddings(backbone, manifest_stem="crops_manifest"):
    """Return (ids array, embeddings array) from the cache."""
    npz = np.load(CACHE_DIR / f"{backbone}_{manifest_stem}.npz")
    return npz["ids"], npz["embeddings"]


def align(rows, ids, embeddings):
    """Align manifest rows with cached embeddings; returns
    (kept_rows, X, y4, is_diagram, split array)."""
    pos = {int(i): k for k, i in enumerate(ids)}
    kept, idx = [], []
    for r in rows:
        k = pos.get(r["image_id"])
        if k is not None:
            kept.append(r)
            idx.append(k)
    X = embeddings[idx]
    y4 = np.array([CLS_TO_IDX[r["cls"]] for r in kept])
    is_diag = (y4 == 0).astype(int)
    split = np.array([r["split"] for r in kept])
    return kept, X, y4, is_diag, split


def binary_metrics(y_true_bin, y_pred_bin):
    from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                                 recall_score)
    return {
        "acc": round(float(accuracy_score(y_true_bin, y_pred_bin)), 4),
        "f1": round(float(f1_score(y_true_bin, y_pred_bin)), 4),
        "precision": round(float(precision_score(y_true_bin, y_pred_bin,
                                                 zero_division=0)), 4),
        "recall": round(float(recall_score(y_true_bin, y_pred_bin,
                                           zero_division=0)), 4),
    }


def save_predictions(name, split_name, image_ids, pred4, prob4):
    PREDS_DIR.mkdir(exist_ok=True)
    np.savez(PREDS_DIR / f"{name}_{split_name}.npz",
             ids=np.asarray(image_ids), pred4=pred4, prob4=prob4)


def record_result(name, kind, config_dict, val_metrics, notes=""):
    RESULTS_DIR.mkdir(exist_ok=True)
    row = {
        "name": name, "kind": kind, "config": config_dict,
        "val": val_metrics, "manifest_sha": manifest_sha(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "notes": notes,
    }
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(row, indent=2))
    line = (f"| {name} | {kind} | acc={val_metrics.get('acc')} "
            f"f1={val_metrics.get('f1')} p={val_metrics.get('precision')} "
            f"r={val_metrics.get('recall')} | {notes} |\n")
    md = ML_DIR / "RESULTS.md"
    if not md.exists():
        md.write_text("# Experiment log (validation split — binary accept/reject)\n\n"
                      "| experiment | kind | val metrics | notes |\n"
                      "|---|---|---|---|\n")
    with open(md, "a") as f:
        f.write(line)
    return row
