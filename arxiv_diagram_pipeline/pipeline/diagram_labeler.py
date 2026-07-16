"""Send extracted diagram images back to the LLM for a detailed labeling."""

from pipeline import openrouter_client
from pipeline.page_renderer import to_data_uri

LABEL_PROMPT = """\
You are labeling a diagram image that was extracted from page {page} of the
academic paper "{title}" (field: {field}).

PAGE CONTEXT (OCR text of the page the diagram appears on):
---
{page_text}
---

DIAGRAM CONTEXT (from an earlier analysis of the full page):
{diagram_context}

Study the attached diagram image carefully and write a good, DETAILED labeling
of the diagram. Cover every labeled component, the connections and
relationships between components, any annotations, symbols, axes or values,
and what the diagram as a whole illustrates in the context of the paper.

Respond with ONLY a JSON object, no other text:
{{
  "diagram_type": "<short type, e.g. 'block diagram', 'circuit schematic'>",
  "title": "<one-line title for the diagram>",
  "label": "<the detailed labeling: one or more paragraphs covering components, connections, annotations and purpose>"
}}
"""


CLASSIFY_LABEL_PROMPT = """\
You are curating a dataset of PROPER TECHNICAL DIAGRAMS from academic papers.
The attached image was automatically cropped from page {page} of the paper
"{title}" (field: {field}) — automatic cropping produces many bad images, so
your FIRST job is strict quality control, and only then labeling.

PAGE CONTEXT (OCR text of the page the image came from):
---
{page_text}
---

DIAGRAM CONTEXT (from an earlier analysis of the full page):
{diagram_context}

STEP 1 — Decide if this image is a proper, usable technical diagram.
ACCEPT only if it is a complete, legible diagram such as: a block diagram,
system architecture, flowchart, circuit schematic, network topology,
signal-flow graph, mechanical/technical drawing, control loop, state machine,
annotated experimental-setup illustration, or similar.
REJECT if it is any of these:
- blank or near-blank, or too small/blurry to read
- a fragment or sliver of a figure (cut-off diagram, a lone axis, a legend,
  a caption strip, a single arrow or box without context)
- a pure data plot (line/bar/scatter chart, heatmap, spectrogram) with no
  structural/architectural annotation
- a table, pure text block, equation, algorithm pseudocode
- a photograph without technical annotation, a logo, page decoration
- multiple unrelated sub-figures mashed together illegibly

STEP 2 — Only if accepted, write a good, DETAILED labeling of the diagram:
cover every labeled component, the connections and relationships between
components, any annotations, symbols, axes or values, and what the diagram
as a whole illustrates in the context of the paper.

Respond with ONLY a JSON object, no other text:
{{
  "is_diagram": true or false,
  "reject_reason": "<if rejected: short reason, e.g. 'data plot', 'fragment', 'blank'; else empty string>",
  "diagram_type": "<if accepted: short type, e.g. 'block diagram', 'circuit schematic'; else empty string>",
  "title": "<if accepted: one-line title for the diagram; else empty string>",
  "label": "<if accepted: the detailed labeling, one or more paragraphs; else empty string>"
}}
"""


def classify_and_label(image_path, page_number, paper_title, field_name,
                       page_text, diagram_context):
    """v2: strict accept/reject classification plus labeling in one call.
    Returns (result_dict, cost_usd)."""
    prompt = CLASSIFY_LABEL_PROMPT.format(
        page=page_number,
        title=paper_title,
        field=field_name,
        page_text=page_text.strip() or "(no OCR text available)",
        diagram_context=diagram_context.strip() or "(none)",
    )
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": to_data_uri(image_path)}},
        ],
    }]
    reply, cost = openrouter_client.chat_with_meta(messages)
    result = openrouter_client.extract_json(reply)
    result.setdefault("is_diagram", False)
    result.setdefault("reject_reason", "")
    result.setdefault("diagram_type", "")
    result.setdefault("title", "")
    result.setdefault("label", "")
    return result, cost


def label(image_path, page_number, paper_title, field_name, page_text, diagram_context):
    prompt = LABEL_PROMPT.format(
        page=page_number,
        title=paper_title,
        field=field_name,
        page_text=page_text.strip() or "(no OCR text available)",
        diagram_context=diagram_context.strip() or "(none)",
    )
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": to_data_uri(image_path)}},
        ],
    }]
    reply = openrouter_client.chat(messages)
    result = openrouter_client.extract_json(reply)
    result.setdefault("diagram_type", "")
    result.setdefault("title", "")
    result.setdefault("label", "")
    return result
