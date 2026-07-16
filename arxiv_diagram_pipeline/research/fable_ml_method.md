# Fable as the ML Engineer — Working Method for the Classifier Program

*How the model driving this repo (Claude Fable 5, in Claude Code) prompts and
disciplines itself through an applied ML program. Written before the code, as
requested, so the process is auditable against what actually happened.*

## Why this needs a method at all

Agentic ML work fails in characteristic ways — different from human failure
modes: silently optimistic results (evaluating on leaked data), abandoning a
debuggable approach for a rewrite, forgetting negative results and repeating
them, and "benchmark theater" (reporting the best of many peeks at the test
set). The recent literature on ML-engineering agents (MLE-bench; AIDE's
tree-search-over-solutions framing; AIRA's operator+search-policy decoupling)
converges on the same counter-measures we adopt here: strict artifact-based
state, small verifiable increments with ablation-style refinement, and
separation of exploration from evaluation.

## The seven working rules for this program

1. **Everything on disk, nothing in vibes.** Every experiment writes a JSON
   result row (`ml/results/*.json`: config, git hash, data manifest hash,
   metrics, latency, timestamp, notes) plus one line in `ml/RESULTS.md`. The
   conversation is not the record; the repo is. This doubles as the agent's
   long-term memory across context windows (the "progress file" pattern from
   long-running-agent practice).
2. **Frozen splits before any model.** The split manifest (paper-level,
   seeded) is generated once, committed, and its SHA recorded in every result
   row. The test split is read by exactly one script (`evaluate.py`), run at
   the end per model family — never during development. Validation is for
   iteration; test is for the paper.
3. **Gold before silver claims.** Headline metrics only against the
   hand-verified gold set. Fable is the annotator, so annotator discipline
   applies (below). Silver-agreement (fidelity to the LLM pipeline) is
   reported separately and never called "accuracy".
4. **Ladder, don't leap.** Approaches run in ascending capability order
   (heuristics → zero-shot → probes → fine-tune → detector), and each rung
   must beat the previous on validation to justify its complexity — the
   ablation-driven, component-at-a-time refinement that outperforms
   whole-pipeline rewrites in agent ML studies. Negative results get logged
   with the same care as positive ones.
5. **Delegate the mechanical, keep the judgment.** Sonnet subagents write
   well-specified leaf scripts (data loaders, plotting, boilerplate) with
   verification commands included in the spec; Fable designs the experiments,
   reads the confusion matrices, adjudicates gold labels, and writes the
   analysis. (Same policy that built the v2 pipeline.)
6. **Verify before claiming.** No result enters RESULTS.md without the actual
   command output in the transcript. If a number looks too good, the first
   hypothesis is leakage, the second is a metric bug; both get checked before
   celebration (paper-level split integrity is asserted by script, not by
   reading code).
7. **Time-boxed debugging, then descope.** Any component that resists two
   focused fix attempts gets simplified or dropped (documented), not
   heroically rescued. The goal is a production decision, not completeness.

## Fable as gold-set annotator — the instrument protocol

Using the same model as annotator and analyst risks circularity, so the gold
labeling is treated as a measurement instrument with known reliability, per
current LLM-annotation practice:

- **Rubric first**: a written, versioned rubric (in `ml/RUBRIC.md`) defining
  diagram vs data-plot vs photo vs fragment, with the borderline policy made
  explicit *before* labeling. Labels cite rubric clauses, not taste.
- **Blind to model outputs**: gold labeling happens from the image alone
  (+ rubric); classifier predictions and the original LLM verdicts are not
  shown during annotation, so gold cannot inherit their errors.
- **Test-retest reliability**: ~15% of gold items get re-labeled later in a
  shuffled order; self-agreement (Cohen's κ) is reported in the paper. κ<0.8
  would invalidate the instrument and force a rubric revision.
- **Second rater**: a Sonnet subagent independently labels the same 15%
  slice with the same rubric; disagreements are adjudicated by Fable with
  written justifications. Inter-rater κ is reported alongside.
- **Provenance**: every gold label stores who/when/rubric-version.

## Self-prompting structure (how the session actually runs)

- **Task DB + planning files** carry the plan; each experiment is a task with
  an explicit done-condition ("result row written and verified").
- Each experiment follows the same prompt-to-self template, kept short:
  *goal → exact command(s) → expected artifact → verification → interpretation
  written to RESULTS.md*. If interpretation changes the plan, the plan file is
  edited in the same turn (so a context reset cannot lose the decision).
- **Checkpoint cadence**: after every rung of the ladder, a one-paragraph
  status lands in progress.md (what ran, headline validation number, next).
- **No unbounded loops**: training scripts run as background tasks with
  Monitors watching for completion/NaN/OOM signatures; polling is forbidden.

## Compute discipline (laptop-first)

- Embeddings computed once per backbone and cached (`ml/cache/`); all probe
  experiments reuse the cache. Fine-tunes use MPS with fixed seeds and
  deterministic dataloader ordering where the backend allows.
- Every latency number reports: device (MPS/CPU), batch size, warmup policy,
  p50/p95, and machine identity — measured, not estimated.
- Nothing in the program requires Colab; if a config would (it shouldn't at
  our scale), it gets descoped rather than outsourced — per the project's
  reduce-external-dependencies constraint.

## Sources
- [MLE-bench overview](https://www.emergentmind.com/topics/mle-bench) · [AI research agents on MLE-bench (AIRA)](https://arxiv.org/html/2507.02554v2) — search-policy/operator decoupling, ablation-driven refinement
- [Anthropic: how Claude Code is used in practice](https://www.anthropic.com/research/claude-code-expertise) · [Long-running Claude for scientific computing](https://www.anthropic.com/research/long-running-Claude) — progress-file memory, verification loops
- [Inter-prompt reliability of LLM annotation](https://arxiv.org/pdf/2604.16413) · [LLM annotation in management research](https://faculty.wharton.upenn.edu/wp-content/uploads/2025/09/The-use-of-LLMs-to-Annotate-Data.pdf) — instrument-reliability framing, κ protocols
