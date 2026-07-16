#!/usr/bin/env python3
"""Evaluate the DocLayout-YOLO page gate against GOLD page labels.

Reads results/detector_boxes.json (produced by detector_eval.py) and
data/gold_pages.csv; applies the validation-chosen thresholds from
results/detector_doclayout_yolo.json; reports gold accuracy/F1 with
bootstrap CIs, plus the silver-vs-gold comparison on the same pages.
"""

import csv
import json

import numpy as np

import common


def gate(entry, conf_t, area_frac):
    W, H = entry["img_wh"]
    for b in entry["boxes"]:
        if b["cls"] == "figure" and b["conf"] >= conf_t:
            x1, y1, x2, y2 = b["xyxy"]
            if (x2 - x1) * (y2 - y1) >= area_frac * W * H:
                return 1
    return 0


def main():
    boxes = json.loads((common.RESULTS_DIR / "detector_boxes.json").read_text())
    cfg = json.loads(
        (common.RESULTS_DIR / "detector_doclayout_yolo.json").read_text())["config"]
    conf_t, area = cfg["conf_t"], cfg["area_frac"]

    gold = {}
    with open(common.DATA_DIR / "gold_pages.csv") as f:
        for r in csv.DictReader(f):
            gold[f"{r['arxiv_id']}|{r['page_no']}"] = int(r["has_diagram"])

    keys = [k for k in gold if k in boxes]
    y = np.array([gold[k] for k in keys])
    p = np.array([gate(boxes[k], conf_t, area) for k in keys])
    silver = np.array([boxes[k]["has_diagram"] for k in keys])

    from sklearn.metrics import accuracy_score, f1_score
    def ci(yy, pp, fn):
        rng = np.random.default_rng(0)
        idx = np.arange(len(yy))
        vals = [fn(yy[s], pp[s]) for s in
                (rng.choice(idx, len(idx), replace=True) for _ in range(1000))]
        return round(float(np.percentile(vals, 2.5)), 4), \
            round(float(np.percentile(vals, 97.5)), 4)

    m = common.binary_metrics(y, p)
    m["acc_ci"] = ci(y, p, accuracy_score)
    m["f1_ci"] = ci(y, p, lambda a, b: f1_score(a, b, zero_division=0))
    m["n"] = len(keys)
    ms = common.binary_metrics(y, silver)
    print(f"detector vs GOLD pages (n={len(keys)}, conf={conf_t}, area={area}):")
    print(f"  detector: acc {m['acc']} CI{m['acc_ci']}  f1 {m['f1']} "
          f"CI{m['f1_ci']}  p {m['precision']} r {m['recall']}")
    print(f"  LLM teacher on same pages: acc {ms['acc']}  f1 {ms['f1']}  "
          f"p {ms['precision']}  r {ms['recall']}")
    out = {"detector_gold": m, "teacher_same_pages": ms,
           "thresholds": {"conf_t": conf_t, "area_frac": area}}
    (common.RESULTS_DIR / "detector_gold_eval.json").write_text(
        json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
