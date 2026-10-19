from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from cantools.database.can import Database
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .errors import DBCError
from .service import DBCService

FORMAT_NAME = "dbc-skill-excel"
SCHEMA_VERSION = "1"
GENERATOR = "dbc-skill/dbc_crud.py"

METADATA_HEADERS = ("key", "value")
NODE_HEADERS = ("name", "comment")
MESSAGE_HEADERS = (
    "frame_id",
    "is_extended_frame",
    "name",
    "length",
    "senders",
    "is_fd",
    "cycle_time",
    "comment",
)
SIGNAL_HEADERS = (
    "message_frame_id",
    "message_is_extended_frame",
    "name",
    "start",
    "length",
    "byte_order",
    "is_signed",
    "factor",
    "offset",
    "minimum",
    "maximum",
    "unit",
    "receivers",
    "comment",
    "is_multiplexer",
    "multiplexer_signal",
    "multiplexer_ids",
)
CHOICE_HEADERS = (
    "message_frame_id",
    "message_is_extended_frame",
    "signal_name",
    "raw_value",
    "label",
)

_SHEET_HEADERS = (
    ("Metadata", METADATA_HEADERS),
    ("Nodes", NODE_HEADERS),
    ("Messages", MESSAGE_HEADERS),
    ("Signals", SIGNAL_HEADERS),
    ("Choices", CHOICE_HEADERS),
)

_BOOLEAN_FORMULA = '"FALSE,TRUE"'
_BYTE_ORDER_FORMULA = '"little_endian,big_endian"'
_VALIDATION_LAST_ROW = 100000
_FIXED_TIMESTAMP = datetime(2000, 1, 1)

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", start_color="305496", end_color="305496")


def _format_frame_id(frame_id: int) -> str:
    return f"0x{frame_id:X}"


def _format_multiplexer_ids(multiplexer_ids: list[int] | None) -> str | None:
    if multiplexer_ids is None:
        return None
    ordered = sorted(multiplexer_ids)
    parts = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(f"{start}-{previous}" if previous > start else str(start))
        start = previous = value
    parts.append(f"{start}-{previous}" if previous > start else str(start))
    return ",".join(parts)


def _write_rows(sheet, rows) -> None:
    for values in rows:
        row_index = sheet.max_row + 1
        for column_index, value in enumerate(values, start=1):
            if value is None:
                continue
            cell = sheet.cell(row=row_index, column=column_index)
            cell.value = value
            if isinstance(value, str):
                cell.data_type = "s"


def _style_sheet(sheet, headers) -> None:
    for column_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column_index, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(sheet.max_row, 1)}"
    for column_index, header in enumerate(headers, start=1):
        width = len(header)
        for row in sheet.iter_rows(
            min_row=2, min_col=column_index, max_col=column_index
        ):
            value = row[0].value
            if value is not None:
                width = max(width, min(len(str(value)), 60))
        sheet.column_dimensions[get_column_letter(column_index)].width = min(
            width + 2, 62
        )


def _add_list_validation(sheet, header, headers, formula) -> None:
    column = headers.index(header) + 1
    validation = DataValidation(type="list", formula1=formula, allow_blank=True)
    validation.add(f"{get_column_letter(column)}2:{get_column_letter(column)}{_VALIDATION_LAST_ROW}")
    sheet.add_data_validation(validation)


def _metadata_rows(db: Database, snapshot: dict) -> list:
    rows = [
        ("format", FORMAT_NAME),
        ("schema_version", SCHEMA_VERSION),
        ("generator", GENERATOR),
    ]
    if db.version:
        rows.append(("dbc_version", db.version))
    rows.extend(
        [
            ("node_count", len(snapshot["nodes"])),
            ("message_count", len(snapshot["messages"])),
            ("signal_count", len(snapshot["signals"])),
        ]
    )
    return rows


def _build_workbook(db: Database, snapshot: dict) -> Workbook:
    workbook = Workbook()
    workbook.properties.created = _FIXED_TIMESTAMP
    workbook.properties.modified = _FIXED_TIMESTAMP
    sheets = {}
    for index, (name, headers) in enumerate(_SHEET_HEADERS):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        sheet.title = name
        sheets[name] = sheet

    _write_rows(sheets["Metadata"], _metadata_rows(db, snapshot))
    _write_rows(
        sheets["Nodes"],
        ([node["name"], node["comment"]] for node in snapshot["nodes"]),
    )
    _write_rows(
        sheets["Messages"],
        (
            [
                _format_frame_id(message["frame_id"]),
                message["is_extended_frame"],
                message["name"],
                message["length"],
                ",".join(message["senders"]) if message["senders"] else None,
                message["is_fd"],
                message["cycle_time"],
                message["comment"],
            ]
            for message in snapshot["messages"]
        ),
    )
    _write_rows(
        sheets["Signals"],
        (
            [
                _format_frame_id(signal["message_frame_id"]),
                signal["message_is_extended_frame"],
                signal["name"],
                signal["start"],
                signal["length"],
                signal["byte_order"],
                signal["is_signed"],
                signal["factor"],
                signal["offset"],
                signal["minimum"],
                signal["maximum"],
                signal["unit"],
                ",".join(signal["receivers"]) if signal["receivers"] else None,
                signal["comment"],
                signal["is_multiplexer"],
                signal["multiplexer_signal"],
                _format_multiplexer_ids(signal["multiplexer_ids"]),
            ]
            for signal in snapshot["signals"]
        ),
    )
    _write_rows(
        sheets["Choices"],
        (
            [
                _format_frame_id(signal["message_frame_id"]),
                signal["message_is_extended_frame"],
                signal["name"],
                raw_value,
                label,
            ]
            for signal in snapshot["signals"]
            if signal["choices"]
            for raw_value, label in signal["choices"].items()
        ),
    )

    for name, headers in _SHEET_HEADERS:
        sheet = sheets[name]
        _style_sheet(sheet, headers)
        for header in ("is_extended_frame", "is_fd", "is_signed", "is_multiplexer", "message_is_extended_frame"):
            if header in headers:
                _add_list_validation(sheet, header, headers, _BOOLEAN_FORMULA)
        if "byte_order" in headers:
            _add_list_validation(sheet, "byte_order", headers, _BYTE_ORDER_FORMULA)
    return workbook


def export_database(db: Database, output: Path) -> dict:
    output = Path(output)
    snapshot = DBCService(db).entity_snapshot()
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".xlsx", dir=output.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            workbook = _build_workbook(db, snapshot)
            workbook.save(temporary)
            verification = load_workbook(temporary)
            try:
                expected_sheets = [name for name, _ in _SHEET_HEADERS]
                if verification.sheetnames != expected_sheets:
                    raise DBCError(
                        "Excel export verification failed; refusing to replace the destination."
                    )
            finally:
                verification.close()
            if output.exists():
                shutil.copymode(output, temporary)
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
    except DBCError:
        raise
    except OSError as exc:
        raise DBCError(f"Unable to export Excel '{output}': {exc}") from exc

    return {
        "output": str(output),
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "node_count": len(snapshot["nodes"]),
        "message_count": len(snapshot["messages"]),
        "signal_count": len(snapshot["signals"]),
        "warnings": [],
    }
