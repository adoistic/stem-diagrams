# Distilling an LLM Diagram-Curation Pipeline into Local Classifiers

**A practical study on one MacBook — data creation, model ladder, measurements,
and a production decision.**

*Thothica — authored by Adnan, with Claude Fable 5 as the ML engineer.
2026-07-16. This is an engineering decision document, not an academic paper:
its output is a go/no-go for replacing paid LLM gates with free local models
in the STEM-diagrams dataset pipeline.*

---

## 1. What we built and why

We curate a dataset of *proper technical diagrams* (block diagrams,
schematics, flowcharts, architectures — not data plots, not photos, not
fragments) from arXiv papers in six engineering fields, each image paired
with a detailed LLM-written label. The v2 production pipeline works, but every
page and every crop passes through paid vision-LLM calls:

```
arXiv PDFs → render pages → [LLM: page has diagram?] → batched Mistral OCR
           → figure crops → [LLM: proper diagram? + write label] → dataset
```

The two bracketed gates are classification, not generation. This study asks:
can local models on a laptop replace them at equal-or-better accuracy and
dramatically better speed? (Cost is not the marketing axis — local inference
is effectively free — but for the record the LLM gates cost ~$13/1k pages
processed end-to-end.)

## 2. How the training data was created (full provenance)

### 2.1 The v2 extraction pipeline (teacher)
- 6 arXiv field queries → 1,183 papers downloaded (3s politeness, resumable
  SQLite state, survives SIGKILL/credit exhaustion — both proven in prod).
- Page gate: a cheap screener (`bytedance-seed/seed-1.6-flash`, $0.00024/page,
  4.2s) flags candidate pages; `xiaomi/mimo-v2.5` confirms (bake-off: 92%
  verdict agreement with mimo at 15x lower cost; confirmation keeps mimo's
  gate quality). A free pre-filter skips pages with zero graphics objects
  (30% of pages; 0.4% diagram-page loss, measured).
- Mistral OCR (batched ~25 vector pages/call) extracts figure crops.
- Crop gate + labeling: mimo-v2.5 classify-and-label with strict rejection
  rules (plots/fragments/photos/blanks) plus a free local filter that kills
  tiny/blank crops pre-LLM.
- Yield: **2,000 accepted diagrams** (with labels), 3,868 rejected crops with
  reasons, 12,266 LLM-judged pages. Total spend $20.36; ~19 hours wall-clock
  including all engineering. Exports: two Excel files (with/without source
  attribution) + flat anonymized image folder.

### 2.2 From pipeline exhaust to supervised datasets
Every pipeline decision was journaled in SQLite, so the classifier datasets
are a *byproduct*, not new work:
- **Crops** (4-class silver labels): diagram 2,000 · data_plot 589 · photo 21
  · fragment_junk 667 (LLM reject reasons mapped by rule; trivial local
  rejects capped at 600 so they don't dominate).
- **Pages** (binary silver): 12,266 rendered at production DPI (110), 21%
  positive.
- **Frozen splits**: one paper-level 70/15/15 assignment (seed 20260716,
  stratified by field, 956 papers) shared by both tasks; manifest SHA
  `241a5c791341c6e3` recorded in every result row. No paper straddles splits.

### 2.3 Gold labels (the instrument)
Silver labels are LLM opinions. All headline numbers use **gold** labels
produced under a versioned rubric (`ml/RUBRIC.md` v1.1) with the borderline
policy decided *before* labeling: annotated experiment photos → photo (out);
phase/stability maps and computed colormaps → data_plot (out);
schematic-dominant composites → diagram (in).
- 200 test-split crops + 120 test-split pages, labeled blind by **two
  independent raters** (Claude Sonnet agents; no access to model or pipeline
  outputs), disagreements adjudicated by Fable with written justifications.
- Inter-rater reliability: **κ = 0.925** (crops, 4-class), 0.940 (binary);
  0.798 (pages) before adjudication — an acceptable instrument.
- **Finding: the LLM teacher itself scores only ~75% (crops) / ~80% (pages)
  against the strict rubric** — gold vs silver binary disagreement is 24.5%
  and 20% respectively. The teacher over-accepts annotated plots and photos.
  Consequence: a student can beat its teacher, and "agreement with the LLM"
  ceilings well below 100% are expected and correct.

## 3. Method: the model ladder

Ascending capability, each rung justified only if it beats the previous
(validation, silver). All on an Apple-Silicon MacBook; nothing external.

| Rung | Approach | Implementation |
|---|---|---|
| A | Cheap-signal baseline | 10 image stats → gradient-boosted trees |
| B | Zero-shot VLM | SigLIP2 text prompts vs image embedding |
| C | Frozen embeddings + head | SigLIP2 / DINOv2 / DINOv3 / MobileCLIP-S0 × {logreg, MLP} |
| D | End-to-end fine-tune | EfficientNet-B0 @224, 8 epochs, MPS |
| E | Layout detector page gate | DocLayout-YOLO (DocStructBench weights), threshold swept on val |
| G | Abstention cascade | accept/reject bands on P(diagram), defer the middle |

Working method (self-imposed, see `research/fable_ml_method.md`): frozen
splits before models; test split read by exactly one script at the end;
every experiment writes a JSON row + RESULTS.md line; negative results kept;
mechanical scripts delegated to Sonnet subagents, judgment kept by Fable.

## 4. Results

### 4.1 Validation ladder (binary accept/reject vs silver)

| Rung | Model | Val acc | Val F1 | Note |
|---|---|---|---|---|
| A | heuristics GBT | 0.775 | 0.835 | the floor |
| B | zero-shot SigLIP2 | 0.743 | 0.784 | **negative result** — below floor |
| C | SigLIP2 + logreg | 0.828 | 0.849 | fit in <1s |
| C | SigLIP2 + MLP | **0.858** | **0.887** | fit in 2s |
| C | DINOv2 + MLP | TBD | TBD | |
| C | DINOv3 + MLP | TBD | TBD | |
| C | MobileCLIP-S0 + MLP | TBD | TBD | |
| D | EfficientNet-B0 fine-tune | 0.732 | 0.778 | **negative result** — loses to probes on 2.2k noisy labels (14 min train) |
| E | DocLayout-YOLO page gate | TBD | TBD | pages task |

### 4.2 Gold test results (headline)

TBD: table of accuracy/F1 with bootstrap 95% CIs per model, vs the LLM
pipeline's own gold score; McNemar tests between the top contenders; per-field
slices; the LLM-teacher row for direct comparison.

### 4.3 Speed on this Mac

TBD: p50/p95 single-image and batch throughput (MPS and CPU) for the winning
stack vs the production LLM gates (~4–17 s/page measured); end-to-end
pages/min projection.

### 4.4 Abstention cascade

TBD: coverage vs precision table; the operating point for production.

## 5. Production decision

TBD: go/no-go per gate (page gate, crop gate), chosen operating points,
what stays LLM (labeling of accepted diagrams), expected cost/speed of the
v3 pipeline, and rollout plan (shadow-mode first, then cutover).

## 6. Limitations & honest notes

- Gold n=200 crops / 120 pages → CIs of a few points; McNemar ties below
  ~4-5pt differences.
- The photo class has 21 silver examples (4 in test) — binary is the
  reliable metric; 4-class is diagnostic only.
- Robotics field is under-represented (90 positives).
- Same-model-family risk: gold raters and adjudicator are Claude models, as
  was the teacher; mitigated by rubric-anchored blind rating + κ reporting,
  not eliminated.
- Silver noise (~25%) caps what validation-vs-silver can show; gold is the
  arbiter.
- Ops: torch-MPS wedged on large-batch ViT extraction after killed GPU
  processes (fresh fine-tune ran fine); HF-hub stale lock files hang loads
  after SIGKILL. Both worked around; CPU used where MPS was flaky —
  documented so the numbers are reproducible.

## Appendix A: artifacts
- Code: `ml/` (this repo). Data manifests + gold labels: `ml/data/`.
- Per-experiment JSON: `ml/results/`. Experiment log: `ml/RESULTS.md`.
- Method: `research/fable_ml_method.md`. Plan: `research/classifier_research.md`.
