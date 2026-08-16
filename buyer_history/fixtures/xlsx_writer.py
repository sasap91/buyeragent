"""Minimal .xlsx writer, used only to build the synthetic fixture.

Writes the smallest workbook the reader in `buyer_history.xlsx` accepts: inline
strings (no shared string table), no styles, no formulas. Stdlib only, to keep
the fixture reproducible on a bare Python install.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    "{sheet_overrides}"
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell(row: int, column: int, value: object) -> str:
    ref = f"{_column_name(column)}{row}"
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{_escape(str(value))}</t></is></c>'


def _sheet_xml(rows: list[list[object]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(_cell(row_index, i, v) for i, v in enumerate(row))
        parts.append(f'<row r="{row_index}">{cells}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def write_workbook(path: str | Path, sheets: dict[str, list[list[object]]]) -> Path:
    """Write {sheet name: rows} to an .xlsx file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    names = list(sheets)
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(names) + 1)
    )

    workbook_sheets = "".join(
        f'<sheet name="{_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(names, start=1)
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{workbook_sheets}</sheets>"
        "</workbook>"
    )

    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(names) + 1)
        )
        + "</Relationships>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES.format(sheet_overrides=overrides))
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for i, name in enumerate(names, start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheets[name]))

    return path
