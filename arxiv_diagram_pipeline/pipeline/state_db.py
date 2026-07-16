"""SQLite state store for the v2 pipeline.

Single-file, WAL-mode, one shared connection guarded by a lock so the
downloader/harvester threads and the main scheduler can all write safely.
Every mutation commits immediately (autocommit), so a crash, Ctrl-C, or
exhausted API credits never lose more than the call that was in flight.
"""

import json
import sqlite3
import threading

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  arxiv_id TEXT PRIMARY KEY,
  base_id  TEXT NOT NULL,
  field    TEXT NOT NULL,
  title TEXT DEFAULT '', authors TEXT DEFAULT '', published TEXT DEFAULT '',
  abs_url TEXT DEFAULT '', pdf_url TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|downloaded|failed
  n_pages INTEGER DEFAULT 0,
  error TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_base ON papers(base_id);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status, field);

CREATE TABLE IF NOT EXISTS pages (
  arxiv_id TEXT NOT NULL,
  page_no INTEGER NOT NULL,                 -- 1-based
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|done|failed
  has_diagram INTEGER DEFAULT 0,
  detect_json TEXT DEFAULT '',
  ocr_md TEXT DEFAULT '',
  batch_id INTEGER DEFAULT 0,               -- 0 = not yet assigned to an OCR batch
  cost REAL DEFAULT 0,
  error TEXT DEFAULT '',
  PRIMARY KEY (arxiv_id, page_no)
);
CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
CREATE INDEX IF NOT EXISTS idx_pages_diagram ON pages(has_diagram, batch_id);

CREATE TABLE IF NOT EXISTS ocr_batches (
  batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pdf_path TEXT DEFAULT '',
  manifest_json TEXT NOT NULL,              -- [[arxiv_id, page_no], ...] in page order
  status TEXT NOT NULL DEFAULT 'building',  -- building|pending|done|failed
  error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS images (
  image_id INTEGER PRIMARY KEY AUTOINCREMENT,
  arxiv_id TEXT NOT NULL,
  page_no INTEGER NOT NULL,
  batch_id INTEGER NOT NULL,
  file_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|labeled|rejected|failed
  reject_reason TEXT DEFAULT '',
  diagram_type TEXT DEFAULT '', title TEXT DEFAULT '', label TEXT DEFAULT '',
  cost REAL DEFAULT 0,
  error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_images_path ON images(file_path);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class StateDB:
    def __init__(self, path=None):
        self.conn = sqlite3.connect(
            str(path or config.STATE_DB), check_same_thread=False,
            isolation_level=None, timeout=60,
        )
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)

    def _exec(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params)

    def _all(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def _one(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def _val(self, sql, params=()):
        row = self._one(sql, params)
        return row[0] if row else 0

    # ---- papers ----

    def add_papers(self, field, papers):
        """Insert harvested papers; silently skips duplicates (same id or same
        versionless base id already registered, possibly under another field)."""
        added = 0
        for p in papers:
            base_id = p["arxiv_id"].rsplit("v", 1)[0]
            with self.lock:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO papers "
                    "(arxiv_id, base_id, field, title, authors, published, abs_url, pdf_url) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (p["arxiv_id"], base_id, field, p["title"],
                     "; ".join(p.get("authors", [])), p.get("published", ""),
                     p.get("abs_url", ""), p.get("pdf_url", "")),
                )
                added += cur.rowcount
        return added

    def next_pending_paper(self):
        """Pending paper from the least-downloaded field, for balanced coverage."""
        row = self._one(
            "SELECT p.* FROM papers p JOIN ("
            "  SELECT field, SUM(status='downloaded') AS done FROM papers"
            "  GROUP BY field HAVING SUM(status='pending') > 0 ORDER BY done LIMIT 1"
            ") f ON p.field = f.field WHERE p.status='pending' LIMIT 1"
        )
        return dict(row) if row else None

    def mark_paper_downloaded(self, arxiv_id, n_pages):
        with self.lock:
            self.conn.execute(
                "UPDATE papers SET status='downloaded', n_pages=? WHERE arxiv_id=?",
                (n_pages, arxiv_id))
            self.conn.executemany(
                "INSERT OR IGNORE INTO pages (arxiv_id, page_no) VALUES (?,?)",
                [(arxiv_id, p) for p in range(1, n_pages + 1)])

    def mark_paper_failed(self, arxiv_id, error):
        self._exec("UPDATE papers SET status='failed', error=? WHERE arxiv_id=?",
                   (str(error)[:500], arxiv_id))

    def paper(self, arxiv_id):
        row = self._one("SELECT * FROM papers WHERE arxiv_id=?", (arxiv_id,))
        return dict(row) if row else None

    # ---- pages / detection ----

    def pending_pages(self, limit, exclude=()):
        rows = self._all(
            "SELECT g.arxiv_id, g.page_no, p.field, p.title FROM pages g "
            "JOIN papers p ON p.arxiv_id = g.arxiv_id "
            "WHERE g.status='pending' ORDER BY g.arxiv_id, g.page_no LIMIT ?",
            (limit + len(exclude),))
        out = [dict(r) for r in rows if (r["arxiv_id"], r["page_no"]) not in exclude]
        return out[:limit]

    def set_page_detected(self, arxiv_id, page_no, has_diagram, detect_json, cost):
        self._exec(
            "UPDATE pages SET status='done', has_diagram=?, detect_json=?, cost=? "
            "WHERE arxiv_id=? AND page_no=?",
            (1 if has_diagram else 0, detect_json, cost, arxiv_id, page_no))

    def set_page_failed(self, arxiv_id, page_no, error):
        self._exec("UPDATE pages SET status='failed', error=? WHERE arxiv_id=? AND page_no=?",
                   (str(error)[:500], arxiv_id, page_no))

    def set_page_ocr_md(self, arxiv_id, page_no, ocr_md):
        self._exec("UPDATE pages SET ocr_md=? WHERE arxiv_id=? AND page_no=?",
                   (ocr_md[:config.OCR_CONTEXT_CHARS], arxiv_id, page_no))

    def unbatched_diagram_pages(self, limit):
        rows = self._all(
            "SELECT arxiv_id, page_no FROM pages "
            "WHERE has_diagram=1 AND batch_id=0 AND status='done' "
            "ORDER BY arxiv_id, page_no LIMIT ?", (limit,))
        return [(r["arxiv_id"], r["page_no"]) for r in rows]

    # ---- OCR batches ----

    def create_batch(self, manifest):
        """Register a batch and claim its pages atomically. Returns batch_id."""
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO ocr_batches (manifest_json) VALUES (?)",
                (json.dumps(manifest),))
            batch_id = cur.lastrowid
            self.conn.executemany(
                "UPDATE pages SET batch_id=? WHERE arxiv_id=? AND page_no=?",
                [(batch_id, a, p) for a, p in manifest])
        return batch_id

    def set_batch_built(self, batch_id, pdf_path):
        self._exec("UPDATE ocr_batches SET status='pending', pdf_path=? WHERE batch_id=?",
                   (str(pdf_path), batch_id))

    def batches_with_status(self, status, limit=100):
        rows = self._all("SELECT * FROM ocr_batches WHERE status=? LIMIT ?", (status, limit))
        return [dict(r) for r in rows]

    def mark_batch_done(self, batch_id):
        self._exec("UPDATE ocr_batches SET status='done' WHERE batch_id=?", (batch_id,))

    def mark_batch_failed(self, batch_id, error):
        self._exec("UPDATE ocr_batches SET status='failed', error=? WHERE batch_id=?",
                   (str(error)[:500], batch_id))

    # ---- images ----

    def add_image(self, arxiv_id, page_no, batch_id, file_path,
                  status="pending", reject_reason=""):
        # OR IGNORE + unique file_path: replaying a half-processed OCR batch
        # after a crash must not create duplicate rows.
        self._exec(
            "INSERT OR IGNORE INTO images "
            "(arxiv_id, page_no, batch_id, file_path, status, reject_reason) "
            "VALUES (?,?,?,?,?,?)",
            (arxiv_id, page_no, batch_id, str(file_path), status, reject_reason))

    def pending_images(self, limit, exclude=()):
        rows = self._all(
            "SELECT i.image_id, i.arxiv_id, i.page_no, i.file_path, "
            "       g.ocr_md, g.detect_json, p.field, p.title "
            "FROM images i "
            "JOIN pages g ON g.arxiv_id = i.arxiv_id AND g.page_no = i.page_no "
            "JOIN papers p ON p.arxiv_id = i.arxiv_id "
            "WHERE i.status='pending' ORDER BY i.image_id LIMIT ?",
            (limit + len(exclude),))
        out = [dict(r) for r in rows if r["image_id"] not in exclude]
        return out[:limit]

    def set_image_labeled(self, image_id, diagram_type, title, label, cost):
        self._exec(
            "UPDATE images SET status='labeled', diagram_type=?, title=?, label=?, cost=? "
            "WHERE image_id=?", (diagram_type, title, label, cost, image_id))

    def set_image_rejected(self, image_id, reason, cost=0.0, new_path=None):
        if new_path is None:
            self._exec(
                "UPDATE images SET status='rejected', reject_reason=?, cost=? WHERE image_id=?",
                (reason[:200], cost, image_id))
        else:
            self._exec(
                "UPDATE images SET status='rejected', reject_reason=?, cost=?, file_path=? "
                "WHERE image_id=?", (reason[:200], cost, str(new_path), image_id))

    def set_image_failed(self, image_id, error):
        self._exec("UPDATE images SET status='failed', error=? WHERE image_id=?",
                   (str(error)[:500], image_id))

    def labeled_rows(self):
        """Iterate export rows for all accepted (labeled) diagrams."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT i.image_id, i.file_path, i.diagram_type, i.title AS diagram_title, "
                "       i.label, i.page_no, p.field, p.arxiv_id, p.title AS paper_title, "
                "       p.authors, p.published, p.abs_url, p.pdf_url "
                "FROM images i JOIN papers p ON p.arxiv_id = i.arxiv_id "
                "WHERE i.status='labeled' ORDER BY i.image_id").fetchall()
        return [dict(r) for r in rows]

    def mark_page_unbatchable(self, arxiv_id, page_no, reason):
        """Diagram page whose source PDF is gone — exclude from future batches."""
        self._exec(
            "UPDATE pages SET batch_id=-1, error=? WHERE arxiv_id=? AND page_no=?",
            (reason[:200], arxiv_id, page_no))

    # ---- meta ----

    def get_meta(self, key, default=""):
        row = self._one("SELECT value FROM meta WHERE key=?", (key,))
        return row[0] if row else default

    def set_meta(self, key, value):
        self._exec("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                   (key, str(value)))

    # ---- recovery / stats ----

    def reset_transient_failures(self):
        """On startup, requeue everything that failed mid-run so it retries."""
        with self.lock:
            n1 = self.conn.execute(
                "UPDATE pages SET status='pending', error='' WHERE status='failed'").rowcount
            n2 = self.conn.execute(
                "UPDATE images SET status='pending', error='' WHERE status='failed'").rowcount
            n3 = self.conn.execute(
                "UPDATE ocr_batches SET status='pending', error='' "
                "WHERE status='failed' AND pdf_path != ''").rowcount
        return n1, n2, n3

    def labeled_count(self):
        return self._val("SELECT COUNT(*) FROM images WHERE status='labeled'")

    def counts(self):
        c = {}
        c["papers_total"] = self._val("SELECT COUNT(*) FROM papers")
        c["papers_pending"] = self._val("SELECT COUNT(*) FROM papers WHERE status='pending'")
        c["papers_downloaded"] = self._val("SELECT COUNT(*) FROM papers WHERE status='downloaded'")
        c["pages_total"] = self._val("SELECT COUNT(*) FROM pages")
        c["pages_pending"] = self._val("SELECT COUNT(*) FROM pages WHERE status='pending'")
        c["pages_diagram"] = self._val("SELECT COUNT(*) FROM pages WHERE has_diagram=1")
        c["batches_pending"] = self._val(
            "SELECT COUNT(*) FROM ocr_batches WHERE status IN ('building','pending')")
        c["images_total"] = self._val("SELECT COUNT(*) FROM images")
        c["images_pending"] = self._val("SELECT COUNT(*) FROM images WHERE status='pending'")
        c["labeled"] = self._val("SELECT COUNT(*) FROM images WHERE status='labeled'")
        c["rejected"] = self._val("SELECT COUNT(*) FROM images WHERE status='rejected'")
        c["cost"] = (self._val("SELECT COALESCE(SUM(cost),0) FROM pages") or 0) + \
                    (self._val("SELECT COALESCE(SUM(cost),0) FROM images") or 0)
        return c

    def close(self):
        with self.lock:
            self.conn.close()
