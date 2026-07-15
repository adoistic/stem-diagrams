# arXiv Diagram Extraction & Labeling Pipeline

Downloads recent arXiv papers in six engineering fields, finds the pages that
contain diagrams using **OpenRouter (`xiaomi/mimo-v2.5-pro`)**, runs
**Mistral OCR** on those pages to extract the diagram images, sends each image
back to the LLM (with page + diagram context) for a **detailed labeling**, and
exports everything to two Excel files — one with the diagram's source, one
without. Both contain the label.

## Fields

| Key | Field |
|-----|-------|
| `semiconductor_engineering` | Semiconductor Engineering |
| `manufacturing_engineering` | Manufacturing Engineering |
| `robotics_automation` | Robotics & Automation |
| `utilities_power_systems` | Utilities & Power Systems |
| `aerospace_engineering` | Aerospace Engineering |
| `telecommunications` | Telecommunications |

arXiv has no exact taxonomy for these fields, so each maps to a category +
keyword query (see `config.py` — tweak freely).

## Setup

```bash
cd arxiv_diagram_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # then fill in your two API keys
```

`.env` keys:

- `OPENROUTER_API_KEY` — for `xiaomi/mimo-v2.5-pro` (diagram detection + labeling)
- `MISTRAL_API_KEY` — for Mistral OCR (page OCR + image extraction)

Optional overrides: `OPENROUTER_MODEL`, `MISTRAL_OCR_MODEL`
(defaults: `xiaomi/mimo-v2.5-pro`, `mistral-ocr-latest`).

## Run

```bash
python run_pipeline.py                          # everything, 5 papers/field
python run_pipeline.py --papers-per-field 2     # smaller test run
python run_pipeline.py --fields robotics_automation --max-pages 8
python run_pipeline.py --stages export          # just rebuild the Excel files
```

Stages run in order and are **resumable** — every step writes its result to
disk and is skipped on re-run if the output already exists. Ctrl-C and re-run
any time.

1. **download** — arXiv API search per field (3 s politeness delay), PDFs +
   `metadata.json` saved per paper. Works without API keys.
2. **detect** — each page rendered to JPEG and sent to `xiaomi/mimo-v2.5-pro`:
   "does this page contain a diagram?" (block diagrams, schematics, flowcharts,
   architectures, technical drawings… — plain tables/plots/photos excluded).
3. **ocr** — Mistral OCR on each diagram page (`include_image_base64=true`);
   the images Mistral extracts are saved to `diagrams/`. If OCR extracts no
   image on a detected page, the full page render is kept as fallback.
4. **label** — each diagram image goes back to the LLM together with the page
   OCR text (page context) and the detection description (diagram context);
   the model returns a detailed labeling (type, title, label paragraphs).
5. **export** — images copied to a flat `output/diagram_images/` folder with
   anonymous names, then two workbooks are written.

## Output structure

```
data/
├── papers/<field>/<arxiv_id>/
│   ├── paper.pdf
│   ├── metadata.json           # title, authors, abstract, URLs
│   ├── pages/page_NNN.jpg      # page renders
│   ├── analysis/page_NNN.json  # LLM diagram detection per page
│   ├── ocr/page_NNN.{json,md}  # Mistral OCR raw response + markdown
│   ├── diagrams/page_NNN_*.…   # images extracted by Mistral OCR
│   └── labels/page_NNN_*.json  # detailed LLM labelings
└── output/
    ├── diagram_images/diagram_0001.jpeg …   # flat anonymous copies
    ├── labels_with_source.xlsx              # + arXiv ID/title/authors/URLs/page/path
    └── labels_without_source.xlsx           # field, image file, type, title, label
```

`labels_without_source.xlsx` references only the anonymized flat image names,
so it carries no trace of which paper a diagram came from.
