from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import cantools
from cantools.database.can import Database

from .errors import DBCError


def load_database(path: Path, encoding: str) -> Database:
    try:
        return cantools.database.load_file(str(path), encoding=encoding, strict=True)
    except (OSError, KeyError, ValueError, cantools.database.errors.Error) as exc:
        raise DBCError(f"Unable to load DBC '{path}': {exc}") from exc


def save_database(
    db: Database,
    source: Path,
    output: Path | None,
    encoding: str,
    backup: bool,
) -> dict:
    backup_path = None
    try:
        db.refresh()
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
            cantools.database.load_file(
                str(temporary), encoding=encoding, strict=True
            ).refresh()
            if in_place and backup and source.exists():
                backup_path = Path(str(source) + ".bak")
                shutil.copy2(source, backup_path)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    except (OSError, KeyError, ValueError, cantools.database.errors.Error) as exc:
        raise DBCError(f"Unable to save DBC '{output or source}': {exc}") from exc

    return {
        "output": str(destination),
        "backup": str(backup_path) if backup_path is not None else None,
    }
