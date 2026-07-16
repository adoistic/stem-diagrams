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
## Session 3 — 2026-07-16 evening: build + test everything locally (goal: production decision)
- research/fable_ml_method.md written (agentic-ML working rules, gold-annotation instrument protocol w/ dual raters + adjudication).
- ml/ scaffolding: py3.12 venv (torch 2.13 MPS OK, timm 1.0.28, transformers 5.14, doclayout_yolo OK). RUBRIC.md v1.0 frozen (policy: annotated photos OUT, phase maps OUT, schematic-dominant composites IN).
- Datasets frozen (assemble_dataset.py, seed 20260716, sha 241a5c791341c6e3): 956 papers 669/144/143; crops diagram 2000/data_plot 589/photo 21/fragment 667; pages 12,266 (~21% pos). Photo class too small → binary is primary metric, 4-class diagnostic.
- Core scripts by Fable: common.py, probe_experiments.py, zero_shot.py, heuristics_baseline.py, finetune.py, detector_eval.py, evaluate.py (only test-reader, bootstrap+McNemar).
- Sonnet leaf scripts: render_pages.py (12,226 pages rendered, 0 failed), extract_embeddings.py (4 backbones incl ungated DINOv3), bench_latency.py (heuristic 5.3ms; efficientnet_b0 27.8ms MPS p50).
- GOLD SETS DONE. Crops: 200, dual-Sonnet raters κ=0.925 (4cls)/0.940 (binary), 9 disagreements Fable-adjudicated, RUBRIC v1.1 (band-diagram clarification). Pages: 120, κ=0.798, 10 adjudicated. **Gold vs silver: 24.5% binary disagreement (crops), 20% (pages) — the LLM pipeline itself scores ~75-80% vs strict rubric; that's the bar local models must beat on gold.**
- Ladder so far (VAL, vs silver): A heuristics 77.5% acc/F1 .835 · B zero-shot siglip2 74.3% (negative result — below floor) · C probe siglip2+MLP **85.8% acc / F1 .887** (logreg 82.8%) · D finetune efficientnet_b0 73-78% F1 .778 (NEGATIVE: full fine-tune loses to frozen probes on 2.2k noisy labels, 14 min MPS) · E detector + C-remaining-backbones running.
- Ops notes: HF stale .lock files after killed process → infinite hang (cleared, HF_HUB_OFFLINE=1); torch-MPS wedges on this extraction workload (518px big batches) though finetune ran fine — descoped extraction+detector to CPU per time-box rule.
- Next phase researched (no code yet): research/classifier_research.md — distillation plan to replace LLM gates with local models (DocLayout-YOLO for pages/extraction, SigLIP2/DINOv3 embedding probes for crops, cascade+abstention), full eval protocol (paper-level splits, gold set, McNemar, latency benchmarks), laptop-first.
