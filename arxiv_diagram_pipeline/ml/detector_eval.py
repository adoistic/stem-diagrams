#!/usr/bin/env python3
"""Approach E: DocLayout-YOLO as the page gate (and figure cropper).

Runs the pretrained DocStructBench model over rendered pages; a page passes
the gate when it has >= 1 'figure' box above confidence/area thresholds
(swept on validation). Also saves per-page boxes so crops can be extracted
and compared against Mistral's. Requires render_pages.py output.
"""

import argparse
import csv
import json
import logging
import random
import time
from pathlib import Path

import numpy as np

import common

log = logging.getLogger("detector")

PAGES_DIR = Path("/Volumes/One Touch/stem_diagrams_data/ml_pages")
WEIGHTS_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
WEIGHTS_FILE = "doclayout_yolo_docstructbench_imgsz1024.pt"


def page_image(row):
    return PAGES_DIR / f"{row['arxiv_id'].replace('/', '_')}_p{row['page_no']:03d}.jpg"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", nargs="+", default=["val", "test"])
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--val-cap", type=int, default=500,
                        help="subsample val pages for threshold sweep (0=all)")
    parser.add_argument("--gold-test-only", action="store_true",
                        help="from test split, keep only the 120 gold pages "
                             "(headline uses gold; no need to run all of test)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    from huggingface_hub import hf_hub_download
    from doclayout_yolo import YOLOv10
    weights = hf_hub_download(WEIGHTS_REPO, WEIGHTS_FILE)
    model = YOLOv10(weights)

    all_rows = [r for r in common.load_pages_manifest() if r["split"] in args.splits]

    gold_keys = set()
    if args.gold_test_only:
        with open(common.DATA_DIR / "gold_pages.csv") as f:
            gold_keys = {(r["arxiv_id"], int(r["page_no"]))
                         for r in csv.DictReader(f)}

    rng = random.Random(20260716)
    val_rows = [r for r in all_rows if r["split"] == "val"]
    if args.val_cap and len(val_rows) > args.val_cap:
        rng.shuffle(val_rows)
        val_rows = val_rows[:args.val_cap]
    test_rows = [r for r in all_rows if r["split"] == "test"]
    if args.gold_test_only:
        test_rows = [r for r in test_rows
                     if (r["arxiv_id"], r["page_no"]) in gold_keys]

    rows = val_rows + test_rows
    if args.limit:
        rows = rows[:args.limit]
    rows = [r for r in rows if page_image(r).exists()]
    log.info("detector over %d pages (val %d + test %d)",
             len(rows), len(val_rows), len(test_rows))

    out = {}
    t0 = time.time()
    BATCH = 16
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        results = model.predict([str(page_image(r)) for r in chunk],
                                imgsz=args.imgsz, conf=0.05,
                                device=args.device, verbose=False)
        for r, res in zip(chunk, results):
            names = res.names
            boxes = []
            for b in res.boxes:
                cls_name = names[int(b.cls)]
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                boxes.append({"cls": cls_name, "conf": float(b.conf),
                              "xyxy": [x1, y1, x2, y2]})
            key = f"{r['arxiv_id']}|{r['page_no']}"
            out[key] = {"split": r["split"], "has_diagram": r["has_diagram"],
                        "field": r["field"], "boxes": boxes,
                        "img_wh": [res.orig_shape[1], res.orig_shape[0]]}
        if (i // BATCH) % 20 == 0:
            done = i + len(chunk)
            rate = done / max(time.time() - t0, 1e-9)
            log.info("%d/%d pages (%.1f pages/s)", done, len(rows), rate)

    boxes_path = common.RESULTS_DIR / "detector_boxes.json"
    common.RESULTS_DIR.mkdir(exist_ok=True)
    boxes_path.write_text(json.dumps(out))
    elapsed = time.time() - t0
    log.info("inference done: %.1f pages/s", len(rows) / elapsed)

    # sweep gate thresholds on validation
    def gate(entry, conf_t, area_frac):
        W, H = entry["img_wh"]
        for b in entry["boxes"]:
            if b["cls"] == "figure" and b["conf"] >= conf_t:
                x1, y1, x2, y2 = b["xyxy"]
                if (x2 - x1) * (y2 - y1) >= area_frac * W * H:
                    return 1
        return 0

    val = [e for e in out.values() if e["split"] == "val"]
    y = np.array([e["has_diagram"] for e in val])
    best = None
    for conf_t in (0.2, 0.3, 0.4, 0.5, 0.6):
        for area in (0.01, 0.03, 0.05):
            p = np.array([gate(e, conf_t, area) for e in val])
            m = common.binary_metrics(y, p)
            if best is None or m["f1"] > best[0]["f1"]:
                best = (m, conf_t, area)
    m, conf_t, area = best
    m["pages_per_sec"] = round(len(rows) / elapsed, 1)
    common.record_result("detector_doclayout_yolo", "detector",
                         {"weights": WEIGHTS_FILE, "imgsz": args.imgsz,
                          "conf_t": conf_t, "area_frac": area,
                          "device": args.device},
                         m, notes=f"page gate vs silver; best conf={conf_t} "
                                  f"area={area}; {m['pages_per_sec']} pages/s")
    log.info("VAL page gate: acc %.4f f1 %.4f (conf %.1f area %.2f)",
             m["acc"], m["f1"], conf_t, area)


if __name__ == "__main__":
    main()
