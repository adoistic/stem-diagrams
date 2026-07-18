#!/usr/bin/env python3
"""v3 harvester (shareable, per-category): deterministic extraction + local gate.

Downloads arXiv PDFs, extracts figure candidates geometrically (PyMuPDF), keeps
the ones the local SigLIP2+logreg gate calls a proper diagram, and streams each
one individually to R2 under v3/img/<category>/ so a single gallery link lets
anyone browse and download the diagrams for their field. Source PDFs go to R2 as
size-capped per-category zips. The laptop only holds the current working set.
No Mistral, no paid API. Resumable; stops at --target accepted diagrams.
"""

import argparse
import json
import logging
import os
import queue
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
import gallery
import gate
import r2

log = logging.getLogger("v3")

FIELDS = {
    "semiconductor_engineering": "(cat:cond-mat.mes-hall OR cat:physics.app-ph OR cat:eess.SP) AND (abs:semiconductor OR abs:transistor OR abs:\"integrated circuit\" OR abs:\"chip design\" OR abs:lithography)",
    "manufacturing_engineering": "(cat:eess.SY OR cat:physics.app-ph OR cat:cs.CE) AND (abs:manufacturing OR abs:\"additive manufacturing\" OR abs:machining OR abs:\"production line\" OR abs:\"process control\")",
    "robotics_automation": "cat:cs.RO",
    "utilities_power_systems": "cat:eess.SY AND (abs:\"power system\" OR abs:\"power grid\" OR abs:\"smart grid\" OR abs:microgrid OR abs:\"distribution network\" OR abs:\"transmission line\")",
    "telecommunications": "(cat:eess.SP OR cat:cs.NI OR cat:cs.IT) AND (abs:wireless OR abs:\"communication system\" OR abs:5G OR abs:6G OR abs:antenna OR abs:\"optical fiber\")",
}
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
API = "http://export.arxiv.org/api/query"

WORK = Path(__file__).resolve().parent / "work"
DB = Path(__file__).resolve().parent / "v3_state.db"
DL_DELAY = float(os.getenv("DL_DELAY", "2.0"))
HARVEST_BUFFER = int(os.getenv("HARVEST_BUFFER", "1500"))
N_UPLOADERS = int(os.getenv("N_UPLOADERS", "4"))
PDF_ZIP_CAP = int(os.getenv("PDF_ZIP_MB", "220")) * 1024 * 1024

_dl_lock = threading.Lock()
_last_dl = [0.0]
_upload_q = queue.Queue()


def throttle(delay):
    with _dl_lock:
        wait = delay - (time.monotonic() - _last_dl[0])
        if wait > 0:
            time.sleep(wait)
        _last_dl[0] = time.monotonic()


def db_conn():
    c = sqlite3.connect(DB, isolation_level=None, timeout=60, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS papers(
      arxiv_id TEXT PRIMARY KEY, base_id TEXT, field TEXT, pdf_url TEXT,
      status TEXT DEFAULT 'pending', pdf_zip TEXT DEFAULT '', n_diagrams INTEGER DEFAULT 0);
    CREATE UNIQUE INDEX IF NOT EXISTS ix_base ON papers(base_id);
    CREATE INDEX IF NOT EXISTS ix_status ON papers(status);
    CREATE TABLE IF NOT EXISTS images(
      name TEXT PRIMARY KEY, arxiv_id TEXT, field TEXT, page INTEGER, method TEXT,
      bbox TEXT, p_diagram REAL, status TEXT DEFAULT 'local', caption TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS ix_img_status ON images(status);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    try:
        c.execute("ALTER TABLE images ADD COLUMN caption TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    return c


def meta_get(c, k, d="0"):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else d


def meta_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))


def accepted(c):
    return c.execute("SELECT COUNT(*) FROM images WHERE status IN ('local','uploaded')").fetchone()[0]


# ---- background image uploader (individual objects, per category) ----

def uploader(c, lock, stop):
    while not stop.is_set() or not _upload_q.empty():
        try:
            name, field, path = _upload_q.get(timeout=1)
        except queue.Empty:
            continue
        key = f"v3/img/{field}/{name}"
        ok = False
        for _ in range(3):
            ok, _msg = r2.put(path, key, "image/png")
            if ok:
                break
            time.sleep(3)
        with lock:
            if ok:
                c.execute("UPDATE images SET status='uploaded' WHERE name=?", (name,))
                Path(path).unlink(missing_ok=True)
            else:
                c.execute("UPDATE images SET status='failed' WHERE name=?", (name,))
                log.warning("[upload] gave up on %s", name)
        _upload_q.task_done()


# ---- arxiv ----

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


def harvest_loop(c, lock, stop, target):
    while not stop.is_set():
        with lock:
            pend = c.execute("SELECT COUNT(*) FROM papers WHERE status='pending'").fetchone()[0]
            done = accepted(c)
        if target and done >= target:
            return
        if pend >= HARVEST_BUFFER:
            stop.wait(30)
            continue
        added = 0
        for field, query in FIELDS.items():
            if stop.is_set():
                return
            with lock:
                off = int(meta_get(c, f"off_{field}"))
            throttle(DL_DELAY)
            try:
                resp = requests.get(API, params={
                    "search_query": query, "start": off, "max_results": 100,
                    "sortBy": "submittedDate", "sortOrder": "descending"}, timeout=60)
                if resp.status_code == 429:
                    stop.wait(120)
                    continue
                entries = parse_entries(resp.text)
            except Exception as exc:
                log.warning("[harvest] %s: %s", field, exc)
                continue
            with lock:
                for aid, pdf in entries:
                    base = aid.rsplit("v", 1)[0]
                    added += c.execute(
                        "INSERT OR IGNORE INTO papers(arxiv_id,base_id,field,pdf_url) VALUES(?,?,?,?)",
                        (aid, base, field, pdf)).rowcount
                meta_set(c, f"off_{field}", off + len(entries))
        with lock:
            npend = c.execute("SELECT COUNT(*) FROM papers WHERE status='pending'").fetchone()[0]
        log.info("[harvest] +%d papers (pending %d)", added, npend)
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


# ---- per-category PDF zips (size-capped) ----

def commit_pdf_zip(c, field, force=False):
    d = WORK / "pdf_stage" / field
    pdfs = sorted(d.glob("*.pdf")) if d.exists() else []
    if not pdfs:
        return
    total = sum(p.stat().st_size for p in pdfs)
    if total < PDF_ZIP_CAP and not force:
        return
    seq = int(meta_get(c, f"pdfseq_{field}")) + 1
    key = f"v3/pdfs/{field}/batch_{seq:04d}.zip"
    zpath = WORK / f"pdf_{field}_{seq:04d}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for p in pdfs:
            z.write(p, p.name)
    ok, msg = r2.put(zpath, key, "application/zip")
    zpath.unlink(missing_ok=True)
    if not ok:
        log.error("[r2] pdf zip %s failed: %s", key, msg)
        return
    ids = [p.stem for p in pdfs]
    c.executemany("UPDATE papers SET pdf_zip=? WHERE arxiv_id=?", [(key, i) for i in ids])
    meta_set(c, f"pdfseq_{field}", seq)
    for p in pdfs:
        p.unlink(missing_ok=True)
    log.info("[r2] uploaded %s (%d pdfs, %.0f MB)", key, len(ids), total / 1e6)


# ---- main ----

def process_paper(c, lock, paper, threshold):
    aid, field = paper["arxiv_id"], paper["field"]
    safe = aid.replace("/", "_")
    pdf_path = WORK / f"{safe}.pdf"
    if not download_pdf(paper["pdf_url"], pdf_path, aid):
        with lock:
            c.execute("UPDATE papers SET status='failed' WHERE arxiv_id=?", (aid,))
        return
    try:
        cands = list(extract.extract_pdf(pdf_path, max_pages=40))
    except Exception as exc:
        log.warning("[extract] %s: %s", aid, exc)
        cands = []
    n_acc = 0
    if cands:
        verdicts = gate.classify([cd["image"] for _p, cd in cands])
        stage = WORK / "img_stage" / field
        stage.mkdir(parents=True, exist_ok=True)
        for (pno, cd), (cls, p) in zip(cands, verdicts):
            if cls == "diagram" and p >= threshold:
                n_acc += 1
                name = f"{safe}_p{pno:03d}_{cd['method']}_{n_acc:02d}.png"
                fp = stage / name
                cd["image"].save(fp)
                with lock:
                    c.execute("INSERT OR IGNORE INTO images(name,arxiv_id,field,page,method,bbox,p_diagram,caption) "
                              "VALUES(?,?,?,?,?,?,?,?)",
                              (name, aid, field, pno, cd["method"], json.dumps(cd["bbox"]), p,
                               cd.get("caption", "")))
                _upload_q.put((name, field, str(fp)))
    # archive the pdf per category
    pstage = WORK / "pdf_stage" / field
    pstage.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf_path), pstage / f"{safe}.pdf")
    with lock:
        c.execute("UPDATE papers SET status='done', n_diagrams=? WHERE arxiv_id=?", (n_acc, aid))


def run(args):
    for sub in ("img_stage", "pdf_stage", "gallery"):
        (WORK / sub).mkdir(parents=True, exist_ok=True)
    c = db_conn()
    lock = threading.Lock()
    c.execute("UPDATE papers SET status='pending' WHERE status='processing'")
    # record start (kept across resumes) + target for the live gallery header
    c.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('pipeline_start',?)", (str(time.time()),))
    meta_set(c, "target", args.target)
    # re-enqueue any local images left from a prior run
    for (name, field) in c.execute("SELECT name,field FROM images WHERE status='local'").fetchall():
        fp = WORK / "img_stage" / field / name
        if fp.exists():
            _upload_q.put((name, field, str(fp)))
        else:
            c.execute("UPDATE images SET status='lost' WHERE name=?", (name,))

    stop = threading.Event()
    threads = [threading.Thread(target=harvest_loop, args=(c, lock, stop, args.target), daemon=True)]
    for _ in range(N_UPLOADERS):
        threads.append(threading.Thread(target=uploader, args=(c, lock, stop), daemon=True))
    for t in threads:
        t.start()

    from PIL import Image
    gate.classify([Image.new("RGB", (224, 224))])  # warmup
    last_gallery = last_status = 0.0
    try:
        while True:
            with lock:
                done = accepted(c)
            if args.target and done >= args.target:
                log.info("TARGET REACHED: %d accepted diagrams", done)
                break
            with lock:
                # balance across fields: take a pending paper from whichever
                # field has the fewest accepted diagrams so far
                row = c.execute("""
                  SELECT p.arxiv_id, p.field, p.pdf_url FROM papers p JOIN (
                    SELECT f.field FROM (SELECT DISTINCT field FROM papers WHERE status='pending') f
                    LEFT JOIN (SELECT field, COUNT(*) n FROM images
                               WHERE status IN ('local','uploaded') GROUP BY field) i
                      ON i.field = f.field
                    ORDER BY COALESCE(i.n, 0) ASC LIMIT 1
                  ) pick ON p.field = pick.field
                  WHERE p.status='pending' LIMIT 1""").fetchone()
                if row:
                    c.execute("UPDATE papers SET status='processing' WHERE arxiv_id=?", (row[0],))
            if not row:
                time.sleep(3)
                continue
            paper = {"arxiv_id": row[0], "field": row[1], "pdf_url": row[2]}
            try:
                process_paper(c, lock, paper, args.gate_threshold)
            except Exception as exc:
                log.warning("[process] %s: %s", paper["arxiv_id"], exc)
                with lock:
                    c.execute("UPDATE papers SET status='failed' WHERE arxiv_id=?", (paper["arxiv_id"],))
            with lock:
                for f in FIELDS:
                    commit_pdf_zip(c, f)
            now = time.monotonic()
            if now - last_status > 30:
                last_status = now
                with lock:
                    dn = c.execute("SELECT COUNT(*) FROM papers WHERE status='done'").fetchone()[0]
                    up = c.execute("SELECT COUNT(*) FROM images WHERE status='uploaded'").fetchone()[0]
                log.info("STATUS accepted %d/%d | uploaded %d | papers %d | upload_q %d",
                         done, args.target, up, dn, _upload_q.qsize())
            if now - last_gallery > 180:
                last_gallery = now
                with lock:
                    ok, ni = gallery.build_and_upload(c)
                if ok:
                    log.info("[gallery] refreshed: %d images -> %s/v3/gallery/index.html",
                             ni, gallery.R2_PUBLIC)
    except KeyboardInterrupt:
        log.warning("interrupted")
    finally:
        stop.set()
        log.info("draining %d uploads...", _upload_q.qsize())
        deadline = time.time() + 120
        while not _upload_q.empty() and time.time() < deadline:
            time.sleep(1)
        with lock:
            for f in FIELDS:
                commit_pdf_zip(c, f, force=True)
            gallery.build_and_upload(c)
    log.info("FINAL: %d accepted, gallery at %s/v3/gallery/index.html",
             accepted(c), gallery.R2_PUBLIC)


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
    run(args)
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
