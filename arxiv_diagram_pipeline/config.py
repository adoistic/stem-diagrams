"""Central configuration for the arXiv diagram pipeline."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "xiaomi/mimo-v2.5-pro")
# Cheap fast model that pre-screens every page; OPENROUTER_MODEL then confirms
# only its positives (bake-off 2026-07-16: 92% agreement, 15x cheaper, 7x
# faster than mimo; mimo confirmation keeps the final gate quality unchanged).
SCREEN_MODEL = os.getenv("SCREEN_MODEL", "bytedance-seed/seed-1.6-flash")
MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"
MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

DATA_DIR = Path(os.getenv("DATA_DIR", "").strip() or (PROJECT_ROOT / "data"))
PAPERS_DIR = DATA_DIR / "papers"
OUTPUT_DIR = DATA_DIR / "output"

RENDER_DPI = 110          # resolution for page renders sent to the LLM / OCR
JPEG_QUALITY = 80
ARXIV_DELAY_SECONDS = 3.0  # politeness delay between arXiv requests
PAPERS_PER_FIELD = 5       # default; override with --papers-per-field
OCR_CONTEXT_CHARS = 4000   # max OCR text passed as page context when labeling

# ---- v2 (parallel, SQLite-state) pipeline ----
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "16"))            # concurrent OpenRouter calls
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "2"))     # concurrent Mistral batch calls
OCR_BATCH_PAGES = int(os.getenv("OCR_BATCH_PAGES", "50"))    # diagram pages per combined PDF
OCR_BATCH_MAX_MB = 20   # split bigger batches (base64 inflates 33%; Mistral cap 50MB)
TARGET_DIAGRAMS = int(os.getenv("TARGET_DIAGRAMS", "30000"))
MAX_PAGES_PER_PAPER = int(os.getenv("MAX_PAGES_PER_PAPER", "20"))
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low")      # low|medium|high|none
DOWNLOAD_BACKLOG_PAGES = 3000   # downloader pauses when this many pages await detection

STATE_DB = PROJECT_ROOT / "state.db"
LOG_DIR = PROJECT_ROOT / "logs"
PAPERS_V2_DIR = DATA_DIR / "papers_v2"
OCR_BATCHES_DIR = DATA_DIR / "ocr_batches"
IMAGES_V2_DIR = DATA_DIR / "images_v2"
REJECTS_V2_DIR = DATA_DIR / "images_rejected_v2"
OUTPUT_V2_DIR = DATA_DIR / "output_v2"

# arXiv has no direct taxonomy for these six fields, so each one maps to a
# category + keyword search query against the arXiv API.
FIELDS = {
    "semiconductor_engineering": {
        "name": "Semiconductor Engineering",
        "query": (
            "(cat:cond-mat.mes-hall OR cat:physics.app-ph OR cat:eess.SP) AND "
            '(abs:semiconductor OR abs:transistor OR abs:"integrated circuit" '
            'OR abs:"chip design" OR abs:lithography)'
        ),
    },
    "manufacturing_engineering": {
        "name": "Manufacturing Engineering",
        "query": (
            "(cat:eess.SY OR cat:physics.app-ph OR cat:cs.CE) AND "
            '(abs:manufacturing OR abs:"additive manufacturing" OR abs:machining '
            'OR abs:"production line" OR abs:"process control")'
        ),
    },
    "robotics_automation": {
        "name": "Robotics & Automation",
        "query": "cat:cs.RO",
    },
    "utilities_power_systems": {
        "name": "Utilities & Power Systems",
        "query": (
            "cat:eess.SY AND "
            '(abs:"power system" OR abs:"power grid" OR abs:"smart grid" '
            'OR abs:microgrid OR abs:"distribution network" OR abs:"transmission line")'
        ),
    },
    "aerospace_engineering": {
        "name": "Aerospace Engineering",
        "query": (
            "(cat:eess.SY OR cat:cs.RO OR cat:physics.flu-dyn) AND "
            "(abs:aerospace OR abs:aircraft OR abs:spacecraft OR abs:UAV "
            "OR abs:satellite OR abs:aerodynamics)"
        ),
    },
    "telecommunications": {
        "name": "Telecommunications",
        "query": (
            "(cat:eess.SP OR cat:cs.NI OR cat:cs.IT) AND "
            '(abs:wireless OR abs:"communication system" OR abs:5G OR abs:6G '
            'OR abs:antenna OR abs:"optical fiber")'
        ),
    },
}
