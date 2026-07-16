#!/usr/bin/env python3
"""Final evaluation — the ONLY script that reads test-split outcomes.

Modes:
  --silver   evaluate saved test predictions against silver labels
  --gold     evaluate against ml/data/gold_crops.csv (image_id,gold_cls,...)
  --compare A B   McNemar's test between two prediction sets (binary, test)

Reports accuracy/F1/precision/recall with bootstrap 95% CIs, per-field
slices, and the 4-class confusion matrix.
"""

import argparse
import csv
import json

import numpy as np

import common


def load_preds(name, split="test"):
    npz = np.load(common.PREDS_DIR / f"{name}_{split}.npz")
    return {int(i): (int(p), probs) for i, p, probs
            in zip(npz["ids"], npz["pred4"], npz["prob4"])}


def bootstrap_ci(y, p, metric_fn, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    vals = []
    idx = np.arange(len(y))
    for _ in range(n):
        s = rng.choice(idx, len(idx), replace=True)
        vals.append(metric_fn(y[s], p[s]))
    return round(float(np.percentile(vals, 2.5)), 4), \
        round(float(np.percentile(vals, 97.5)), 4)


def evaluate(name, labels_by_id, fields_by_id, label_kind):
    preds = load_preds(name)
    ids = [i for i in preds if i in labels_by_id]
    y4 = np.array([labels_by_id[i] for i in ids])
    p4 = np.array([preds[i][0] for i in ids])
    yb, pb = (y4 == 0).astype(int), (p4 == 0).astype(int)

    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
    m = common.binary_metrics(yb, pb)
    m["acc_ci"] = bootstrap_ci(yb, pb, accuracy_score)
    m["f1_ci"] = bootstrap_ci(yb, pb, lambda a, b: f1_score(a, b, zero_division=0))
    m["acc4"] = round(float((p4 == y4).mean()), 4)
    m["n"] = len(ids)

    print(f"\n=== {name} vs {label_kind} (test, n={len(ids)}) ===")
    print(f"binary acc {m['acc']} CI{m['acc_ci']}  f1 {m['f1']} CI{m['f1_ci']}")
    print(f"precision {m['precision']}  recall {m['recall']}  4cls acc {m['acc4']}")
    print("confusion (rows=true, cols=pred, order "
          + ",".join(common.CLASSES) + "):")
    print(confusion_matrix(y4, p4, labels=range(4)))
    fields = sorted(set(fields_by_id.get(i, "?") for i in ids))
    for f in fields:
        sel = np.array([fields_by_id.get(i) == f for i in ids])
        if sel.sum() >= 10:
            print(f"  {f:28s} acc {accuracy_score(yb[sel], pb[sel]):.4f} "
                  f"(n={int(sel.sum())})")
    return m, dict(zip(ids, pb)), dict(zip(ids, yb))


def mcnemar(name_a, name_b, labels_by_id):
    pa, pb_ = load_preds(name_a), load_preds(name_b)
    ids = [i for i in labels_by_id if i in pa and i in pb_]
    y = np.array([labels_by_id[i] == 0 for i in ids])
    a = np.array([pa[i][0] == 0 for i in ids]) == y
    b = np.array([pb_[i][0] == 0 for i in ids]) == y
    n01 = int((~a & b).sum())
    n10 = int((a & ~b).sum())
    stat = (abs(n10 - n01) - 1) ** 2 / max(n10 + n01, 1)
    from scipy.stats import chi2
    p = 1 - chi2.cdf(stat, 1) if (n10 + n01) > 0 else 1.0
    print(f"McNemar {name_a} vs {name_b}: n10={n10} n01={n01} "
          f"chi2={stat:.2f} p={p:.4f}"
          + ("  (significant at 0.05)" if p < 0.05 else "  (tie)"))


def silver_labels():
    rows = common.load_crops_manifest()
    labels = {r["image_id"]: common.CLS_TO_IDX[r["cls"]]
              for r in rows if r["split"] == "test"}
    fields = {r["image_id"]: r["field"] for r in rows}
    return labels, fields


def gold_labels():
    labels, fields = {}, {}
    crop_fields = {r["image_id"]: r["field"] for r in common.load_crops_manifest()}
    with open(common.DATA_DIR / "gold_crops.csv") as f:
        for r in csv.DictReader(f):
            iid = int(r["image_id"])
            labels[iid] = common.CLS_TO_IDX[r["gold_cls"]]
            fields[iid] = crop_fields.get(iid, "?")
    return labels, fields


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*", help="prediction sets to evaluate")
    parser.add_argument("--silver", action="store_true")
    parser.add_argument("--gold", action="store_true")
    parser.add_argument("--compare", nargs=2)
    args = parser.parse_args()

    out = {}
    if args.silver:
        labels, fields = silver_labels()
        for n in args.names:
            out[f"{n}_silver"] = evaluate(n, labels, fields, "silver")[0]
    if args.gold:
        labels, fields = gold_labels()
        for n in args.names:
            out[f"{n}_gold"] = evaluate(n, labels, fields, "gold")[0]
    if args.compare:
        labels, _ = gold_labels() if args.gold else silver_labels()
        mcnemar(args.compare[0], args.compare[1], labels)
    if out:
        path = common.RESULTS_DIR / "test_evaluation.json"
        existing = json.loads(path.read_text()) if path.exists() else {}
        existing.update({k: v for k, v in out.items()})
        path.write_text(json.dumps(existing, indent=2, default=str))


if __name__ == "__main__":
    main()
