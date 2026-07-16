# Labeling Rubric — v1.0 (2026-07-16)

Four classes. Every crop gets exactly one. "Accept" for the production gate
means class = DIAGRAM; everything else is rejected. Gold labels cite clauses
(e.g. "D2", "P1") so decisions are auditable.

## DIAGRAM (accept)

- **D1** Structural/technical drawings whose content is *drawn*, not measured:
  block diagrams, circuit schematics, flowcharts, state machines, control
  loops, signal-flow graphs, network topologies, system architectures,
  mechanical/technical drawings, kinematic sketches, cross-section schematics,
  band diagrams, ontology/relationship graphs, timelines with structured
  annotation.
- **D2** Annotated experimental-setup **illustrations**: drawn/rendered
  depictions of apparatus, devices, or scenes with labeled components
  (includes 3D renders of setups).
- **D3** Composite multi-panel figures where DIAGRAM panels dominate (>50% of
  area, judged visually). A schematic with a small inset plot is DIAGRAM; a
  plot grid with one small schematic inset is DATA_PLOT.

## DATA_PLOT (reject)

- **P1** Measured/computed data renderings: line/bar/scatter plots, heatmaps,
  colormaps, spectrograms, histograms, box plots — with or without
  annotations. Annotations do not promote a plot to a diagram.
- **P2** Phase/stability/parameter-space maps (computed regions in a
  quantitative axis space).
- **P3** Result-trajectory visualizations: paths/curves plotted over maps,
  maze layouts, or 3D scenes where the *content* is an experimental result.

## PHOTO (reject)

- **H1** Photographs and micrographs (SEM/TEM/optical), even with letter
  labels or arrows. Annotation does not promote a photo to a diagram.
- **H2** Exception → DIAGRAM: only when drawn schematic content dominates the
  photo (e.g. a faint background photo under a dense drawn overlay).

## FRAGMENT_JUNK (reject)

- **F1** Blank/near-blank crops; unreadable or too-small content.
- **F2** Slivers of larger figures: lone axes, legends, caption strips,
  single arrows/boxes without context, cut-off partial diagrams.
- **F3** Logos, decorative elements, equations, tables, pseudocode blocks.

## Tie-breaking

- Judge by *dominant purpose*: does the image primarily communicate structure
  (DIAGRAM) or measured values (DATA_PLOT) or appearance (PHOTO)?
- If genuinely 50/50 after that: composites → D3 rule by area; else prefer the
  reject class (the production gate is precision-first).
- Gold annotator records `uncertain: true` on any tie-broken item; those are
  also reported as a separate slice in evaluation.

## Version history
- v1.1 (2026-07-16, post-adjudication clarification): "band diagrams" in D1
  means *drawn* energy-level/band-alignment schematics. Computed band
  structures (E–k curves) and computed parameter-space/theory colormaps are
  DATA_PLOT (P2). Rendered measured/simulated data (point clouds, MD
  snapshots) are DATA_PLOT (P3), not photos.
- v1.0 (2026-07-16): initial. Policy decisions: annotated experiment photos
  are PHOTO (out); phase/stability maps are DATA_PLOT (out); trajectory result
  maps are DATA_PLOT (out); schematic-dominant composites are DIAGRAM (in).
  Rationale: Adnan's stated intent is "proper diagrams", precision-first.
