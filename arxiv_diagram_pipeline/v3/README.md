# v3 — deterministic diagram harvester (no Mistral, no paid API)

v3 replaces the paid pieces of the extraction pipeline with local, deterministic
ones. It downloads arXiv PDFs, extracts figure candidates geometrically, keeps
the ones the local classifier calls a proper diagram, and streams everything to
R2. The laptop only ever holds the current working set.

## How it avoids Mistral

Figure extraction is deterministic (`extract.py`), three geometric signals:
1. **embedded images** (`page.get_images`) — raster/exported figures, pulled at
   original quality. Most "vector-looking" arXiv diagrams are actually embedded
   images, so this alone catches the majority.
2. **vector-path clustering** (`page.get_drawings`) — native TikZ/PGF line art.
3. **caption anchoring** (`page.get_text`) — validates and rescues.

The **gate** (`gate.py`) is the study's winner: frozen SigLIP2 + logistic
regression (`gate_logreg.pkl`), keeping only `class == diagram`. No OCR, no LLM.

## Run

```bash
cd arxiv_diagram_pipeline
HF_HUB_OFFLINE=1 ml/.venv/bin/python v3/run_v3.py --target 10000
```

Uses `ml/.venv` (torch + transformers + PyMuPDF + requests). Resumable — rerun
the same command to continue. State in `v3/v3_state.db`; progress in
`v3/logs/v3.log`.

## Output (R2 bucket `stem-diagrams-dataset`, prefix `v3/`)

- `v3/images/batch_NNNNN.zip` — accepted diagram PNGs (500/batch)
- `v3/pdfs/batch_NNNNN.zip` — source PDFs (120/batch)
- `v3/manifest.csv` — image → arxiv_id, field, page, method, bbox, p_diagram, batch

## Rebuild the gate

`gate_logreg.pkl` is regenerable from the study's cached embeddings:
`ml/.venv/bin/python v3/train_gate.py` (needs `ml/cache/siglip2_crops_manifest.npz`,
produced by `ml/extract_embeddings.py`).
