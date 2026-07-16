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

## Session 2 (same day) — v2 scale-up to 30k
- Built run_pipeline_v2.py per new goal: SQLite state, 20 parallel OpenRouter calls, batched Mistral OCR (manifest maps combined-PDF page → paper+page), two-layer quality filter, in-memory rasterization. Sonnet subagents wrote image_filter / search_paginated / export_v2+status_v2; Fable wrote state machine, orchestrator, prompts, batcher.
- User rule added to ~/.claude/CLAUDE.md: never pass max_tokens to LLM APIs (removed everywhere).
- Integration test: 12-diagram target hit end-to-end in 5.5 min; SIGKILL mid-run → clean resume (WAL); JSON LaTeX-escape repair fixed the 2 recurring label failures; local filter rejected 77 junk images pre-LLM (verified correct on samples).
- Committed 9976841, pushed. PRODUCTION RUN LAUNCHED ~13:55 nohup pid 8362, target 30000. At launch+3min: 79 labeled, 5620 papers registered, $0.81. ETA ~2.3 days. Monitor armed for FATAL/credits/completion. Resume = rerun same command.
- 429 incident (arXiv rate-limit misread as supply exhaustion) → fixed (thread-safe throttle, 429 backoff, buffer harvest), c37fce4.
- Cost review (Adnan): mimo-v2.5-pro measured $0.00106/detect; Mistral OCR verified $4/1k pages (dominant cost). Bake-off → seed-1.6-flash screens (15x cheaper, 7x faster, 92% agree), mimo confirms+labels. Local graphics pre-filter (30% pages free-skipped). db373d0. Target cut 30k→5k→1.6k→2k as credits/needs evolved. Credit exhaustion mid-run handled cleanly (402 → clean stop, zombie-exit fixed via os._exit, LaTeX \escape corruption fixed, Excel control-char sanitizer), 517a2ac.
- **EXTRACTION COMPLETE 2026-07-16 17:20: 2,000 labeled diagrams, 3,868 rejected, 1,183 papers, $20.36 total ($10.39 OpenRouter + $9.97 Mistral).** Exports + 2,000 flat images in output_v2/. Audit sample: ~75% solid, ~20% borderline, ~8% clear false accepts.
- Next phase researched (no code yet): research/classifier_research.md — distillation plan to replace LLM gates with local models (DocLayout-YOLO for pages/extraction, SigLIP2/DINOv3 embedding probes for crops, cascade+abstention), full eval protocol (paper-level splits, gold set, McNemar, latency benchmarks), laptop-first.
