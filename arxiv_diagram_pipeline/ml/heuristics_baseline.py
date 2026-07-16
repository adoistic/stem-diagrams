#!/usr/bin/env python3
"""Approach A: cheap-signal baseline (no neural nets).

Features per crop: file size, dimensions, aspect, grayscale stats, content
fraction, unique-color proxy. Gradient-boosted trees on the silver 4-class.
This is the floor every learned model must beat.
"""

import logging

import numpy as np
from PIL import Image
from sklearn.ensemble import HistGradientBoostingClassifier

import common

log = logging.getLogger("heuristics")


def features(path):
    import os
    size = os.path.getsize(path)
    with Image.open(path) as im:
        w, h = im.size
        g = im.convert("L")
        g.thumbnail((256, 256))
        a = np.asarray(g, dtype=np.float32)
        rgb = im.convert("RGB")
        rgb.thumbnail((64, 64))
        colors = len(set(map(tuple, np.asarray(rgb).reshape(-1, 3)[::7])))
    mode = np.bincount(a.astype(np.uint8).flatten()).argmax()
    content_frac = float((np.abs(a - mode) > 16).mean())
    edge = np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()
    return [size, w, h, max(w, h) / max(1, min(w, h)), float(a.std()),
            content_frac, float(edge), colors,
            float((a > 240).mean()), float((a < 32).mean())]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    rows = common.load_crops_manifest()
    X, keep = [], []
    for i, r in enumerate(rows):
        try:
            X.append(features(r["path"]))
            keep.append(r)
        except Exception:
            continue
        if (i + 1) % 500 == 0:
            log.info("featurized %d/%d", i + 1, len(rows))
    X = np.array(X)
    y4 = np.array([common.CLS_TO_IDX[r["cls"]] for r in keep])
    split = np.array([r["split"] for r in keep])
    is_diag = (y4 == 0).astype(int)
    tr, va, te = split == "train", split == "val", split == "test"

    clf = HistGradientBoostingClassifier(random_state=0)
    clf.fit(X[tr], y4[tr])
    pred4_val = clf.predict(X[va])
    m = common.binary_metrics(is_diag[va], (pred4_val == 0).astype(int))
    m["acc4"] = round(float((pred4_val == y4[va]).mean()), 4)

    common.save_predictions("heuristics_gbt", "val",
                            [r["image_id"] for r, k in zip(keep, va) if k],
                            pred4_val, clf.predict_proba(X[va]))
    common.save_predictions("heuristics_gbt", "test",
                            [r["image_id"] for r, k in zip(keep, te) if k],
                            clf.predict(X[te]), clf.predict_proba(X[te]))
    common.record_result("heuristics_gbt", "heuristic",
                         {"features": 10, "model": "HistGradientBoosting"},
                         m, notes=f"4cls-val-acc {m['acc4']}")
    log.info("heuristics val: binary acc %.4f f1 %.4f (4cls %.4f)",
             m["acc"], m["f1"], m["acc4"])


if __name__ == "__main__":
    main()
