from __future__ import annotations

import re

from .errors import DBCError


def parse_integer(value: str | int) -> int:
    if isinstance(value, bool):
        raise DBCError("Value must be a decimal or 0x hexadecimal integer.")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise DBCError("Value must be a decimal or 0x hexadecimal integer.")

    text = value.strip()
    if re.fullmatch(r"[+-]?[0-9]+", text):
        return int(text, 10)
    if re.fullmatch(r"[+-]?0[xX][0-9a-fA-F]+", text):
        return int(text, 16)
    raise DBCError(
        f"Invalid integer '{value}'; use decimal or 0x hexadecimal notation."
    )


def parse_choices(values: list[str]) -> dict[int, str]:
    if isinstance(values, (str, bytes)):
        raise DBCError("Choices must be a list of RAW=LABEL entries.")

    choices = {}
    try:
        entries = list(values)
    except TypeError as exc:
        raise DBCError("Choices must be a list of RAW=LABEL entries.") from exc

    for entry in entries:
        if not isinstance(entry, str):
            raise DBCError("Each choice must use RAW=LABEL notation.")
        raw, separator, label = entry.partition("=")
        label = label.strip()
        if not separator or not raw.strip() or not label:
            raise DBCError(f"Invalid choice '{entry}'; use RAW=LABEL notation.")
        raw_value = parse_integer(raw)
        if raw_value in choices:
            raise DBCError(f"Choice value '{raw_value}' is duplicated.")
        choices[raw_value] = label

    return {raw_value: choices[raw_value] for raw_value in sorted(choices)}


def parse_multiplexer_values(value: str) -> list[int]:
    if not isinstance(value, str) or not value.strip():
        raise DBCError("Multiplexer values must be a comma-separated list or ranges.")

    multiplexer_ids = set()
    for part in value.split(","):
        text = part.strip()
        if not text:
            raise DBCError("Multiplexer values contain an empty entry.")
        if "-" in text:
            bounds = text.split("-")
            if len(bounds) != 2:
                raise DBCError(f"Invalid multiplexer range '{text}'.")
            lower = parse_integer(bounds[0])
            upper = parse_integer(bounds[1])
            if lower < 0 or upper < 0:
                raise DBCError("Multiplexer values must be nonnegative integers.")
            if lower > upper:
                raise DBCError(f"Invalid multiplexer range '{text}'.")
            multiplexer_ids.update(range(lower, upper + 1))
        else:
            multiplexer_id = parse_integer(text)
            if multiplexer_id < 0:
                raise DBCError("Multiplexer values must be nonnegative integers.")
            multiplexer_ids.add(multiplexer_id)

    return sorted(multiplexer_ids)


def validate_signal_bounds(minimum, maximum) -> None:
    if (minimum is None) != (maximum is None):
        raise DBCError("DBC cannot represent one-sided signal bounds; set or clear both.")
    if minimum is not None and str(minimum) == str(maximum) == "0":
        raise DBCError(
            "DBC reserves integer 0|0 for absent bounds; use floating-point zero or clear both."
        )
