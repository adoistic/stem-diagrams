# Replacing the LLM Gates with Local Classifiers — Research & Experiment Plan

*Prepared 2026-07-16, ahead of any code. Companion to the v2 extraction pipeline.*
*Constraints set by Adnan: market on **accuracy** and **speed**, not cost (it should
cost ~nothing to run); must run on a laptop (Apple Silicon Mac); Colab/Kaggle
acceptable as fallback for training only, not ideal.*

---

## 1. Problem framing

The v2 pipeline uses LLM calls for three decisions. Only the first two are
classification (replaceable by local deterministic models); the third is
generative and stays with an LLM:

| Task | Today | Candidate replacement |
|------|-------|----------------------|
| **T1 — page gate**: does this rendered page contain a diagram? | seed-1.6-flash screen + mimo-v2.5 confirm (~4–17 s/page, API) | local page classifier or layout detector (~10–60 ms/page) |
| **T2 — crop gate**: is this extracted image a proper technical diagram (vs plot/fragment/photo/blank)? | mimo classify step inside classify_and_label | local image classifier (~5–20 ms/image) |
| **T3 — figure localization** (currently implicit): where on the page is the figure? | Mistral OCR extracts embedded images ($4/1k pages) | document layout detector crops figures directly (free) |
| labeling (generative description) | mimo-v2.5 | **stays LLM** — only runs on accepted diagrams |

T3 is the sleeper: a layout detector that finds figure bounding boxes on the
rendered page replaces both T1 (page has a figure ⇔ detector fires) *and* the
Mistral extraction step — the largest remaining cost line — while giving us
crops for T2. Worth treating as a first-class approach, not an afterthought.

**Speed target for marketing:** ≥50 pages/sec page-gating and ≥100 crops/sec
classification on a MacBook (batch), vs ~4–17 s *per page* today via API.
That is a 3–4 orders-of-magnitude speedup story. Zero marginal cost.

---

## 2. Training data we already have (from `state.db`, 2026-07-16)

The v2 pipeline saved every decision, so the dataset already exists:

### T2 (crop-level) — images on disk, labels in DB
- **Positives: 1,969 accepted diagrams** (`images_v2/`), with detailed labels
- **Semantic negatives: ~685 LLM-rejected crops** (`images_rejected_v2/`), with
  reasons — data plot (~509), fragment (~28), photograph (~16), blurry (~3), …
- **Trivial negatives: ~3,122 local-filter rejects** (tiny-file/tiny-dims) —
  mostly sub-8KB fragments; useful as easy negatives but rule-based filtering
  already handles them at runtime; do NOT let them dominate training
- Field spread of positives: aerospace 436, manufacturing 409, utilities 395,
  semiconductor 381, telecom 258, robotics 90 (robotics underrepresented —
  watch per-field metrics)

### T1 (page-level) — labels in DB, pages re-renderable from stored PDFs
- **12,118 judged pages: 2,522 diagram / 9,596 non-diagram** (~21% positive)
- Every page can be re-rendered deterministically (PyMuPDF, same DPI as prod)

### 712 distinct papers with accepted images → paper-level splits are feasible.

### Label quality caveats (from the 24-image hand audit)
- ~8% of accepted images are clear false accepts (pure data plots, barely
  annotated photos); ~20% are borderline (annotated experiment photos,
  phase/stability maps, trajectory maps)
- These are **silver labels** (LLM teacher). Plan: (a) run the $2 strict
  audit pass over all accepted images before training; (b) build a **gold
  test set** by hand: ~300 crops (~150 accepted + 150 rejected, stratified by
  reject reason and field) + ~200 pages, visually verified by Fable (the 24
  already done count toward this). All headline accuracy numbers get reported
  against gold, with silver-agreement as a secondary metric.
- Optional: run confident-learning (cleanlab) over training labels to flag
  probable label errors for re-audit.

---

## 3. Approach families

For each: mechanism, expected accuracy, laptop latency, training effort, tools.
Expected-accuracy priors are anchored by the closest public benchmark:
EfficientNet-B3 reaches ~95% on DocFigure (33K figures, 28 classes — a *harder*
task than our binary/4-class gate), and classic FC+FV-CNN got 92.9% back in
2019. Our tasks should land at or above these bands.

### A. Rule-based heuristics (baseline floor, already partially built)
- Signals: PyMuPDF graphics-object counts (already used as prod pre-filter),
  vector-ink ratio, embedded-image area ratio, file size, dimensions, aspect,
  color histogram entropy, text-block coverage.
- Train: none, or a tiny decision tree over the signals. Latency: ~1–5 ms.
- Expected: T1 recall high / precision poor alone (~70s accuracy); valuable as
  stage-0 skip and as an ablation baseline every learned model must beat.
- Tools: PyMuPDF, PIL, scikit-learn (if tree).

### B. Zero-shot VLM-embedding classification (no training at all)
- CLIP-family text prompts ("a block diagram", "a line chart", "a photo of
  equipment", …) scored against image embedding; argmax or threshold.
- Models: SigLIP 2, MetaCLIP 2, MobileCLIP2 (fastest), OpenCLIP ViT-B.
- Expected: 80–90% on T2 (diagram-vs-plot is a known CLIP strength; chart-type
  zero-shot literature supports this); T1 on full pages weaker (~75–85%) —
  pages are text-dominated, CLIP is object-centric.
- Latency: 5–20 ms/crop on MPS (MobileCLIP2: 3–15 ms class latency).
- Value: instant baseline; also the embedding backbone for C at zero extra cost.

### C. Frozen embeddings + shallow head  ⭐ primary T2 recommendation
- Extract embeddings once (SigLIP 2 / DINOv3 / MobileCLIP2), train logistic
  regression / small MLP / kNN on top. Minutes to train **on CPU**; the whole
  experiment loop (5 backbones × 4 heads × CV) runs in an afternoon.
- Public linear-probe rankings (ImageNet): PECore 89.3 > SigLIP2 89.1 >
  DINOv3 88.4 > DINOv2 87.3 — all viable; test 2–3, pick empirically.
- Expected: **92–97% on T2 gold** with ~1.4k train positives; T1 on page
  renders 85–93%.
- Latency: dominated by embedding: ~5–20 ms/img MPS (ViT-B class), ~3–8 ms
  for MobileCLIP2-S; head is microseconds. Batch throughput: 100–500 img/s.
- Deployment: backbone via timm/transformers on MPS, or Core ML/ONNX export;
  head is a 100KB sklearn/numpy artifact.
- Bonus: same embeddings give near-duplicate detection + a similarity search
  index over the dataset for free.

### D. Fine-tuned small CNN/ViT (accuracy ceiling for T1/T2)
- Fine-tune MobileNetV4 / EfficientNet-B0→B3 / FastViT / ConvNeXt-Tiny
  end-to-end on our crops (T2) or page renders (T1).
- Evidence: EfficientNet-B3 ≈95% on 28-class DocFigure ⇒ binary/4-class on
  cleaner labels should exceed that. Expected: **95–98% T2**, 90–95% T1.
- Train: 15–60 min on M-series MPS (timm, 224–384px, ~5k images); Colab T4
  as fallback for bigger sweeps. Latency: 5–15 ms/img MPS; exportable to
  Core ML (ANE) for another 2–5x.
- Risk: overfitting to silver-label noise → clean labels first (audit pass),
  strong augmentation, early stopping on gold-val.

### E. Document layout detector  ⭐ primary T1/T3 recommendation
- Run DocLayout-YOLO (YOLOv10-based, DocSynth-300K pretrained, real-time,
  beats DINO-4scale/LayoutLMv3 on DocStructBench) or PP-DocLayout / Surya on
  rendered pages: figure boxes out. Page gate = "any figure box ≥ area
  threshold"; crops feed T2; Mistral no longer needed for extraction.
- Expected out-of-box: figure-class detection is these models' bread and
  butter on academic PDFs (trained heavily on arXiv-style docs); mAP@50 for
  the figure class typically ~0.9+. Our T1 accuracy via detector likely
  88–95% before any fine-tuning; fine-tuning on ~500 hand-checked pages
  (annotation cheap: boxes already suggested by the model) pushes higher.
- Latency: ~20–60 ms/page (YOLOv10-scale on MPS/CPU).
- Note: replaces OCR *image extraction*, not OCR *text* — page text for label
  context can come from PyMuPDF `get_text()` (free, and arXiv PDFs are born-
  digital so text layer is exact; Mistral OCR adds nothing there).
- Tools: `doclayout-yolo` (GitHub opendatalab), ultralytics-style API; or
  `surya` / PaddleOCR PP-DocLayout.

### F. Small local VLM as judge (abstention-band fallback)
- Qwen3-VL 2B/4B, Moondream, or MobileVLM via MLX / Ollama / llama.cpp on the
  Mac. 0.3–2 s/image — too slow as the main gate, right as the *fallback* for
  the 5–10% of cases where C/D/E are uncertain.
- Keeps the whole pipeline local (no API even for edge cases); the cloud LLM
  then only ever writes labels for accepted diagrams.

### G. Cascade + abstention (the production shape)
- Stage 0: heuristics (A) — instant skips.
- Stage 1: detector (E) for pages / classifier (C or D) for crops with two
  thresholds: accept ≥ τ_hi, reject ≤ τ_lo, defer in between.
- Stage 2: deferred band → local VLM (F) or cloud LLM.
- Calibrate τ on validation (temperature scaling first) to hit a target
  precision at max coverage; report coverage-vs-accuracy curve. Conformal
  prediction (split-conformal on val scores) gives distribution-free
  guarantees if we want a stronger marketing claim ("≥97% precision at 93%
  automation, guaranteed on exchangeable data").

---

## 4. Recommendation matrix

| Task | First try | Backup | Ceiling |
|------|-----------|--------|---------|
| T1 page gate | **E: DocLayout-YOLO out-of-box** | C on page renders | E fine-tuned, or D on pages |
| T2 crop gate | **C: SigLIP2/DINOv3 + logistic head** | B zero-shot | D fine-tuned EfficientNet/FastViT |
| T3 extraction | **E boxes → crops** | keep Mistral | E fine-tuned |
| Uncertain cases | **G abstention → F local VLM** | cloud LLM | — |

Class design for T2: don't train binary. Train **4-way: diagram / data-plot /
photo-or-micrograph / fragment-or-junk** (labels already exist via reject
reasons), then map to accept/reject. Multi-class heads learn cleaner
boundaries and the confusion matrix directly explains failures. The
"borderline" categories from the audit (annotated photos, phase maps) should
become an explicit **policy decision** encoded in the gold labels — decide
once whether each is in or out, document it, and the classifier inherits a
consistent rule (unlike the LLM, which wobbles).

---

## 5. Evaluation protocol

### 5.1 Splits
- **Paper-level** 70/15/15 (train/val/test), stratified by field. No paper's
  images/pages straddle splits (style leakage otherwise inflates results).
- Freeze the test split in a committed JSON manifest before any training.
- Robotics has only 90 positives — report per-field but flag its wide CIs;
  optionally harvest more robotics papers before the freeze.

### 5.2 Gold labels
- ~300 crops + ~200 pages hand-verified (Fable visual audit; 24 done).
  Gold overrides silver wherever they conflict. All *headline* metrics on gold.
- Encode the borderline policy in a one-page rubric (what counts as a
  diagram) so future annotation is consistent.

### 5.3 Metrics
- **Primary (marketing): accuracy + macro-F1 on gold test**, per task.
- Precision/recall per class, PR-AUC (positives ~21% at page level — PR beats
  ROC under imbalance), confusion matrices, per-field breakdown.
- Calibration: reliability diagram + ECE (needed for honest abstention).
- Abstention: coverage-vs-accuracy curve; headline variant "X% accuracy at
  Y% automation".
- Uncertainty: bootstrap 95% CIs on all headline numbers; **McNemar's test**
  for pairwise model comparisons on the same test set (n≈300–500 → detects
  ~4–5 pt differences; treat smaller gaps as ties).
- Silver-agreement (vs LLM pipeline decisions) as secondary: shows fidelity
  to the current system separately from correctness.

### 5.4 Speed benchmarks (the second marketing axis)
- Report on the actual MacBook: single-image latency (p50/p95), batch
  throughput (img/s at batch 32/128), model load time, peak RAM.
- Backends compared: PyTorch MPS vs Core ML (ANE) vs ONNX Runtime CPU.
- End-to-end replay: run the full v3 gate over one real paper set and report
  pages/min vs the v2 API pipeline's measured ~4–17 s/page. Target headline:
  "~1000× faster page gating on a laptop, at equal-or-better accuracy."

### 5.5 Robustness checks
- Leave-one-field-out generalization (train on 5 fields, test the 6th).
- Render-DPI sensitivity (90/110/150) for T1/E.
- Hard-negative slice: data plots that the LLM initially accepted (the audit's
  false-accept examples) — the exact failure mode we're fixing; track it as
  its own metric slice.

---

## 6. Compute plan (laptop-first, as required)

| Step | Where | Time |
|------|-------|------|
| Embedding extraction (≈6k crops + 12k pages) | Mac MPS | ~10–30 min once, cached to disk |
| C heads (all sweeps) | Mac CPU | minutes |
| B zero-shot | Mac MPS | minutes |
| E detector inference (12k pages) | Mac MPS/CPU | ~10–20 min |
| D fine-tunes | Mac MPS 15–60 min each; **Colab T4 only if sweeping >5 configs** | — |
| E fine-tune (optional) | Colab T4 (~1–2 h) — the one genuinely GPU-hungry item | — |
| F local VLM | Mac via MLX/Ollama | interactive |

Nothing requires Kaggle; Colab only as an optional accelerator. Inference —
the thing we market — is 100% laptop.

## 7. Risks / open questions
1. **Silver-label noise** is the top risk to both training and honest claims
   → audit pass + gold set are prerequisites, not nice-to-haves.
2. Borderline-category policy must be decided *before* gold labeling
   (annotated experiment photos: in or out? phase maps: out, per Adnan's
   "proper diagrams" intent — confirm).
3. DocLayout-YOLO box conventions (multi-panel figures → one box or many?)
   need a quick empirical look; affects T2 crop distribution vs Mistral crops
   (domain shift between training crops and detector crops — mitigate by
   generating detector crops for training too).
4. Robotics field is data-poor; harvest top-up before freeze.
5. Page render DPI in training must match production DPI.

## 8. Next-session checklist (code session)
1. Strict audit pass over 1,969 accepted (existing pipeline, ~$2.5).
2. Data assembly script: dump crops+labels+splits manifest from `state.db`
   (paper-level split, stratified; seed fixed).
3. Gold-set annotation batch (Fable visual audit queue: 300 crops, 200 pages).
4. Baselines in order: A → B → C (3 backbones × logistic/MLP) → E out-of-box
   → D (one EfficientNet-B0 + one FastViT) → G calibration.
5. Benchmark harness: metrics + latency, one `results.md` leaderboard.

## Sources
- [DocLayout-YOLO paper](https://arxiv.org/abs/2410.12628) · [GitHub](https://github.com/opendatalab/DocLayout-YOLO) · [PP-DocLayout](https://arxiv.org/pdf/2503.17213)
- [DINOv3 (Meta)](https://github.com/facebookresearch/dinov3) · [linear-probe comparison incl. SigLIP2/PECore](https://www.deeplearning.ai/the-batch/metas-dinov3-gets-an-updated-loss-term-and-improved-vision-performance)
- [DocFigure dataset](https://cvit.iiit.ac.in/usodi/Docfig.php) · [EfficientNet-B3 ~95% on DocFigure](https://www.researchgate.net/publication/399213433_Chart_Classification_of_DocFigure_Dataset_using_VGG-16_and_EfficientNet-B3) · [figure-classification survey](https://arxiv.org/html/2307.05694)
- [MobileCLIP (Apple)](https://machinelearning.apple.com/research/mobileclip) · [FastVLM/FastViT](https://machinelearning.apple.com/research/fast-vision-language-models)
- [ACL-Fig dataset](https://www.researchgate.net/publication/367557593_ACL-Fig_A_Dataset_for_Scientific_Figure_Classification)
