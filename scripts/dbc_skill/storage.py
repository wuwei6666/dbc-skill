from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import cantools
from cantools.database.can import Database

from .errors import DBCError
from .service import DBCService, validate_multiplexer_metadata
from .values import validate_signal_bounds


def load_database(path: Path, encoding: str) -> Database:
    try:
        return cantools.database.load_file(str(path), encoding=encoding, strict=True)
    except (OSError, LookupError, ValueError, cantools.database.errors.Error) as exc:
        raise DBCError(f"Unable to load DBC '{path}': {exc}") from exc


def _multiplexer_metadata(db: Database) -> dict:
    return {
        (message.frame_id, message.name, signal.name): (
            signal.is_multiplexer,
            signal.multiplexer_signal,
            (
                tuple(sorted(signal.multiplexer_ids))
                if signal.multiplexer_ids is not None
                else None
            ),
        )
        for message in db.messages
        for signal in message.signals
    }


def _supported_metadata(db: Database) -> dict:
    messages = []
    signals = []
    for message in db.messages:
        details = DBCService._message_to_dict(message)
        details["signals"] = sorted(
            details["signals"],
            key=lambda signal: (signal["start"], signal["name"], signal["length"]),
        )
        messages.append(details)
        signals.extend(
            {
                "message_frame_id": message.frame_id,
                "message_is_extended_frame": message.is_extended_frame,
                **DBCService._signal_to_dict(signal),
            }
            for signal in message.signals
        )

    messages.sort(
        key=lambda message: (
            message["frame_id"],
            message["is_extended_frame"],
            message["name"],
        )
    )
    signals.sort(
        key=lambda signal: (
            signal["message_frame_id"],
            signal["message_is_extended_frame"],
            signal["name"],
        )
    )
    return {
        "nodes": sorted(
            (DBCService._node_to_dict(node) for node in db.nodes),
            key=lambda node: node["name"],
        ),
        "messages": messages,
        "signals": signals,
    }


def _same_file(source: Path, destination: Path) -> bool:
    try:
        if source.samefile(destination):
            return True
    except OSError:
        pass
    return source.resolve(strict=False) == destination.resolve(strict=False)


def save_database(
    db: Database,
    source: Path,
    output: Path | None,
    encoding: str,
    backup: bool,
) -> dict:
    for message in db.messages:
        for signal in message.signals:
            validate_signal_bounds(signal.minimum, signal.maximum)
    validate_multiplexer_metadata(db)

    backup_path = None
    try:
        db.refresh()
        expected_multiplexer_metadata = _multiplexer_metadata(db)
        expected_supported_metadata = _supported_metadata(db)
        destination = output or source
        in_place = _same_file(source, destination)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".dbc", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with temporary.open("w", encoding=encoding, newline="") as stream:
                stream.write(db.as_dbc_string())
            reloaded = cantools.database.load_file(
                str(temporary), encoding=encoding, strict=True
            )
            reloaded.refresh()
            if (
                _multiplexer_metadata(reloaded) != expected_multiplexer_metadata
                or _supported_metadata(reloaded) != expected_supported_metadata
            ):
                raise DBCError(
                    "Supported DBC metadata, including multiplexer metadata, changed "
                    "during serialization; refusing to replace the destination."
                )
            if destination.exists():
                shutil.copymode(destination, temporary)
            if in_place and backup and source.exists():
                backup_path = Path(str(source) + ".bak")
                shutil.copy2(source, backup_path)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    except (
        OSError,
        LookupError,
        TypeError,
        ValueError,
        cantools.database.errors.Error,
    ) as exc:
        raise DBCError(f"Unable to save DBC '{output or source}': {exc}") from exc

    return {
        "output": str(destination),
        "backup": str(backup_path) if backup_path is not None else None,
    }
