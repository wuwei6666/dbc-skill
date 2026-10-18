from __future__ import annotations

import argparse
from pathlib import Path

import cantools
from cantools.database.can import Database

from .errors import DBCError
from .formatting import emit_error, emit_result
from .service import DBCService
from .storage import load_database, save_database


def _add_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-backup", action="store_true")


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

    node_parser = subparsers.add_parser("node", help="Manage DBC nodes.")
    node_subparsers = node_parser.add_subparsers(dest="node_command", required=True)

    node_list_parser = node_subparsers.add_parser("list", help="List nodes.")
    node_list_parser.add_argument("path", type=Path)

    node_show_parser = node_subparsers.add_parser("show", help="Show a node.")
    node_show_parser.add_argument("path", type=Path)
    node_show_parser.add_argument("name")

    node_add_parser = node_subparsers.add_parser("add", help="Add a node.")
    node_add_parser.add_argument("path", type=Path)
    node_add_parser.add_argument("name")
    node_add_parser.add_argument("--comment")
    _add_mutation_arguments(node_add_parser)

    node_update_parser = node_subparsers.add_parser("update", help="Update a node.")
    node_update_parser.add_argument("path", type=Path)
    node_update_parser.add_argument("name")
    node_update_parser.add_argument("--new-name")
    comment_group = node_update_parser.add_mutually_exclusive_group()
    comment_group.add_argument("--comment")
    comment_group.add_argument("--clear-comment", action="store_true")
    _add_mutation_arguments(node_update_parser)

    node_delete_parser = node_subparsers.add_parser("delete", help="Delete a node.")
    node_delete_parser.add_argument("path", type=Path)
    node_delete_parser.add_argument("name")
    _add_mutation_arguments(node_delete_parser)

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
        elif args.command == "node":
            service = DBCService(load_database(args.path, args.encoding))
            if args.node_command == "list":
                result = {"nodes": service.list_nodes()}
            elif args.node_command == "show":
                result = service.show_node(args.name)
            else:
                if args.node_command == "add":
                    result = service.add_node(args.name, args.comment)
                elif args.node_command == "update":
                    result = service.update_node(
                        args.name,
                        args.new_name,
                        args.comment,
                        args.clear_comment,
                    )
                elif args.node_command == "delete":
                    result = service.delete_node(args.name)
                else:
                    raise DBCError(f"Unknown node command: {args.node_command}")
                result.update(
                    save_database(
                        service.db,
                        args.path,
                        args.output,
                        args.encoding,
                        backup=not args.no_backup,
                    )
                )
        else:
            raise DBCError(f"Unknown command: {args.command}")
    except (DBCError, OSError, LookupError, cantools.database.errors.Error) as exc:
        emit_error(args.command, str(exc), args.json_output)
        return 1

    emit_result(args.command, result, args.json_output)
    return 0
