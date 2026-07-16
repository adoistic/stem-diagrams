# Progress Log

## Session 1 — 2026-07-16
- 00:58 Directory empty, Python 3.14.5 confirmed. No prior session (skipped catchup).
- Created task_plan.md / findings.md / progress.md.
- Scaffolded `arxiv_diagram_pipeline/` (config, 7 pipeline modules, run_pipeline.py, README, .env + .env.example, requirements.txt, .gitignore at root).
- venv (Python 3.14) + deps installed; PyMuPDF 1.28.0 OK.
- Download stage tested live: 6/6 fields → 1 paper each (after adding fallback PDF URLs + over-fetch).
- Detect stage: page renders OK; empty key → clean one-line error.
- Export stage: mock label → both Excel files verified, then mock removed.
- User added mid-session: .env.example, .gitignore, git commit, push to GitHub.
- git init (main), initial commit, pushed to private repo github.com/adoistic/stem-diagrams. .env/data/.venv excluded via .gitignore.
- User supplied real API keys + goal "get at least a few dozen diagrams, save to external hard disk." Saved keys to .env, found the external drive "/Volumes/One Touch" (4TB), pointed DATA_DIR there.
- Real run: 42 papers (7/field × 6 fields) → detect (72 diagram pages / 248 analyzed) → OCR (143 images) → label (141 labeled) → export (141-row Excel ×2).
- Found xiaomi/mimo-v2.5-pro is text-only on OpenRouter (goal literally cannot work with the exact model named) — switched to sibling xiaomi/mimo-v2.5 (multimodal), documented why in .env comment.
- Hit + fixed two full-stage crashes from the same root cause (ExFAT/USB external drive transient I/O under sustained load) — hardened every unprotected file read across run_pipeline.py. Also fixed reasoning-model-returns-null-content and improved JSON parsing leniency.
- Final deliverables on the external drive: /Volumes/One Touch/stem_diagrams_data/output/{labels_with_source.xlsx, labels_without_source.xlsx, diagram_images/} (141 diagrams each).
- DONE. Pipeline is reusable — `python run_pipeline.py` with .env keys filled continues scaling the dataset (idempotent/resumable).
