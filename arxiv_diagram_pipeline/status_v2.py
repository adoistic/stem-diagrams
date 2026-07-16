#!/usr/bin/env python3
"""Read-only stats dashboard for the v2 SQLite pipeline state.

Usage:
  python status_v2.py
  python status_v2.py --db /path/to/state.db --target 30000
"""

import argparse
import logging
import os
import sqlite3
import sys
import urllib.parse

import config

log = logging.getLogger(__name__)

DEFAULT_DB = str(config.PROJECT_ROOT / "state.db")
DEFAULT_TARGET = 30000


def open_db(db_path):
    """Open the SQLite DB read-only; returns a connection, or None if the
    file doesn't exist."""
    if not os.path.exists(db_path):
        return None
    uri = f"file:{urllib.parse.quote(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _counts_by_status(conn, table):
    """Return {status: count} for a table."""
    rows = conn.execute(f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status")
    return {row["status"]: row["n"] for row in rows}


def _print_papers(conn):
    by_status = _counts_by_status(conn, "papers")
    total = sum(by_status.values())
    downloaded = by_status.get("downloaded", 0)
    failed = by_status.get("failed", 0)
    print(f"\npapers: total={total} downloaded={downloaded} failed={failed}")

    rows = conn.execute(
        "SELECT field, status, COUNT(*) AS n FROM papers GROUP BY field, status"
    )
    per_field = {}
    for row in rows:
        per_field.setdefault(row["field"], {})[row["status"]] = row["n"]
    for field_key in sorted(per_field):
        counts = per_field[field_key]
        field_total = sum(counts.values())
        name = config.FIELDS.get(field_key, {}).get("name", field_key)
        print(
            f"  {name:<28} total={field_total:<5} "
            f"downloaded={counts.get('downloaded', 0):<5} "
            f"failed={counts.get('failed', 0)}"
        )


def _print_pages(conn):
    by_status = _counts_by_status(conn, "pages")
    total = sum(by_status.values())
    detected = by_status.get("done", 0)
    failed = by_status.get("failed", 0)
    has_diagram = conn.execute(
        "SELECT COUNT(*) AS n FROM pages WHERE has_diagram = 1"
    ).fetchone()["n"]
    hit_rate = (has_diagram / detected * 100) if detected else 0.0
    print(f"\npages: total={total} detected={detected} failed={failed}")
    print(f"  diagram pages found: {has_diagram} (hit rate: {hit_rate:.1f}%)")


def _print_ocr_batches(conn):
    by_status = _counts_by_status(conn, "ocr_batches")
    print(
        f"\nocr_batches: pending={by_status.get('pending', 0)} "
        f"done={by_status.get('done', 0)} failed={by_status.get('failed', 0)}"
    )


def _print_images(conn, target):
    by_status = _counts_by_status(conn, "images")
    total = sum(by_status.values())
    labeled = by_status.get("labeled", 0)
    print(
        f"\nimages: total={total} labeled={labeled} "
        f"rejected={by_status.get('rejected', 0)} "
        f"failed={by_status.get('failed', 0)} "
        f"pending={by_status.get('pending', 0)}"
    )

    top_reasons = conn.execute(
        "SELECT reject_reason, COUNT(*) AS n FROM images "
        "WHERE reject_reason != '' GROUP BY reject_reason "
        "ORDER BY n DESC LIMIT 5"
    ).fetchall()
    if top_reasons:
        print("  top reject reasons:")
        for row in top_reasons:
            print(f"    {row['n']:<5} {row['reject_reason']}")

    cost = (
        (conn.execute("SELECT SUM(cost) AS c FROM images").fetchone()["c"] or 0.0)
        + (conn.execute("SELECT SUM(cost) AS c FROM pages").fetchone()["c"] or 0.0)
    )
    print(f"\ntotal accumulated cost (detection + labeling): ${cost:.4f}")

    pct = (labeled / target * 100) if target else 0.0
    print(f"\nprogress: labeled {labeled} / target {target} ({pct:.1f}%)")


def print_dashboard(conn, target):
    _print_papers(conn)
    _print_pages(conn)
    _print_ocr_batches(conn)
    _print_images(conn, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DEFAULT_DB, help="path to state.db")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET,
                        help="target labeled-image count for the progress line")
    args = parser.parse_args()

    conn = open_db(args.db)
    if conn is None:
        print(f"No state DB found at {args.db} — nothing to report yet.")
        sys.exit(0)

    try:
        print_dashboard(conn, args.target)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
