"""Parse CSV/Excel sheets and bulk-create Entity List (hierarchy) rows."""

from __future__ import annotations

import csv
import io
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from typing import Any, Iterable, Literal

from sqlmodel import Session, select

from app.models.tables import AppDefinitions, Hierarchy
from app.services.app_definitions_service import (
    DEFAULT_APP_DEFINITIONS,
    entity_label,
)
from app.services.entity_list_service import ENTITY_LIST_LEVELS
from app.services.hierarchy_service import get_next_hierarchy_id, sync_hierarchy_id_sequence

NAME_HEADERS = frozenset({"entity name", "entity_name", "name", "entity"})
TYPE_HEADERS = frozenset(
    {
        "entity type",
        "entity_type",
        "type",
        "hierarchy_type",
        "hierarchy type",
        "category",
    }
)
ABBR_HEADERS = frozenset(
    {"abbreviation", "acronym", "abbr", "acronym / abbreviation"}
)

def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(parent) if _local_tag(child.tag) == name]


def _descendants(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent.iter() if child is not parent and _local_tag(child.tag) == name]


def _child_text(parent: ET.Element, name: str) -> str:
    for child in _descendants(parent, name):
        if child.text:
            return child.text
    return ""


class EntityListImportError(ValueError):
    def __init__(self, message: str, *, errors: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


def _normalize_header(value: str) -> str:
    return " ".join(value.replace("_", " ").strip().lower().split())


def _cell_col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return max(n - 1, 0)


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in _descendants(root, "si"):
        texts = [t.text or "" for t in _descendants(si, "t")]
        values.append("".join(texts))
    return values


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        raw = _child_text(cell, "v")
        try:
            return shared[int(raw)]
        except (TypeError, ValueError, IndexError):
            return ""
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in _descendants(cell, "t"))
    return _child_text(cell, "v").strip()


def parse_xlsx_rows(content: bytes) -> list[list[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise EntityListImportError("File is not a valid Excel workbook (.xlsx).") from exc

    sheet_name = next(
        (name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")),
        None,
    )
    if not sheet_name:
        raise EntityListImportError("Excel file has no worksheet.")

    shared = _shared_strings(zf)
    root = ET.fromstring(zf.read(sheet_name))
    matrix: list[list[str]] = []
    sheet_data = next(iter(_descendants(root, "sheetData")), None)
    rows = _children(sheet_data, "row") if sheet_data is not None else []
    for row in rows:
        cells = _children(row, "c")
        if not cells:
            continue
        width = 0
        values: dict[int, str] = {}
        for cell in cells:
            idx = _cell_col_index(cell.attrib.get("r", "A"))
            values[idx] = _cell_text(cell, shared).strip()
            width = max(width, idx + 1)
        matrix.append([values.get(i, "") for i in range(width)])
    return matrix


def parse_csv_rows(content: bytes) -> list[list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    sample = text.lstrip()
    if not sample:
        raise EntityListImportError("File is empty.")
    dialect = csv.excel
    try:
        dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;\t")
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(text), dialect)
    return [[(cell or "").strip() for cell in row] for row in reader]


def _rows_to_dicts(matrix: list[list[str]]) -> list[dict[str, str]]:
    if not matrix:
        raise EntityListImportError("File is empty.")
    header_idx = next((i for i, row in enumerate(matrix) if any(cell.strip() for cell in row)), None)
    if header_idx is None:
        raise EntityListImportError("File is empty.")
    headers = [_normalize_header(cell) for cell in matrix[header_idx]]
    records: list[dict[str, str]] = []
    for row in matrix[header_idx + 1 :]:
        if not any((cell or "").strip() for cell in row):
            continue
        record: dict[str, str] = {}
        for i, header in enumerate(headers):
            if not header:
                continue
            record[header] = row[i].strip() if i < len(row) else ""
        records.append(record)
    return records


def parse_entity_list_file(content: bytes, filename: str) -> list[dict[str, str]]:
    name = (filename or "").lower().strip()
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        raise EntityListImportError(
            "Old .xls Excel format is not supported. Save the file as .xlsx or .csv and try again."
        )
    if name.endswith(".xlsx") or (content[:2] == b"PK" and not name.endswith(".csv")):
        matrix = parse_xlsx_rows(content)
    else:
        matrix = parse_csv_rows(content)
    return _rows_to_dicts(matrix)


def _pick_field(row: dict[str, str], aliases: Iterable[str]) -> str:
    wanted = set(aliases)
    for key, value in row.items():
        if _normalize_header(key) in wanted:
            return (value or "").strip()
    return ""


def build_type_aliases(definitions: AppDefinitions | None = None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    extras = {
        "system": ("systems", "sys"),
        "subsystem": ("subsystems", "sub"),
        "module": ("modules", "mod"),
        "unit": ("units",),
        "component": ("components", "comp"),
    }
    for level in ENTITY_LIST_LEVELS:
        aliases[level] = level
        for extra in extras.get(level, ()):
            aliases[extra] = level
        labels = [
            DEFAULT_APP_DEFINITIONS.get(f"label_{level}", level),
            DEFAULT_APP_DEFINITIONS.get(f"label_{level}s", f"{level}s"),
        ]
        if definitions is not None:
            labels.append(entity_label(definitions, level))
            labels.append(entity_label(definitions, level, plural=True))
        for label in labels:
            if label:
                aliases[_normalize_header(str(label))] = level
    return aliases


def resolve_entity_type(raw: str, aliases: dict[str, str]) -> str | None:
    key = _normalize_header(raw)
    return aliases.get(key)


def _required_columns(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise EntityListImportError("File has a header row but no data rows.")
    keys = {_normalize_header(k) for k in rows[0].keys()}
    has_name = bool(keys & NAME_HEADERS)
    has_type = bool(keys & TYPE_HEADERS)
    missing: list[str] = []
    if not has_name:
        missing.append("entity name")
    if not has_type:
        missing.append("entity type")
    if missing:
        raise EntityListImportError(
            "File is missing required columns: "
            + ", ".join(missing)
            + ". Expected headers like 'Entity Name' and 'Entity Type'."
        )


def import_entity_list_rows(
    session: Session,
    rows: list[dict[str, str]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    _required_columns(rows)
    definitions = session.exec(select(AppDefinitions).limit(1)).first()
    aliases = build_type_aliases(definitions)

    existing = list(session.exec(select(Hierarchy)).all())
    seen = {
        (entry.name.strip().lower(), (entry.hierarchy_type or "").strip().lower())
        for entry in existing
    }

    errors: list[dict] = []
    payloads: list[dict[str, Any]] = []
    skipped = 0

    for index, row in enumerate(rows, start=2):
        name = _pick_field(row, NAME_HEADERS)
        type_raw = _pick_field(row, TYPE_HEADERS)
        abbreviation = _pick_field(row, ABBR_HEADERS)
        row_errors: list[str] = []

        if not name and not type_raw:
            continue
        if not name:
            row_errors.append("'entity name' is required")
        if not type_raw:
            row_errors.append("'entity type' is required")

        hierarchy_type = resolve_entity_type(type_raw, aliases) if type_raw else None
        if type_raw and hierarchy_type is None:
            allowed = ", ".join(sorted(ENTITY_LIST_LEVELS))
            row_errors.append(f"'entity type' must be one of: {allowed}")

        if row_errors:
            errors.append({"row": index, "errors": row_errors})
            continue

        assert hierarchy_type is not None
        key = (name.lower(), hierarchy_type)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        payloads.append(
            {
                "name": name,
                "hierarchy_type": hierarchy_type,
                "abbreviation": abbreviation.upper() if abbreviation else None,
                "parent_id": None,
            }
        )

    if errors:
        raise EntityListImportError(
            "File contains validation errors",
            errors=errors,
        )

    if dry_run:
        return {
            "dry_run": True,
            "valid_rows": len(payloads),
            "skipped": skipped,
            "errors": [],
        }

    created: list[dict[str, Any]] = []
    if payloads:
        next_id = get_next_hierarchy_id(session)
        db_entries: list[Hierarchy] = []
        for payload in payloads:
            entry = Hierarchy(**payload)
            entry.id = next_id
            next_id += 1
            db_entries.append(entry)
        session.add_all(db_entries)
        session.flush()
        sync_hierarchy_id_sequence(session)
        session.commit()
        for entry in db_entries:
            session.refresh(entry)
            created.append(
                {
                    "id": entry.id,
                    "name": entry.name,
                    "hierarchy_type": entry.hierarchy_type,
                }
            )

    return {
        "imported": len(created),
        "skipped": skipped,
        "rows": created,
        "errors": [],
    }


EXPORT_HEADERS = ["entity_name", "entity_type", "abbreviation"]
ExportFormat = Literal["csv", "xlsx"]


def _col_letter(index: int) -> str:
    n = index + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters or "A"


def build_xlsx(rows: list[list[str]]) -> bytes:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_rows: list[str] = []
    for r_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for c_idx, value in enumerate(row):
            text = xml_escape(str(value or ""), {'"': "&quot;"})
            cells.append(
                f'<c r="{_col_letter(c_idx)}{r_idx}" t="inlineStr"><is><t>{text}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{ns}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{ns}">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def build_entity_list_csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def entity_list_export_matrix(session: Session) -> list[list[str]]:
    entries = list(
        session.exec(
            select(Hierarchy).order_by(Hierarchy.hierarchy_type, Hierarchy.name)
        ).all()
    )
    matrix: list[list[str]] = [list(EXPORT_HEADERS)]
    for entry in entries:
        matrix.append(
            [
                entry.name or "",
                (entry.hierarchy_type or "").strip().lower(),
                entry.abbreviation or "",
            ]
        )
    return matrix


def export_entity_list_file(
    session: Session, file_format: ExportFormat
) -> tuple[bytes, str, str]:
    matrix = entity_list_export_matrix(session)
    if file_format == "xlsx":
        return (
            build_xlsx(matrix),
            "entity-list.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return (
        build_entity_list_csv(matrix),
        "entity-list.csv",
        "text/csv",
    )
