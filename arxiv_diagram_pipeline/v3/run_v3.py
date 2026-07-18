#!/usr/bin/env python3
"""v3 harvester: deterministic figure extraction + local diagram gate, no Mistral.

Downloads arXiv PDFs, extracts figure candidates geometrically (PyMuPDF), keeps
the ones the local SigLIP2+logreg gate calls a proper diagram, and streams
everything to R2 in zip batches. The laptop only ever holds the current working
set: PDFs and crops are deleted after their batch uploads. Resumable; stops at
--target accepted diagrams.

Mistral is intentionally unused (that was the whole point). If deterministic
yield ever proves insufficient it can be added as a capped fallback.
"""

import argparse
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract
import gate
import r2

log = logging.getLogger("v3")

FIELDS = {
    "semiconductor_engineering": "(cat:cond-mat.mes-hall OR cat:physics.app-ph OR cat:eess.SP) AND (abs:semiconductor OR abs:transistor OR abs:\"integrated circuit\" OR abs:\"chip design\" OR abs:lithography)",
    "manufacturing_engineering": "(cat:eess.SY OR cat:physics.app-ph OR cat:cs.CE) AND (abs:manufacturing OR abs:\"additive manufacturing\" OR abs:machining OR abs:\"production line\" OR abs:\"process control\")",
    "robotics_automation": "cat:cs.RO",
    "utilities_power_systems": "cat:eess.SY AND (abs:\"power system\" OR abs:\"power grid\" OR abs:\"smart grid\" OR abs:microgrid OR abs:\"distribution network\" OR abs:\"transmission line\")",
    "aerospace_engineering": "(cat:eess.SY OR cat:cs.RO OR cat:physics.flu-dyn) AND (abs:aerospace OR abs:aircraft OR abs:spacecraft OR abs:UAV OR abs:satellite OR abs:aerodynamics)",
    "telecommunications": "(cat:eess.SP OR cat:cs.NI OR cat:cs.IT) AND (abs:wireless OR abs:\"communication system\" OR abs:5G OR abs:6G OR abs:antenna OR abs:\"optical fiber\")",
}
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
API = "http://export.arxiv.org/api/query"

WORK = Path(__file__).resolve().parent / "work"
DB = Path(__file__).resolve().parent / "v3_state.db"
IMG_BATCH = int(os.getenv("IMG_BATCH", "500"))
PDF_BATCH = int(os.getenv("PDF_BATCH", "120"))
DL_DELAY = float(os.getenv("DL_DELAY", "2.0"))
HARVEST_BUFFER = int(os.getenv("HARVEST_BUFFER", "1500"))

_dl_lock = threading.Lock()
_last_dl = [0.0]


def throttle(delay):
    with _dl_lock:
        wait = delay - (time.monotonic() - _last_dl[0])
        if wait > 0:
            time.sleep(wait)
        _last_dl[0] = time.monotonic()


# ---------------- state ----------------

def db_conn():
    c = sqlite3.connect(DB, isolation_level=None, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS papers(
      arxiv_id TEXT PRIMARY KEY, base_id TEXT, field TEXT, pdf_url TEXT,
      status TEXT DEFAULT 'pending', pdf_batch TEXT DEFAULT '', n_diagrams INTEGER DEFAULT 0);
    CREATE UNIQUE INDEX IF NOT EXISTS ix_base ON papers(base_id);
    CREATE INDEX IF NOT EXISTS ix_status ON papers(status);
    CREATE TABLE IF NOT EXISTS images(
      name TEXT PRIMARY KEY, arxiv_id TEXT, field TEXT, page INTEGER,
      method TEXT, bbox TEXT, p_diagram REAL,
      status TEXT DEFAULT 'staged', r2_batch TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS ix_img_status ON images(status);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    return c


def meta_get(c, k, d="0"):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else d


def meta_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))


def accepted_count(c):
    return c.execute("SELECT COUNT(*) FROM images WHERE status IN ('staged','uploaded')").fetchone()[0]


# ---------------- arxiv ----------------

def parse_entries(xml):
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("atom:entry", ATOM):
        aid = (e.findtext("atom:id", "", ATOM) or "").split("/abs/")[-1].strip()
        pdf = ""
        for ln in e.findall("atom:link", ATOM):
            if ln.get("title") == "pdf":
                pdf = ln.get("href", "")
        out.append((aid, pdf or f"https://arxiv.org/pdf/{aid}"))
    return out


def harvest_loop(stop, target):
    c = db_conn()
    while not stop.is_set():
        pend = c.execute("SELECT COUNT(*) FROM papers WHERE status='pending'").fetchone()[0]
        done = accepted_count(c)
        if done >= target:
            return
        if pend >= HARVEST_BUFFER:
            stop.wait(30)
            continue
        added = 0
        for field, query in FIELDS.items():
            if stop.is_set():
                return
            off = int(meta_get(c, f"off_{field}"))
            throttle(DL_DELAY)
            try:
                resp = requests.get(API, params={
                    "search_query": query, "start": off, "max_results": 100,
                    "sortBy": "submittedDate", "sortOrder": "descending"}, timeout=60)
                if resp.status_code == 429:
                    log.warning("[harvest] 429; backing off 120s")
                    stop.wait(120)
                    continue
                entries = parse_entries(resp.text)
            except Exception as exc:
                log.warning("[harvest] %s failed: %s", field, exc)
                continue
            for aid, pdf in entries:
                base = aid.rsplit("v", 1)[0]
                cur = c.execute("INSERT OR IGNORE INTO papers(arxiv_id,base_id,field,pdf_url) VALUES(?,?,?,?)",
                                (aid, base, field, pdf))
                added += cur.rowcount
            meta_set(c, f"off_{field}", off + len(entries))
        log.info("[harvest] +%d papers (pending now %d)", added,
                 c.execute("SELECT COUNT(*) FROM papers WHERE status='pending'").fetchone()[0])
        if added == 0:
            stop.wait(300)


def download_pdf(url, dest, arxiv_id):
    for cand in (url, f"https://arxiv.org/pdf/{arxiv_id}",
                 f"https://arxiv.org/pdf/{re.sub(r'v[0-9]+$','',arxiv_id)}"):
        throttle(DL_DELAY)
        try:
            r = requests.get(cand, timeout=120)
            if r.status_code == 429:
                time.sleep(60)
                continue
            if r.content[:4] == b"%PDF":
                dest.write_bytes(r.content)
                return True
        except Exception:
            continue
    return False


# ---------------- batch commit ----------------

def commit_images(c):
    stage = WORK / "img_stage"
    pngs = sorted(stage.glob("*.png"))
    if not pngs:
        return
    seq = int(meta_get(c, "img_seq")) + 1
    key = f"v3/images/batch_{seq:05d}.zip"
    zpath = WORK / f"img_batch_{seq:05d}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in pngs:
            z.write(p, p.name)
    ok, msg = r2.put(zpath, key, "application/zip")
    if not ok:
        log.error("[r2] image batch upload failed: %s", msg)
        zpath.unlink(missing_ok=True)
        return
    names = [p.name for p in pngs]
    c.executemany("UPDATE images SET status='uploaded', r2_batch=? WHERE name=?",
                  [(key, n) for n in names])
    meta_set(c, "img_seq", seq)
    for p in pngs:
        p.unlink(missing_ok=True)
    zpath.unlink(missing_ok=True)
    log.info("[r2] uploaded %s (%d images)", key, len(names))


def commit_pdfs(c, force=False):
    stage = WORK / "pdf_stage"
    pdfs = sorted(stage.glob("*.pdf"))
    if not pdfs or (len(pdfs) < PDF_BATCH and not force):
        return
    seq = int(meta_get(c, "pdf_seq")) + 1
    key = f"v3/pdfs/batch_{seq:05d}.zip"
    zpath = WORK / f"pdf_batch_{seq:05d}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for p in pdfs:
            z.write(p, p.name)
    ok, msg = r2.put(zpath, key, "application/zip")
    if not ok:
        log.error("[r2] pdf batch upload failed: %s", msg)
        zpath.unlink(missing_ok=True)
        return
    ids = [p.stem for p in pdfs]
    c.executemany("UPDATE papers SET pdf_batch=? WHERE arxiv_id=?", [(key, i) for i in ids])
    meta_set(c, "pdf_seq", seq)
    for p in pdfs:
        p.unlink(missing_ok=True)
    zpath.unlink(missing_ok=True)
    log.info("[r2] uploaded %s (%d pdfs)", key, len(ids))


def upload_manifest(c):
    import csv
    mpath = WORK / "manifest.csv"
    rows = c.execute("SELECT name,arxiv_id,field,page,method,bbox,p_diagram,r2_batch "
                     "FROM images WHERE status='uploaded' ORDER BY name").fetchall()
    with open(mpath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image", "arxiv_id", "field", "page", "method", "bbox", "p_diagram", "image_batch"])
        w.writerows(rows)
    r2.put(mpath, "v3/manifest.csv", "text/csv")
    log.info("[r2] manifest updated (%d images)", len(rows))


# ---------------- main ----------------

def process_paper(c, paper, gate_threshold):
    aid, field, pdf_url = paper["arxiv_id"], paper["field"], paper["pdf_url"]
    safe = aid.replace("/", "_")
    pdf_path = WORK / f"{safe}.pdf"
    if not download_pdf(pdf_url, pdf_path, aid):
        c.execute("UPDATE papers SET status='failed' WHERE arxiv_id=?", (aid,))
        return 0
    # extract candidates
    try:
        cands = list(extract.extract_pdf(pdf_path, max_pages=40))
    except Exception as exc:
        log.warning("[extract] %s failed: %s", aid, exc)
        cands = []
    n_acc = 0
    if cands:
        imgs = [cd["image"] for _pno, cd in cands]
        verdicts = gate.classify(imgs)
        (WORK / "img_stage").mkdir(exist_ok=True)
        for (pno, cd), (cls, p) in zip(cands, verdicts):
            if cls == "diagram" and p >= gate_threshold:
                n_acc += 1
                name = f"{safe}_p{pno:03d}_{cd['method']}_{n_acc:02d}.png"
                cd["image"].save(WORK / "img_stage" / name)
                c.execute("INSERT OR IGNORE INTO images(name,arxiv_id,field,page,method,bbox,p_diagram) "
                          "VALUES(?,?,?,?,?,?,?)",
                          (name, aid, field, pno, cd["method"], json.dumps(cd["bbox"]), p))
    # stage the pdf for archival, mark paper done
    (WORK / "pdf_stage").mkdir(exist_ok=True)
    shutil.move(str(pdf_path), WORK / "pdf_stage" / f"{safe}.pdf")
    c.execute("UPDATE papers SET status='done', n_diagrams=? WHERE arxiv_id=?", (n_acc, aid))
    return n_acc


def run(args):
    WORK.mkdir(exist_ok=True)
    (WORK / "img_stage").mkdir(exist_ok=True)
    (WORK / "pdf_stage").mkdir(exist_ok=True)
    c = db_conn()
    # recover: reset papers left 'processing'
    c.execute("UPDATE papers SET status='pending' WHERE status='processing'")

    stop = threading.Event()
    ht = threading.Thread(target=harvest_loop, args=(stop, args.target), daemon=True)
    ht.start()

    log.info("gate warmup...")
    gate.classify([__import__("PIL.Image", fromlist=["new"]).new("RGB", (224, 224))])
    last_manifest = 0.0
    last_status = 0.0
    try:
        while True:
            done = accepted_count(c)
            if done >= args.target:
                log.info("TARGET REACHED: %d accepted diagrams", done)
                break
            row = c.execute("SELECT arxiv_id,field,pdf_url FROM papers WHERE status='pending' LIMIT 1").fetchone()
            if not row:
                exhausted = c.execute("SELECT COUNT(*) FROM papers WHERE status='pending'").fetchone()[0] == 0
                if exhausted and getattr(run, "_harvest_dry", False):
                    log.warning("no pending papers and harvest dry — stopping at %d", done)
                    break
                time.sleep(3)
                continue
            paper = {"arxiv_id": row[0], "field": row[1], "pdf_url": row[2]}
            c.execute("UPDATE papers SET status='processing' WHERE arxiv_id=?", (paper["arxiv_id"],))
            try:
                process_paper(c, paper, args.gate_threshold)
            except Exception as exc:
                log.warning("[process] %s failed: %s", paper["arxiv_id"], exc)
                c.execute("UPDATE papers SET status='failed' WHERE arxiv_id=?", (paper["arxiv_id"],))

            # commit batches when full
            if len(list((WORK / "img_stage").glob("*.png"))) >= IMG_BATCH:
                commit_images(c)
            commit_pdfs(c)

            now = time.monotonic()
            if now - last_status > 30:
                last_status = now
                cnt = c.execute("SELECT COUNT(*) FROM papers WHERE status='done'").fetchone()[0]
                pend = c.execute("SELECT COUNT(*) FROM papers WHERE status='pending'").fetchone()[0]
                log.info("STATUS accepted %d/%d | papers done %d | pending %d | img_stage %d | pdf_stage %d",
                         accepted_count(c), args.target, cnt, pend,
                         len(list((WORK / 'img_stage').glob('*.png'))),
                         len(list((WORK / 'pdf_stage').glob('*.pdf'))))
            if now - last_manifest > 300:
                last_manifest = now
                commit_images(c)
                commit_pdfs(c, force=True)
                upload_manifest(c)
    except KeyboardInterrupt:
        log.warning("interrupted — committing staged work")
    finally:
        stop.set()
        commit_images(c)
        commit_pdfs(c, force=True)
        upload_manifest(c)
    log.info("FINAL: %d accepted diagrams, %d papers done",
             accepted_count(c),
             c.execute("SELECT COUNT(*) FROM papers WHERE status='done'").fetchone()[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=10000)
    ap.add_argument("--gate-threshold", type=float, default=0.5)
    args = ap.parse_args()
    (Path(__file__).resolve().parent / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(Path(__file__).resolve().parent / "logs" / "v3.log")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    code = run(args)
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
