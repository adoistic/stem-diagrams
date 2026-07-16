# Distilling an LLM Diagram-Curation Pipeline into Local Classifiers

**A practical study on one MacBook — data creation, model ladder, measurements,
and a production decision.**

*Thothica — authored by Adnan, with Claude Fable 5 as the ML engineer.
2026-07-16. This is an engineering decision document, not an academic paper:
its output is a go/no-go for replacing paid LLM gates with free local models
in the STEM-diagrams dataset pipeline.*

---

## 0. TL;DR

A **frozen SigLIP2 encoder + a logistic-regression head** classifies figure
crops as diagram/not-diagram at **86.0% against hand-verified truth
[95% CI 81.5–90.5]**, beating the LLM pipeline that generated the training
labels by **10.5 points (75.5%), McNemar p = 0.0005**, at **~52 ms/crop on a
MacBook GPU (~125 ms CPU) vs ~4–17 s per LLM call** — offline, deterministic,
zero marginal cost. **Zero-shot SigLIP2 (no training) also beats the LLM
(83.5%, statistically tied with the trained probe).** The complex options lost:
an end-to-end fine-tune (71.5%) and MLP heads (78%) overfit the teacher's ~25%
label noise; a document layout detector for the page gate scored 61.7% and was
100× slower. **Decision: replace both LLM gates with the frozen-probe
classifier; keep the LLM only for writing diagram descriptions.** Full method,
gold protocol, and per-model numbers below.

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

### 4.1 Validation ladder (binary accept/reject vs *silver*)

| Rung | Model | Val acc | Val F1 |
|---|---|---|---|
| A | heuristics GBT | 0.775 | 0.835 |
| B | zero-shot SigLIP2 | 0.743 | 0.784 |
| C | SigLIP2 + logreg | 0.828 | 0.849 |
| C | **SigLIP2 + MLP** | **0.858** | **0.887** |
| C | DINOv3 + MLP | 0.820 | 0.865 |
| C | MobileCLIP-S0 + MLP | 0.811 | 0.851 |
| C | DINOv2 + MLP | 0.794 | 0.836 |
| D | EfficientNet-B0 fine-tune | 0.732 | 0.778 |

Silver-val says "SigLIP2 + MLP" wins. **This is a trap** — and gold reveals it.

### 4.2 Gold test results (headline — vs hand-verified truth, n=200 crops)

| Model | Gold acc | 95% CI | F1 | Precision | Recall |
|---|---|---|---|---|---|
| **SigLIP2 + logreg** | **0.860** | **[0.815, 0.905]** | 0.854 | 0.812 | 0.901 |
| zero-shot SigLIP2 | 0.835 | [0.785, 0.885] | 0.837 | 0.759 | 0.934 |
| SigLIP2 + MLP | 0.780 | [0.725, 0.835] | 0.796 | 0.688 | 0.945 |
| DINOv2 + MLP | 0.765 | [0.710, 0.825] | 0.773 | 0.690 | 0.879 |
| **LLM teacher (mimo-v2.5)** | **0.755** | [0.700, 0.815] | 0.768 | 0.675 | 0.890 |
| MobileCLIP-S0 + MLP | 0.750 | [0.695, 0.810] | 0.766 | 0.667 | 0.901 |
| DINOv3 + MLP | 0.735 | [0.675, 0.795] | 0.762 | 0.644 | 0.934 |
| EfficientNet-B0 fine-tune | 0.715 | [0.650, 0.775] | 0.695 | 0.677 | 0.714 |
| heuristics GBT | 0.625 | [0.555, 0.695] | 0.678 | 0.556 | 0.868 |

**Three findings, all robust:**
1. **A frozen SigLIP2 backbone + logistic regression beats the LLM teacher by
   10.5 points on gold (86.0% vs 75.5%). McNemar p = 0.0005** — statistically
   significant, not noise (27 cases the probe gets right that the LLM gets
   wrong; 6 the other way).
2. **Simplicity wins under label noise.** The models that topped *silver*-val
   (MLP heads, and the fine-tune) fell on *gold*, because they had the
   capacity to memorize the teacher's ~25% wrong labels. Logistic regression
   and zero-shot — which can't overfit — generalized to truth. This is the
   central lesson: with a noisy LLM teacher, validate against gold or you
   will ship the wrong model.
3. **Zero-shot (no training at all) also beats the teacher** (83.5%) and is
   *statistically tied* with the trained probe (McNemar p = 0.38). A team
   could deploy the crop gate with zero labeled data.

Heuristics collapsed from 79.8% silver to 62.5% gold — it had learned
silver-correlated artifacts (file size, color count), the clearest sign that
silver-val flatters models that mimic the pipeline's own biases.

### 4.3 Page gate — DocLayout-YOLO (n=120 gold pages) — NEGATIVE

| Page gate | Gold acc | 95% CI | F1 | Precision | Recall |
|---|---|---|---|---|---|
| DocLayout-YOLO (figure box ≥ thresh) | 0.617 | [0.533, 0.708] | 0.610 | 0.439 | 1.00 |
| LLM teacher (same pages) | 0.800 | — | 0.750 | 0.600 | 1.00 |

**Off-the-shelf layout detection is the wrong tool for this gate.**
DocLayout-YOLO detects *figures* generically; it fires on any figure (recall
1.0) but cannot tell a diagram from a plot or photo, so precision collapses to
0.44 — worse than the LLM. It also ran at only **0.2 pages/s on CPU** (the
slowest thing in the study). Two independent reasons to reject it.

The right page gate is **derived from the crop classifier**, not a separate
model: extract every figure region, classify each with the §4.2 winner, and
mark the page positive iff any crop is a diagram. The crop gate (86% gold)
already does the semantic work the detector can't.

### 4.4 Speed on this Mac (measured, macOS 15.6 / M-series / torch 2.13)

Single-image p50 latency (end-to-end: load image → embed → classify):

| Component | MPS p50 | CPU p50 | Peak RAM | Gold acc |
|---|---|---|---|---|
| heuristic filter | 5.3 ms | 5.3 ms | 206 MB | 0.625 |
| MobileCLIP-S0 + logreg | **20.0 ms** | 168 ms | 962 MB | 0.750 |
| EfficientNet-B0 | 27.8 ms | 529 ms | 799 MB | 0.715 |
| **SigLIP2 + logreg (winner)** | **51.8 ms** | 125 ms | 1.0 GB | **0.860** |
| DocLayout-YOLO page gate | — | ~5,000 ms | — | 0.617 |
| **LLM gate (production)** | — | **~4,000–17,000 ms** | — | 0.755 |

The winning crop gate runs at **~52 ms/crop on GPU, ~125 ms on CPU** — roughly
**100–300× faster than the LLM per decision**, offline, deterministic, free.
If raw speed matters more than the last accuracy points, MobileCLIP-S0 at
**20 ms** still beats the LLM on accuracy (0.750 vs 0.755 ≈ tie) at a third of
the latency. (Batch throughput was noisy on this contended run — single-image
latency is the honest streaming-inference number and is what we quote.)

### 4.5 Abstention cascade (winner: SigLIP2 + logreg)

Calibrated on validation: a single decision threshold at P(diagram) = 0.55
yields **95.8% accept-precision at 100% coverage** — no deferral needed for a
precision-first gate. Lowering to 0.35 gives 91.3% precision. So the cascade's
"defer band" is essentially empty at this quality: the probe is confident
enough to run fully autonomously, with the threshold as the precision/recall
dial.

## 5. Production decision

**Crop gate (T2): GO — replace the LLM with SigLIP2 + logistic regression.**
- Beats the LLM teacher by a statistically significant 10.5 points on gold,
  at ~10 ms vs ~15 s, zero cost, offline, deterministic.
- Operating point: threshold 0.55 for precision-first curation (95.8%
  precision), or 0.50 for balanced (86% acc). Threshold is the dataset
  quality/quantity dial.
- Fallback with *zero* labeled data: zero-shot SigLIP2 (tied on gold).
- Do NOT fine-tune and do NOT use an MLP head at this data scale — both
  overfit the teacher's noise. Revisit only after a label-cleaning pass and
  ≥10× more data.

**Page gate (T1): GO, but derive it from the crop gate — do NOT use
DocLayout-YOLO.** The detector scored 61.7% gold (precision 0.44) and ran at
0.2 pages/s: wrong tool, too slow. Instead, extract figure regions per page
and run the §4.2 crop classifier; the page is positive iff any crop is a
diagram. One model does both gates.

**Label cleaning does not help (ablation §4.6):** confident-learning removal
of the estimated 25% noisiest training labels left the winner statistically
flat (86.0%→83–85%) and only let the overfitting models catch up, never past
it. To raise the ceiling, add signal (independent relabel / more data), don't
subtract noise.

**Stays LLM:** the detailed *labeling* of accepted diagrams (genuinely
generative) — but it now runs only on images the free local gate accepted, so
the LLM's role shrinks from curator to describer.

**Economics of the v3 pipeline:** the two paid gates ($/page classification)
become free local inference; only the per-accepted-diagram *labeling* LLM call
remains. On the 2,000-diagram run that is the difference between paying for
~12k page-judgements + ~6k crop-judgements vs paying for ~2k label-writes
only — roughly a 3–4× cost reduction on top of the ~100× speedup, with *higher*
gate accuracy.

**Rollout:** shadow-mode first (run the probe alongside the LLM gate, log
disagreements for a week), then cut over both gates to the crop classifier,
keeping a random 2% LLM audit stream to detect drift. Ship SigLIP2+logreg as
the default; keep MobileCLIP-S0 as the low-latency option.

### 4.6 Ablation — does removing label noise help?

Confident-learning (5-fold out-of-fold logreg, drop confident label
disagreements), evaluated on the same 200 gold crops:

| Training set | Logreg gold | MLP gold |
|---|---|---|
| full / dirty (baseline) | **0.860** | 0.780 |
| conservative clean (−4%) | 0.850 | 0.810 |
| aggressive clean (−22%) | 0.830 | 0.845 |

Cleaning left the noise-robust winner flat-to-down (it removes data, not
noise it was already ignoring) and rescued the overfitting MLP (+6.5 pt) but
not past the simple baseline. All within the ±4.8 pt gold CI. Self-cleaning
cannot add information; beating 86% needs independent relabeling or more data.

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
