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
    reply = openrouter_client.chat(messages, max_tokens=4500)
    result = openrouter_client.extract_json(reply)
    result.setdefault("diagram_type", "")
    result.setdefault("title", "")
    result.setdefault("label", "")
    return result
