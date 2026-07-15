# Findings

## Environment
- Python 3.14.5 at /opt/homebrew/bin/python3, macOS (darwin 24.6.0)
- Working dir `/Users/siraj/STEM DIagrams` was empty at session start
- PyMuPDF: needs verification that a cp314 wheel exists; fallback = pypdfium2 or brew python@3.12 venv

## API references (from prior knowledge — verify on first real run)
- arXiv Atom API: `http://export.arxiv.org/api/query?search_query=...&start=0&max_results=N&sortBy=submittedDate&sortOrder=descending`; be polite: ≥3s between requests; PDF at `https://arxiv.org/pdf/<id>`.
- OpenRouter: `POST https://openrouter.ai/api/v1/chat/completions`, Bearer key, OpenAI-style messages; vision via `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`.
- Mistral OCR: `POST https://api.mistral.ai/v1/ocr` with `{"model": "...", "document": {"type":"image_url","image_url":"data:image/png;base64,..."}, "include_image_base64": true}` → `pages[].markdown`, `pages[].images[].{id,image_base64,top_left_x,...}`. Model name configurable (`mistral-ocr-latest` default) since "OCR 3" naming may differ.

## Field → arXiv query mapping (design)
- Semiconductor Engineering: cat:cond-mat.mes-hall / physics.app-ph + semiconductor keywords
- Manufacturing Engineering: keyword-driven (manufacturing, additive manufacturing) over eess.SY/physics.app-ph/cs.CE
- Robotics & Automation: cat:cs.RO (direct match)
- Utilities & Power Systems: cat:eess.SY + power grid/smart grid/microgrid keywords
- Aerospace Engineering: keywords aircraft/spacecraft/UAV/satellite over eess.SY/cs.RO/physics.flu-dyn
- Telecommunications: cat:eess.SP/cs.NI/cs.IT + wireless/5G/antenna keywords

## Verification results (2026-07-16, actual)
- venv: Python 3.14.5 works fine — PyMuPDF 1.28.0 has a cp314 wheel (earlier assumption that 3.13 was needed proved WRONG). Installed: requests, python-dotenv, PyMuPDF 1.28.0, openpyxl.
- arXiv API: all 6 field queries return results; 6/6 fields downloaded 1 paper each.
- Fresh v1 submissions can 404 on arxiv.org/pdf/<id>vN — versionless URL works; also saw a 120 s read timeout on export.arxiv.org. Multi-candidate URL loop handles both.
- Rendering: page 1 of aerospace paper → 249 KB JPEG @ 110 DPI q80.
- Missing-key behavior: `ERROR: OPENROUTER_API_KEY is empty — fill it in .env`, exit code 1, no traceback.
- Excel export (mock label): with-source = 13 cols (Field, ArXiv ID, Paper Title, Authors, Published, Abstract URL, PDF URL, Page, Source Image Path, Image File, Diagram Type, Diagram Title, Label); without-source = 5 cols (Field, Image File, Diagram Type, Diagram Title, Label). Flat anonymized copies in data/output/diagram_images/. Mock data cleaned up after test.
