from __future__ import annotations

import argparse
from pathlib import Path

import cantools
from cantools.database.can import Database

from .errors import DBCError
from .formatting import emit_error, emit_result
from .service import DBCService
from .storage import load_database, save_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbc_crud.py", description="Create and inspect CAN DBC databases."
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--encoding", default="utf-8")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create an empty DBC database.")
    init_parser.add_argument("path", type=Path)

    summary_parser = subparsers.add_parser(
        "summary", help="Summarize a DBC database."
    )
    summary_parser.add_argument("path", type=Path)

    validate_parser = subparsers.add_parser(
        "validate", help="Parse and validate a DBC database."
    )
    validate_parser.add_argument("path", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            args.path.parent.mkdir(parents=True, exist_ok=True)
            result = save_database(
                Database(), args.path, None, args.encoding, backup=True
            )
        elif args.command == "summary":
            service = DBCService(load_database(args.path, args.encoding))
            result = service.summary()
        elif args.command == "validate":
            service = DBCService(load_database(args.path, args.encoding))
            try:
                result = service.validate()
            except DBCError as exc:
                raise DBCError(
                    f"Unable to validate DBC '{args.path}': {exc}"
                ) from exc
        else:
            raise DBCError(f"Unknown command: {args.command}")
    except (DBCError, OSError, KeyError, cantools.database.errors.Error) as exc:
        emit_error(args.command, str(exc), args.json_output)
        return 1

    emit_result(args.command, result, args.json_output)
    return 0
