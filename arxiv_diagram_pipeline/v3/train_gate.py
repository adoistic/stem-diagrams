#!/usr/bin/env python3
"""Retrain the diagram gate (logreg on frozen SigLIP2 features) and pickle it.

The gate is the study's winner: frozen SigLIP2 embedding -> 4-class logistic
regression (diagram / data_plot / photo / fragment). We keep only the fitted
sklearn model; SigLIP2 is loaded at inference time from the HF cache.
"""

import csv
import pickle
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

ML = Path(__file__).resolve().parent.parent / "ml"
CLASSES = ["diagram", "data_plot", "photo", "fragment_junk"]
C2I = {c: i for i, c in enumerate(CLASSES)}
OUT = Path(__file__).resolve().parent / "gate_logreg.pkl"


def main():
    rows = list(csv.DictReader(open(ML / "data" / "crops_manifest.csv")))
    npz = np.load(ML / "cache" / "siglip2_crops_manifest.npz")
    pos = {int(i): k for k, i in enumerate(npz["ids"])}
    emb = npz["embeddings"]

    X, y = [], []
    for r in rows:
        k = pos.get(int(r["image_id"]))
        if k is not None:
            X.append(emb[k])
            y.append(C2I[r["cls"]])
    X, y = np.array(X), np.array(y)
    # train on everything we have — this is the deployed gate, not an experiment
    clf = LogisticRegression(max_iter=3000, C=1.0, class_weight="balanced")
    clf.fit(X, y)
    acc = (clf.predict(X) == y).mean()
    OUT.write_bytes(pickle.dumps({"clf": clf, "classes": CLASSES,
                                  "backbone": "google/siglip2-base-patch16-224",
                                  "dim": X.shape[1]}))
    print(f"trained on {len(y)} crops, train acc {acc:.3f}, saved -> {OUT}")
    print("class distribution:", {c: int((y == i).sum()) for i, c in enumerate(CLASSES)})


if __name__ == "__main__":
    main()
