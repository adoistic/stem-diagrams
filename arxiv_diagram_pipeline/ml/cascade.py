#!/usr/bin/env python3
"""Approach G: abstention-band cascade calibration.

Takes a trained model's saved VALIDATION probabilities, picks accept/reject
thresholds on P(diagram) to hit a target precision at maximum coverage, and
reports the coverage-accuracy trade-off. Items inside the band would be
deferred (to a local VLM or the cloud LLM) in production.
"""

import argparse
import json
import logging

import numpy as np

import common

log = logging.getLogger("cascade")


def load_val(name):
    npz = np.load(common.PREDS_DIR / f"{name}_val.npz")
    rows = {r["image_id"]: r for r in common.load_crops_manifest()}
    ids = [int(i) for i in npz["ids"]]
    y = np.array([rows[i]["cls"] == "diagram" for i in ids])
    p_diag = npz["prob4"][:, 0]
    return y.astype(int), p_diag


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="prediction set name")
    parser.add_argument("--target-precision", type=float, default=0.95)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    y, p = load_val(args.name)

    # sweep symmetric-ish threshold pairs
    grid = np.round(np.arange(0.05, 1.0, 0.05), 2)
    table = []
    for lo in grid:
        for hi in grid[grid >= lo]:
            accept = p >= hi
            reject = p <= lo
            decided = accept | reject
            if decided.sum() < len(y) * 0.3:
                continue
            correct = (accept & (y == 1)) | (reject & (y == 0))
            acc = correct[decided].mean() if decided.any() else 0
            prec = (y[accept] == 1).mean() if accept.any() else 0
            table.append({"lo": float(lo), "hi": float(hi),
                          "coverage": round(float(decided.mean()), 4),
                          "decided_acc": round(float(acc), 4),
                          "accept_precision": round(float(prec), 4)})

    ok = [t for t in table if t["accept_precision"] >= args.target_precision]
    best = max(ok, key=lambda t: t["coverage"]) if ok else \
        max(table, key=lambda t: t["accept_precision"])
    log.info("best band for precision>=%.2f: lo=%.2f hi=%.2f -> coverage %.1f%%, "
             "decided-acc %.4f, accept-precision %.4f",
             args.target_precision, best["lo"], best["hi"],
             best["coverage"] * 100, best["decided_acc"], best["accept_precision"])

    # a few representative rows for the paper
    table.sort(key=lambda t: -t["coverage"])
    payload = {"name": args.name, "target_precision": args.target_precision,
               "best": best, "table_top": table[:200]}
    out = common.RESULTS_DIR / f"cascade_{args.name}.json"
    out.write_text(json.dumps(payload, indent=2))
    common.record_result(f"cascade_{args.name}", "cascade",
                         {"target_precision": args.target_precision},
                         {"acc": best["decided_acc"],
                          "precision": best["accept_precision"],
                          "coverage": best["coverage"],
                          "f1": None, "recall": None},
                         notes=f"lo={best['lo']} hi={best['hi']} "
                               f"coverage={best['coverage']:.0%}")


if __name__ == "__main__":
    main()
