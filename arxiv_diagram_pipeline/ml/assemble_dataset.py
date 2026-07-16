#!/usr/bin/env python3
"""Assemble the classifier datasets from the v2 pipeline's state.db.

Outputs (all deterministic given SEED):
  ml/data/splits.json         paper -> train/val/test (paper-level, stratified
                              by field; one assignment shared by BOTH tasks)
  ml/data/crops_manifest.csv  crop-level rows: path, silver 4-class, field, split
  ml/data/pages_manifest.csv  page-level rows: pdf path, page_no, has_diagram, split

Silver classes follow ml/RUBRIC.md v1.0:
  diagram       accepted (labeled) images
  data_plot     llm rejects mentioning plots/heatmaps/phase maps
  photo         llm rejects mentioning photographs/micrographs
  fragment_junk local filter rejects + fragments/blurry/blank + unknown

Trivial local rejects (tiny-file/dims) are capped so they don't dominate.
"""

import csv
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ML_DIR.parent))
import config  # noqa: E402

SEED = 20260716
SPLIT_FRACS = {"train": 0.70, "val": 0.15, "test": 0.15}
TRIVIAL_NEG_CAP = 600
RUBRIC_VERSION = "1.0"

DATA_DIR = ML_DIR / "data"


def classify_reason(reason):
    r = reason.lower()
    if r.startswith("local:"):
        return "fragment_junk", "local"
    body = r[4:] if r.startswith("llm:") else r
    if "plot" in body or "heatmap" in body or "chart" in body or "graph of" in body \
            or "phase map" in body or "spectrogram" in body or "histogram" in body:
        return "data_plot", "llm"
    if "photo" in body or "micrograph" in body:
        return "photo", "llm"
    return "fragment_junk", "llm"


def main():
    rng = random.Random(SEED)
    conn = sqlite3.connect(f"file:{config.STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ---- crop rows with silver classes ----
    crops = []
    unknown_reasons = Counter()
    trivial = []
    for r in conn.execute(
            "SELECT i.image_id, i.file_path, i.status, i.reject_reason, "
            "p.field, p.arxiv_id FROM images i "
            "JOIN papers p ON p.arxiv_id = i.arxiv_id "
            "WHERE i.status IN ('labeled','rejected')"):
        path = Path(r["file_path"])
        if not path.exists():
            continue
        if r["status"] == "labeled":
            cls, src = "diagram", "accepted"
        else:
            cls, src = classify_reason(r["reject_reason"])
            if src == "llm" and cls == "fragment_junk":
                unknown_reasons[r["reject_reason"][:40]] += 1
        row = {"image_id": r["image_id"], "path": str(path), "cls": cls,
               "field": r["field"], "arxiv_id": r["arxiv_id"], "source": src}
        if src == "local":
            trivial.append(row)
        else:
            crops.append(row)

    rng.shuffle(trivial)
    crops.extend(trivial[:TRIVIAL_NEG_CAP])

    # ---- page rows ----
    pages = []
    for r in conn.execute(
            "SELECT g.arxiv_id, g.page_no, g.has_diagram, p.field FROM pages g "
            "JOIN papers p ON p.arxiv_id = g.arxiv_id WHERE g.status='done'"):
        pdf = config.PAPERS_V2_DIR / r["field"] / (r["arxiv_id"].replace("/", "_") + ".pdf")
        if not pdf.exists():
            continue
        pages.append({"arxiv_id": r["arxiv_id"], "page_no": r["page_no"],
                      "has_diagram": r["has_diagram"], "field": r["field"],
                      "pdf_path": str(pdf)})

    # ---- ONE paper-level split shared by both tasks ----
    paper_fields = {}
    for row in crops:
        paper_fields[row["arxiv_id"]] = row["field"]
    for row in pages:
        paper_fields.setdefault(row["arxiv_id"], row["field"])

    by_field = defaultdict(list)
    for pid, field in paper_fields.items():
        by_field[field].append(pid)

    split_of = {}
    for field, pids in sorted(by_field.items()):
        pids.sort()
        rng.shuffle(pids)
        n = len(pids)
        n_train = round(n * SPLIT_FRACS["train"])
        n_val = round(n * SPLIT_FRACS["val"])
        for i, pid in enumerate(pids):
            split_of[pid] = ("train" if i < n_train
                             else "val" if i < n_train + n_val else "test")

    # integrity: every paper exactly one split
    assert len(split_of) == len(paper_fields)

    # ---- write outputs ----
    DATA_DIR.mkdir(exist_ok=True)
    splits_payload = {"seed": SEED, "rubric_version": RUBRIC_VERSION,
                      "fracs": SPLIT_FRACS, "papers": split_of}
    splits_json = json.dumps(splits_payload, indent=0, sort_keys=True)
    (DATA_DIR / "splits.json").write_text(splits_json)
    manifest_sha = hashlib.sha256(splits_json.encode()).hexdigest()[:16]

    with open(DATA_DIR / "crops_manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["image_id", "path", "cls", "field",
                                          "arxiv_id", "source", "split"])
        w.writeheader()
        for row in sorted(crops, key=lambda x: x["image_id"]):
            row["split"] = split_of[row["arxiv_id"]]
            w.writerow(row)

    with open(DATA_DIR / "pages_manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["arxiv_id", "page_no", "has_diagram",
                                          "field", "pdf_path", "split"])
        w.writeheader()
        for row in sorted(pages, key=lambda x: (x["arxiv_id"], x["page_no"])):
            row["split"] = split_of[row["arxiv_id"]]
            w.writerow(row)

    # ---- report ----
    print(f"splits.json sha256[:16] = {manifest_sha}  (seed {SEED}, rubric v{RUBRIC_VERSION})")
    print(f"papers: {len(split_of)}  "
          + "  ".join(f"{s}={list(split_of.values()).count(s)}" for s in ("train", "val", "test")))
    cls_split = Counter((r['cls'], split_of[r['arxiv_id']]) for r in crops)
    print("crops by class x split:")
    for cls in ("diagram", "data_plot", "photo", "fragment_junk"):
        line = "  ".join(f"{s}={cls_split.get((cls, s), 0)}" for s in ("train", "val", "test"))
        print(f"  {cls:14s} {line}")
    pg_split = Counter((r['has_diagram'], split_of[r['arxiv_id']]) for r in pages)
    print("pages (diag/total): " + "  ".join(
        f"{s}={pg_split.get((1, s), 0)}/{pg_split.get((0, s), 0) + pg_split.get((1, s), 0)}"
        for s in ("train", "val", "test")))
    if unknown_reasons:
        print("note: unmapped llm reject reasons -> fragment_junk:")
        for reason, n in unknown_reasons.most_common(8):
            print(f"  {n}x {reason}")


if __name__ == "__main__":
    main()
