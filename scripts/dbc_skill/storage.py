from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import cantools
from cantools.database.can import Database

from .errors import DBCError
from .service import validate_multiplexer_metadata
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
        destination = output or source
        in_place = destination == source
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
            if _multiplexer_metadata(reloaded) != expected_multiplexer_metadata:
                raise DBCError(
                    "Multiplexer metadata changed during serialization; "
                    "refusing to replace the destination."
                )
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
