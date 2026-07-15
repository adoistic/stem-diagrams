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
