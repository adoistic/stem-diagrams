"""Search arXiv via the Atom API and download paper PDFs."""

import logging
import re
import time
import xml.etree.ElementTree as ET

import requests

API_URL = "http://export.arxiv.org/api/query"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}

log = logging.getLogger(__name__)

_last_request = 0.0


def _throttle(delay):
    global _last_request
    wait = delay - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _parse_entries(xml_text):
    """Parse an arXiv Atom feed into a list of paper metadata dicts."""
    root = ET.fromstring(xml_text)

    papers = []
    for entry in root.findall("atom:entry", ATOM):
        abs_url = (entry.findtext("atom:id", "", ATOM) or "").strip()
        arxiv_id = abs_url.split("/abs/", 1)[-1]
        pdf_url = ""
        for link in entry.findall("atom:link", ATOM):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        papers.append({
            "arxiv_id": arxiv_id,
            "title": re.sub(r"\s+", " ", entry.findtext("atom:title", "", ATOM)).strip(),
            "abstract": (entry.findtext("atom:summary", "", ATOM) or "").strip(),
            "authors": [
                (a.findtext("atom:name", "", ATOM) or "").strip()
                for a in entry.findall("atom:author", ATOM)
            ],
            "published": (entry.findtext("atom:published", "", ATOM) or "")[:10],
            "abs_url": abs_url,
            "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return papers


def search(query, max_results, delay=3.0):
    """Return a list of paper metadata dicts for an arXiv search query."""
    _throttle(delay)
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = requests.get(API_URL, params=params, timeout=60)
    resp.raise_for_status()
    return _parse_entries(resp.text)


def search_paginated(query, total, page_size=200, delay=3.0, start_offset=0):
    """Yield up to `total` paper dicts for an arXiv query, paginating with
    the API's `start` parameter (beginning at `start_offset`). Stops early
    when arXiv returns no more results. Tolerates transient empty/error
    responses."""
    page_size = min(page_size, 1000)
    seen_ids = set()
    yielded = 0
    start = start_offset

    while yielded < total:
        params = {
            "search_query": query,
            "start": start,
            "max_results": page_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        papers = []
        for attempt in range(3):
            _throttle(delay)
            try:
                resp = requests.get(API_URL, params=params, timeout=60)
                resp.raise_for_status()
                papers = _parse_entries(resp.text)
            except requests.RequestException as exc:
                log.warning("arXiv page fetch failed (start=%s, attempt=%s): %s", start, attempt + 1, exc)
                papers = []

            if papers:
                break
            log.warning("arXiv page empty (start=%s, attempt=%s)", start, attempt + 1)
            if attempt < 2:
                time.sleep(5)

        if not papers:
            log.info("arXiv returned no results after retries (start=%s); stopping", start)
            break

        for paper in papers:
            if paper["arxiv_id"] in seen_ids:
                continue
            seen_ids.add(paper["arxiv_id"])
            yield paper
            yielded += 1
            if yielded >= total:
                break

        start += page_size


def _candidate_urls(pdf_url, arxiv_id):
    """Fresh submissions 404 on some mirrors; try a few equivalent URLs."""
    urls = [pdf_url] if pdf_url else []
    versionless = re.sub(r"v\d+$", "", arxiv_id)
    for aid in (arxiv_id, versionless):
        for host in ("arxiv.org", "export.arxiv.org"):
            url = f"https://{host}/pdf/{aid}"
            if url not in urls:
                urls.append(url)
    return urls


def download_pdf(pdf_url, dest_path, delay=3.0, arxiv_id=""):
    arxiv_id = arxiv_id or pdf_url.rstrip("/").rsplit("/", 1)[-1]
    last_exc = None
    for url in _candidate_urls(pdf_url, arxiv_id):
        _throttle(delay)
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            if not resp.content.startswith(b"%PDF"):
                raise ValueError(f"Response from {url} is not a PDF")
            dest_path.write_bytes(resp.content)
            return
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            log.warning("PDF fetch failed for %s: %s", url, exc)
    raise last_exc
