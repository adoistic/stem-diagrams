# Findings

## Environment
- Python 3.14.5 at /opt/homebrew/bin/python3, macOS (darwin 24.6.0)
- Working dir `/Users/siraj/STEM DIagrams` was empty at session start
- PyMuPDF: needs verification that a cp314 wheel exists; fallback = pypdfium2 or brew python@3.12 venv

## API references (from prior knowledge — verify on first real run)
- arXiv Atom API: `http://export.arxiv.org/api/query?search_query=...&start=0&max_results=N&sortBy=submittedDate&sortOrder=descending`; be polite: ≥3s between requests; PDF at `https://arxiv.org/pdf/<id>`.
- OpenRouter: `POST https://openrouter.ai/api/v1/chat/completions`, Bearer key, OpenAI-style messages; vision via `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`.
- Mistral OCR: `POST https://api.mistral.ai/v1/ocr` with `{"model": "...", "document": {"type":"image_url","image_url":"data:image/png;base64,..."}, "include_image_base64": true}` → `pages[].markdown`, `pages[].images[].{id,image_base64,top_left_x,...}`. Model name configurable (`mistral-ocr-latest` default) since "OCR 3" naming may differ.

## Real-run findings (2026-07-16, with real API keys)
- **xiaomi/mimo-v2.5-pro is TEXT-ONLY on OpenRouter.** `GET /api/v1/models` shows `input_modalities: ["text"]` for `-pro`, vs `["text","audio","image","video"]` for plain `xiaomi/mimo-v2.5`. A vision call to `-pro` returns HTTP 404 `{"error":{"message":"No endpoints found that support image input","code":404}}` — NOT a transient error, will always fail. Switched runtime model to `xiaomi/mimo-v2.5` via `OPENROUTER_MODEL` in .env (config.py already supported this override). If OpenRouter later adds vision to `-pro`, just change the env var back.
- This model is a *reasoning* model — `reasoning` field appears in the response with `finish_reason:"length"` possible if max_tokens is too small (burns tokens on reasoning before content). Current max_tokens (2000 detect / 3000 label) worked fine in testing; watch for empty `content` on especially verbose pages.
- Diagram yield in first real batch (6 papers, first 2 pages each = 12 pages): 3 diagram pages found, 4 images extracted by Mistral OCR, all 4 labeled successfully. Rough yield ≈ 1 diagram / 3 pages, but very front-loaded (page 1-2 of a paper often has the main system/architecture figure) — deeper pages may yield less.
- Mistral OCR: extracts multiple images per page when present (page 2 of the aerospace UAV paper yielded 2 images from one page). Response shape matches what mistral_ocr.py assumed (pages[].images[].image_base64, pages[].markdown).
- External disk confirmed: `/Volumes/One Touch` (4TB, ~2.6TB free at start), writable. DATA_DIR set there via .env; config.py DATA_DIR now reads `os.getenv("DATA_DIR")` override.
- ExFAT-over-USB gotcha: macOS writes `._<filename>` AppleDouble sidecar files alongside every real file on ExFAT (no native metadata support). `find -name "*.jpg"` picks these up too (they carry the same extension), inflating file counts 2x. Always filter `grep -v '/\._'` or match on the real `page_*` prefix when counting. The pipeline code itself is unaffected — `diagrams_dir.glob(f"page_{page:03d}_*")` in the label stage only matches real files since sidecar names start with `._`, not `page_`.
- Full real run (42 papers, 6 pages each, all 6 fields): detect found 72 diagram pages out of 248 analyzed (took ~3.5h, mostly OpenRouter network latency/retries, no data lost). Mistral OCR on those 72 pages extracted 143 real images (~10 min, much faster than the reasoning-model detect calls) — some pages are heavily over-segmented (one page yielded 18 images, likely sub-panel/legend fragments rather than 18 distinct diagrams) — worth a quality caveat, not a bug.

## v2 production findings (2026-07-16)
- **arXiv 429-throttles aggressive API pagination.** Front-loading the whole projected paper need (5k+ registrations in ~7 min of back-to-back paginated queries, interleaved with PDF downloads) got the API 429'd; the paginator misread 3 failed retries as end-of-results → false "supply exhausted". Fixes: thread-safe global throttle (harvest+download threads previously raced past the 3s spacing), 429 → 60-300s backoff distinct from genuine empty feeds (TemporarilyUnavailable exception), rolling ~1500-paper harvest buffer instead of front-loading (downloader only consumes ~20 papers/min).
- Graceful restart mid-production verified: SIGTERM drained in-flight calls (133 labeled), relaunch resumed instantly, zero loss.
- LaTeX backslashes in LLM JSON output (`\alpha`) = "Invalid \escape" parse failures (~12% of label calls!) — fixed by doubling invalid escape sequences before a second parse attempt in extract_json.
- Local tiny-file filter (<8KB JPEG) is the dominant reject (77/82 in test); spot-checked correct — sub-8KB crops are icon-sized fragments. LLM rejects catch data plots/fragments as prompted.
- Measured economics: ~$0.019 per accepted diagram → ~$550-600 for 30k. Throughput ~10-14 accepted/min at 20 workers (detect is the long pole at ~15s/call) → ~2-2.5 days.

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
