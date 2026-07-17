# STEM Diagrams: an LLM diagram-curation pipeline, distilled into local classifiers

**A frozen SigLIP2 encoder with a small logistic-regression head tells diagrams
from not-diagrams at 86.0% against hand-checked truth. That beats the vision-LLM
that labeled its own training data by 10.5 points (McNemar p = 0.0005), at
about 52 ms per crop on a laptop, offline and free.**

📄 **[Read the paper (PDF)](arxiv_diagram_pipeline/paper/paper.pdf)** ·
🌐 **[Project site](https://adoistic.github.io/stem-diagrams/)** ·
📦 **[Download the dataset (2,000 diagrams)](https://pub-4b177d3c9b154dfeb08296540e8242ee.r2.dev/stem-diagrams-v1.zip)**

---

This repo contains two things:

1. **The extraction pipeline** (`arxiv_diagram_pipeline/`) — downloads arXiv
   papers in six engineering fields, uses vision-LLMs to find and label proper
   technical diagrams (block diagrams, schematics, flowcharts, architectures —
   not plots, photos, or fragments), and exports a labeled dataset. Parallel,
   resumable (SQLite state; survives credit exhaustion and hard shutdowns),
   quality-filtered. It produced **2,000 labeled diagrams from 1,183 papers for
   \$20.36**.

2. **The ML study** (`arxiv_diagram_pipeline/ml/`) — asks whether the pipeline's
   paid LLM classification gates can be replaced by free local models. They
   can, decisively. Full method, gold-labeling protocol, model ladder, and
   production decision are in [`PAPER.md`](arxiv_diagram_pipeline/PAPER.md) and
   the [PDF](arxiv_diagram_pipeline/paper/paper.pdf).

## Headline results (hand-verified gold set, n=200)

| Model | Gold accuracy | Speed | Cost |
|---|---|---|---|
| **SigLIP2 + logistic regression** | **86.0%** [81.5–90.5] | ~52 ms | free |
| Zero-shot SigLIP2 (no training) | 83.5% | ~52 ms | free |
| LLM teacher (mimo-v2.5) | 75.5% | ~4–17 s | paid |
| EfficientNet-B0 fine-tune | 71.5% | ~28 ms | free |

The simple frozen-feature probe wins; fine-tuning and MLP heads *lose* because
they overfit the teacher's ~25% label noise. See the paper for why, and for the
methodological lesson (validate on gold, not on LLM labels).

## Repository layout

```
arxiv_diagram_pipeline/
├── pipeline/            extraction pipeline modules
├── run_pipeline_v2.py   parallel, resumable orchestrator
├── status_v2.py         live progress dashboard
├── ml/                  the classifier study
│   ├── assemble_dataset.py, extract_embeddings.py, probe_experiments.py,
│   ├── finetune.py, detector_eval.py, cascade.py, evaluate.py, make_figures.py
│   ├── RUBRIC.md         the 4-class labeling rubric (frozen policy)
│   ├── data/             frozen splits + gold labels
│   └── results/          per-experiment JSON + figures
├── research/            method + approach research docs
├── paper/               arXiv LaTeX source (paper.tex) + figures
├── docs/                GitHub Pages site
└── PAPER.md             the full writeup
```

## Quickstart — reproduce the ML result

```bash
cd arxiv_diagram_pipeline/ml
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python assemble_dataset.py                        # frozen paper-level splits
python extract_embeddings.py --backbone siglip2   # cache embeddings (once)
python probe_experiments.py --backbones siglip2   # train probes (seconds)
python evaluate.py --gold probe_siglip2_logreg    # headline vs gold
```

## Run the extraction pipeline

```bash
cd arxiv_diagram_pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # add OPENROUTER_API_KEY and MISTRAL_API_KEY
python run_pipeline_v2.py --target 2000
```

## License

Code: MIT. Dataset labels & metadata: CC BY 4.0. Diagram images are figures
from arXiv papers under their original licenses (source `arxiv_id` retained per
record). See [LICENSE](LICENSE).

## Citation

```bibtex
@misc{abbasi2026stemdiagrams,
  title  = {Distilling an LLM Diagram-Curation Pipeline into Local Classifiers},
  author = {Adnan Abbasi},
  year   = {2026},
  note   = {Thothica. https://github.com/adoistic/stem-diagrams}
}
```

By [Adnan Abbasi](https://github.com/adoistic), founder of Thothica.
