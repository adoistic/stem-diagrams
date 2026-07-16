#!/usr/bin/env python3
"""Approach C: frozen-backbone embeddings + shallow heads.

For each cached backbone: logistic regression and small MLP on the 4-class
silver labels. Reports VALIDATION metrics only; test predictions are saved
for evaluate.py. Run after extract_embeddings.py has populated ml/cache/.
"""

import argparse
import logging
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

import common

log = logging.getLogger("probes")


def run_backbone(backbone):
    rows = common.load_crops_manifest()
    ids, emb = common.load_embeddings(backbone)
    kept, X, y4, is_diag, split = common.align(rows, ids, emb)
    tr, va, te = split == "train", split == "val", split == "test"
    log.info("%s: %d crops aligned (train %d / val %d / test %d), dim %d",
             backbone, len(kept), tr.sum(), va.sum(), te.sum(), X.shape[1])

    heads = {
        "logreg": LogisticRegression(max_iter=3000, C=1.0,
                                     class_weight="balanced"),
        "mlp": MLPClassifier(hidden_layer_sizes=(256,), max_iter=600,
                             early_stopping=True, random_state=0),
    }
    for head_name, clf in heads.items():
        name = f"probe_{backbone}_{head_name}"
        t0 = time.time()
        clf.fit(X[tr], y4[tr])
        fit_s = time.time() - t0

        pred4_val = clf.predict(X[va])
        m = common.binary_metrics(is_diag[va], (pred4_val == 0).astype(int))
        m["acc4"] = round(float((pred4_val == y4[va]).mean()), 4)
        m["fit_seconds"] = round(fit_s, 1)

        prob4_val = clf.predict_proba(X[va])
        common.save_predictions(name, "val",
                                [r["image_id"] for r, k in zip(kept, va) if k],
                                pred4_val, prob4_val)
        pred4_test = clf.predict(X[te])
        prob4_test = clf.predict_proba(X[te])
        common.save_predictions(name, "test",
                                [r["image_id"] for r, k in zip(kept, te) if k],
                                pred4_test, prob4_test)

        common.record_result(name, "probe",
                             {"backbone": backbone, "head": head_name},
                             m, notes=f"4cls-val-acc {m['acc4']}")
        log.info("%s: val binary acc %.4f f1 %.4f (4cls %.4f) fit %.0fs",
                 name, m["acc"], m["f1"], m["acc4"], fit_s)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backbones", nargs="+",
                        default=["siglip2", "dinov2", "mobileclip"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    for b in args.backbones:
        try:
            run_backbone(b)
        except FileNotFoundError:
            log.warning("no embedding cache for %s — run extract_embeddings.py", b)


if __name__ == "__main__":
    main()
