"""Dependency-free .xlsx reader.

An .xlsx file is a zip of XML parts, so the standard library is enough. Keeping
this here avoids adding pandas/openpyxl just to read one fixture workbook.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELS_DOC = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Excel's day 1 is 1900-01-01, but it wrongly treats 1900 as a leap year, so the
# effective epoch for every date after 1900-02-28 is 1899-12-30.
EXCEL_EPOCH = date(1899, 12, 30)

_COL_RE = re.compile(r"([A-Z]+)")


def excel_serial_to_date(value: str | float | int | None) -> date | None:
    """Convert an Excel date serial to a real date. Returns None if not a serial."""
    if value is None or value == "":
        return None
    try:
        serial = float(value)
    except (TypeError, ValueError):
        return None
    if serial <= 0:
        return None
    return EXCEL_EPOCH + timedelta(days=int(serial))


def _column_index(cell_ref: str) -> int:
    match = _COL_RE.match(cell_ref)
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in si.iter(f"{MAIN}t"))
        for si in root.findall(f"{MAIN}si")
    ]


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return [(sheet_name, zip_part_path)] in workbook order."""
    rels: dict[str, str] = {}
    for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")):
        rels[rel.get("Id", "")] = rel.get("Target", "")

    sheets: list[tuple[str, str]] = []
    for sheet in ET.fromstring(archive.read("xl/workbook.xml")).iter(f"{MAIN}sheet"):
        target = rels.get(sheet.get(f"{RELS_DOC}id", ""), "")
        if not target:
            continue
        # Targets may be absolute ("/xl/worksheets/sheet1.xml") or workbook-relative.
        part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        sheets.append((sheet.get("name", ""), part))
    return sheets


def read_workbook(path: str | Path) -> dict[str, list[list[str]]]:
    """Read every sheet into a list of rows of cell strings."""
    archive = zipfile.ZipFile(Path(path))
    strings = _shared_strings(archive)
    workbook: dict[str, list[list[str]]] = {}

    for name, part in _sheet_targets(archive):
        if part not in archive.namelist():
            continue
        rows: list[list[str]] = []
        for row in ET.fromstring(archive.read(part)).iter(f"{MAIN}row"):
            cells: dict[int, str] = {}
            for cell in row.findall(f"{MAIN}c"):
                ref = cell.get("r") or ""
                kind = cell.get("t")
                value_node = cell.find(f"{MAIN}v")
                if kind == "inlineStr":
                    text = "".join(n.text or "" for n in cell.iter(f"{MAIN}t"))
                elif value_node is None:
                    text = ""
                elif kind == "s":
                    text = strings[int(value_node.text or 0)]
                else:
                    text = value_node.text or ""
                if ref:
                    cells[_column_index(ref)] = text.strip()
            if any(cells.values()):
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        workbook[name] = rows

    return workbook


def sheet_records(rows: list[list[str]], header_row: int = 0) -> list[dict[str, str]]:
    """Turn a sheet's rows into dicts keyed by the header row."""
    if len(rows) <= header_row:
        return []
    header = [name.strip() for name in rows[header_row]]
    records: list[dict[str, str]] = []
    for row in rows[header_row + 1 :]:
        record = {
            header[i]: (row[i] if i < len(row) else "")
            for i in range(len(header))
            if header[i]
        }
        if any(value for value in record.values()):
            records.append(record)
    return records


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default
