# Task Plan: arXiv Diagram Extraction & Labeling Pipeline

## Goal
Build a pipeline in `/Users/siraj/STEM DIagrams` that:
1. Downloads arXiv papers in 6 fields: Semiconductor Engineering, Manufacturing Engineering, Robotics & Automation, Utilities & Power Systems, Aerospace Engineering, Telecommunications.
2. Renders each PDF page and asks OpenRouter model `xiaomi/mimo-v2.5-pro` which pages contain diagrams.
3. Runs Mistral OCR (model configurable, "OCR 3" / latest) on diagram pages; saves the images Mistral OCR extracts.
4. Sends each extracted image back to the same LLM with page context + diagram context, asks for a good, detailed labeling.
5. Saves everything locally in a proper folder structure.
6. Exports TWO Excel files: one WITH source columns, one WITHOUT source — both contain the label.
7. Ships an empty `.env` template for both API keys (OPENROUTER_API_KEY, MISTRAL_API_KEY).

## Phases

### Phase 1: Scaffolding — complete
- [x] Project dir `arxiv_diagram_pipeline/`, `.env` template, `requirements.txt`, `config.py`

### Phase 2: Pipeline modules — complete
- [x] `arxiv_client.py` — arXiv Atom API search + PDF download (3s rate limit)
- [x] `page_renderer.py` — PyMuPDF page → JPEG
- [x] `openrouter_client.py` — chat completions w/ retry, JSON parsing
- [x] `diagram_detector.py` — per-page has_diagram analysis
- [x] `mistral_ocr.py` — /v1/ocr with include_image_base64, save images; full-page fallback
- [x] `diagram_labeler.py` — image + page context + diagram context → detailed label
- [x] `excel_exporter.py` — labels_with_source.xlsx / labels_without_source.xlsx

### Phase 3: Orchestrator + docs — complete
- [x] `run_pipeline.py` CLI (stages: download/detect/ocr/label/export, resumable, idempotent)
- [x] `README.md`

### Phase 4: Verify — complete
- [x] venv + deps install (Python 3.14 venv; PyMuPDF 1.28.0 wheel works)
- [x] arXiv search+download real-network test: 6/6 fields have 1 paper each
- [x] Page rendering works (110 DPI JPEG, ~250 KB/page)
- [x] Detect stage fails gracefully with empty key: one-line ERROR, no traceback
- [x] Excel export verified with mock label (both workbooks, correct columns); mock cleaned up
- [x] py_compile + import check on all modules

### Phase 5: Git + GitHub — complete
- [x] .gitignore (excludes .env, data/, venv) + .env.example
- [x] git init, initial commit (root incl. planning files)
- [x] Private GitHub repo created + pushed

### Phase 6: Real run — goal: ≥ a few dozen labeled diagrams — in_progress
- [x] Real API keys saved to .env (OpenRouter + Mistral, user-supplied 2026-07-16)
- [x] DATA_DIR moved to external disk `/Volumes/One Touch/stem_diagrams_data` (config.py reads DATA_DIR env override); local test data (22MB, 6 papers) migrated over
- [x] Sanity-check detect on real API (6 papers, 2 pages each) — found xiaomi/mimo-v2.5-pro is TEXT-ONLY on OpenRouter (404 "No endpoints found that support image input"). Switched OPENROUTER_MODEL to xiaomi/mimo-v2.5 (multimodal sibling, confirmed via /api/v1/models). Fixed retry bug: non-retryable 4xx were being retried.
- [x] Sanity-check ocr + label + export on real API — worked end-to-end: 12 pages (6 papers × 2) → 3 diagram pages → 4 images → 4 real detailed labels → both Excel files written. Yield ≈ 1 diagram per 3 pages.
- [x] Scale up: downloaded 42 papers (7/field), ran detect on first 6 pages of each. Hit 2 more bugs during the run, fixed both (resumable, no data lost): (1) per-page work wasn't fully wrapped in try/except — a transient ExFAT/USB mkdir ENOENT crashed the whole stage; now the full render+detect body is one try/except per page, logged and retried next run. (2) OpenRouter reasoning model can return null content when it exhausts max_tokens on hidden reasoning — now treated as a retryable HTTPError instead of crashing extract_json(None). Bumped max_tokens (detect 2000→3500, label 3000→4500) to reduce frequency. Detect stage ran ~3.5h across 248 pages (many transient network retries, all recovered) → **72 diagram pages found**.
- [x] OCR stage: 72 diagram pages → 143 real images (filtered ExFAT `._` sidecar noise from raw count). Some pages over-segmented (one page → 18 image fragments, mostly sub-panels/time-series crops rather than distinct full diagrams) — noted as a data-quality caveat, not fixed (would need per-image size/content filtering, out of scope for this run).
- [x] Label stage: hit a second crash from the same ExFAT/USB transient-I/O root cause, this time in `iter_diagram_pages()` (unprotected `json.loads` read) — swept the whole file and hardened every remaining unprotected read (`iter_papers`, `iter_diagram_pages`, `stage_export`, PDF page-count in `stage_detect`, OCR-markdown read in `stage_label`) so a flaky read logs+skips instead of killing the stage. Also patched `extract_json` to use `json.JSONDecoder(strict=False)`, tolerating raw control characters in LLM string output (fixes a chunk of, not all, JSON-parse failures — some models still emit invalid `\` escapes that need real JSON repair, out of scope). One run also silently stopped ~2/3 through after a real (very brief) drive disconnect — re-running (idempotent) picked up cleanly and finished. Final: **141/143 images labeled** (2 permanently stuck on invalid-escape JSON, acceptable given far exceeds goal).
- [x] Export: 141 diagrams → both Excel files verified (13 cols with-source / 5 cols without-source, matching row counts, 141 flat anonymized images copied). Field spread: Aerospace 46, Telecom 25, Semiconductor 23, Utilities & Power 20, Robotics 16, Manufacturing 11.
- [x] Cleaned ExFAT `._` AppleDouble sidecar files off the drive (`dot_clean -m`) for a tidy deliverable; verified real files (141 images, 42 PDFs) untouched.
- [x] Report diagram count + Excel paths to user — DONE, see final response.

### Phase 7: v2 scale-up — target 30,000 proper diagrams — in_progress
Goal (user, 2026-07-16): quality-classify extracted images (blanks/non-diagrams slip through), 30k proper diagrams on external disk, parallelize (12-20 concurrent OpenRouter calls OK), survive credit-exhaustion/transient errors (resume exactly), rasterize PDFs in-memory, batch diagram pages into combined PDFs so Mistral OCR is ~1 call per ~30-50 pages (manifest maps batch page → source paper+page), delegate grunt work to Sonnet subagents.
- [x] Architecture: SQLite state.db (local, WAL, autocommit) + threads: harvester/downloader + 20-worker LLM pool (detect+label) + 2-worker OCR pool; main thread = scheduler, sole DB writer alongside the two loops
- [x] Sonnet subagents delivered: pipeline/image_filter.py (local blank/tiny/sliver reject, self-tested), arxiv_client.search_paginated (+start_offset added by me), excel_exporter.export_v2 (write_only, 30k rows) + status_v2.py stats CLI
- [x] Core (Fable): state_db.py, pdf_batcher.py (vector-page batch PDFs, validate+size-split), mistral_ocr.ocr_pdf (batch, 402→CreditsExhausted), openrouter_client v2 (cost meta, reasoning effort w/ fallback, 402 fatal, NO max_tokens — user rule, now in ~/.claude/CLAUDE.md), diagram_labeler.classify_and_label (strict accept/reject + label in one call), run_pipeline_v2.py orchestrator
- [x] Verified on real APIs: batched 3-page PDF (2 papers) OCR in ONE Mistral call, index→manifest mapping correct, images per page match v1 counts; reasoning effort=low accepted (14.9s detect, $0.0005); effort=none NOT faster (16-22s) → keep low
- [x] Batch PDF size reality: ~900KB/page → OCR_BATCH_MAX_MB=20 guard (base64 +33%, Mistral cap 50MB) → effective batches ~20-25 pages
- [ ] Integration test --target 12 (in progress): end-to-end + kill/resume verification
- [ ] Commit + push, then launch 30k production run (nohup, Monitor), periodic checks, final export + report

## Key Decisions
| Decision | Rationale |
|----------|-----------|
| Plain `requests` for OpenRouter + Mistral (no SDKs) | fewer deps, both are simple REST APIs |
| PyMuPDF for rendering | fast, no external binaries |
| Per-stage JSON outputs on disk, skip-if-exists | resumable, idempotent, cheap re-runs |
| If Mistral OCR extracts 0 images on a diagram page → fall back to full page render as the diagram image | never lose a detected diagram |
| Field→arXiv mapping uses category+keyword queries | arXiv has no direct taxonomy for these 6 fields |
| openpyxl for Excel | writes .xlsx directly, supports 2 workbooks |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| arXiv PDF 404 on fresh v1 submissions (arxiv.org/pdf/<id>v1) | 1 | Fallback candidate URLs: export.arxiv.org + versionless id — versionless works |
| arxiv.org read timeout (120 s) on one PDF | 1 | Covered by same multi-URL retry loop |
| A field could end with < quota papers when downloads fail | 1 | Over-fetch search (3× quota), stop at quota, warn if short |
