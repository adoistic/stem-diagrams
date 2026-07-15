"""Ask the OpenRouter vision model whether a rendered page contains diagrams."""

from pipeline import openrouter_client
from pipeline.page_renderer import to_data_uri

DETECT_PROMPT = """\
You are analyzing page {page} of the academic paper "{title}" (field: {field}).

Look at the page image and decide whether it contains one or more DIAGRAMS.
Count as diagrams: block diagrams, system architectures, flowcharts, circuit
schematics, mechanical/technical drawings, network topologies, signal-flow
graphs, annotated illustrations of equipment or processes, and experimental
setup figures.
Do NOT count: plain tables, pure text, equations, unannotated photographs, or
simple data plots (line/bar/scatter charts) unless they carry structural
annotations that make them diagram-like.

Respond with ONLY a JSON object, no other text:
{{
  "has_diagram": true or false,
  "diagrams": [
    {{"type": "<short diagram type>",
      "description": "<1-3 sentences: what the diagram shows>"}}
  ],
  "page_summary": "<2-3 sentence summary of what this page is about>"
}}
If there are no diagrams, use "diagrams": [].
"""


def detect(page_image_path, page_number, paper_title, field_name):
    prompt = DETECT_PROMPT.format(page=page_number, title=paper_title, field=field_name)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": to_data_uri(page_image_path)}},
        ],
    }]
    reply = openrouter_client.chat(messages)
    result = openrouter_client.extract_json(reply)
    result.setdefault("has_diagram", False)
    result.setdefault("diagrams", [])
    result.setdefault("page_summary", "")
    return result
