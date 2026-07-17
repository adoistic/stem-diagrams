#!/usr/bin/env python3
"""Wire the arXiv link into the repo once the paper is submitted.

Usage:  python paper/add_arxiv_link.py 2607.XXXXX
Run from the repo root (the folder containing README.md). Idempotent: running
it again with the same id changes nothing. Edits README.md, the site hero, and
the BibTeX citation, then prints what changed. Review, commit, push.
"""

import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def main():
    if len(sys.argv) != 2 or not ID_RE.match(sys.argv[1]):
        sys.exit("usage: python paper/add_arxiv_link.py <arxiv_id>  "
                 "(e.g. 2607.12345)")
    aid = sys.argv[1]
    url = f"https://arxiv.org/abs/{aid}"
    changed = []

    # 1) README.md — add a link line + BibTeX eprint fields
    readme = Path("README.md")
    r = readme.read_text()
    if "arxiv.org/abs" not in r:
        r = r.replace(
            "📄 **[Read the paper (PDF)]",
            f"📚 **[arXiv:{aid}]({url})** ·\n📄 **[Read the paper (PDF)]", 1)
        r = r.replace(
            "  year   = {2026},",
            "  year   = {2026},\n"
            f"  eprint = {{{aid}}},\n  archivePrefix = {{arXiv}},", 1)
        readme.write_text(r)
        changed.append("README.md")

    # 2) docs/index.html — add an arXiv button in the hero (guard on the button
    # text, not any arxiv link — the gallery already links to arxiv.org/abs)
    html = Path("arxiv_diagram_pipeline/docs/index.html")
    h = html.read_text()
    if 'class="btn" href="https://arxiv.org/abs' not in h:
        h = h.replace(
            '<a class="btn primary" href="./paper.pdf">Read the paper (PDF)</a>',
            f'<a class="btn primary" href="./paper.pdf">Read the paper (PDF)</a>\n'
            f'    <a class="btn" href="{url}">arXiv:{aid}</a>', 1)
        html.write_text(h)
        changed.append("arxiv_diagram_pipeline/docs/index.html")

    if changed:
        print("Updated:", ", ".join(changed))
        print(f"arXiv link wired in as {url}")
        print("Next: git add -A && git commit -m 'Add arXiv link' && git push")
    else:
        print("arXiv link already present — nothing to do.")


if __name__ == "__main__":
    main()
