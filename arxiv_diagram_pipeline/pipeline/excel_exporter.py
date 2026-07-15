"""Write the two Excel outputs: with-source and without-source."""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

# (header, row key, column width)
WITH_SOURCE_COLUMNS = [
    ("Field", "field", 26),
    ("ArXiv ID", "arxiv_id", 16),
    ("Paper Title", "paper_title", 50),
    ("Authors", "authors", 40),
    ("Published", "published", 12),
    ("Abstract URL", "abs_url", 34),
    ("PDF URL", "pdf_url", 34),
    ("Page", "page_number", 7),
    ("Source Image Path", "source_image_path", 55),
    ("Image File", "image_file", 24),
    ("Diagram Type", "diagram_type", 22),
    ("Diagram Title", "diagram_title", 40),
    ("Label", "label", 110),
]

WITHOUT_SOURCE_COLUMNS = [
    ("Field", "field", 26),
    ("Image File", "image_file", 24),
    ("Diagram Type", "diagram_type", 22),
    ("Diagram Title", "diagram_title", 40),
    ("Label", "label", 110),
]


def _write(rows, columns, dest_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Diagram Labels"
    for col, (header, _key, width) in enumerate(columns, start=1):
        ws.cell(row=1, column=col, value=header).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(col)].width = width
    wrap = Alignment(wrap_text=True, vertical="top")
    for r, row in enumerate(rows, start=2):
        for c, (_header, key, _w) in enumerate(columns, start=1):
            cell = ws.cell(row=r, column=c, value=row.get(key, ""))
            cell.alignment = wrap
    ws.freeze_panes = "A2"
    wb.save(dest_path)


def export(rows, output_dir):
    """Write both workbooks; returns their paths."""
    with_path = output_dir / "labels_with_source.xlsx"
    without_path = output_dir / "labels_without_source.xlsx"
    _write(rows, WITH_SOURCE_COLUMNS, with_path)
    _write(rows, WITHOUT_SOURCE_COLUMNS, without_path)
    return with_path, without_path
