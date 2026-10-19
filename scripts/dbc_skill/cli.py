from __future__ import annotations

import argparse
from pathlib import Path

import cantools
from cantools.database.can import Database

from .compare import compare_databases
from .errors import DBCError
from .excel import (
    FORMAT_NAME,
    SCHEMA_VERSION,
    database_from_workbook,
    export_database,
)
from .formatting import emit_error, emit_result
from .service import DBCService, parse_frame_id
from .storage import load_database, save_database
from .values import parse_choices, parse_multiplexer_values


def _add_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-backup", action="store_true")


def _add_signal_field_arguments(
    parser: argparse.ArgumentParser, adding: bool
) -> None:
    if not adding:
        parser.add_argument("--new-name")
    parser.add_argument("--start", type=int, required=adding)
    parser.add_argument("--length", type=int, required=adding)
    parser.add_argument(
        "--byte-order",
        choices=("little_endian", "big_endian"),
        default="little_endian" if adding else None,
    )
    if adding:
        parser.add_argument("--signed", action="store_true")
        parser.add_argument("--multiplexer", action="store_true")
    else:
        signed_group = parser.add_mutually_exclusive_group()
        signed_group.add_argument("--signed", dest="signed", action="store_true")
        signed_group.add_argument("--unsigned", dest="signed", action="store_false")
        multiplexer_group = parser.add_mutually_exclusive_group()
        multiplexer_group.add_argument(
            "--multiplexer", dest="multiplexer", action="store_true"
        )
        multiplexer_group.add_argument(
            "--no-multiplexer", dest="multiplexer", action="store_false"
        )
        parser.set_defaults(signed=None, multiplexer=None)
    parser.add_argument("--factor", type=float)
    parser.add_argument("--offset", type=float)

    if adding:
        parser.add_argument("--minimum", type=float)
        parser.add_argument("--maximum", type=float)
        parser.add_argument("--unit")
        parser.add_argument("--receiver", dest="receivers", action="append")
        parser.add_argument("--choice", dest="choices", action="append")
        parser.add_argument("--comment")
    else:
        minimum_group = parser.add_mutually_exclusive_group()
        minimum_group.add_argument("--minimum", type=float)
        minimum_group.add_argument("--clear-minimum", action="store_true")
        maximum_group = parser.add_mutually_exclusive_group()
        maximum_group.add_argument("--maximum", type=float)
        maximum_group.add_argument("--clear-maximum", action="store_true")
        unit_group = parser.add_mutually_exclusive_group()
        unit_group.add_argument("--unit")
        unit_group.add_argument("--clear-unit", action="store_true")
        receiver_group = parser.add_mutually_exclusive_group()
        receiver_group.add_argument("--receiver", dest="receivers", action="append")
        receiver_group.add_argument("--clear-receivers", action="store_true")
        choice_group = parser.add_mutually_exclusive_group()
        choice_group.add_argument("--choice", dest="choices", action="append")
        choice_group.add_argument("--clear-choices", action="store_true")
        comment_group = parser.add_mutually_exclusive_group()
        comment_group.add_argument("--comment")
        comment_group.add_argument("--clear-comment", action="store_true")

    parser.add_argument("--multiplexer-of")
    parser.add_argument("--multiplexer-values")
    if not adding:
        parser.add_argument("--clear-multiplexer", action="store_true")


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

    compare_parser = subparsers.add_parser(
        "compare", help="Compare two DBC databases without modifying them."
    )
    compare_parser.add_argument("left", type=Path)
    compare_parser.add_argument("right", type=Path)

    excel_parser = subparsers.add_parser(
        "excel", help="Convert between DBC databases and Excel workbooks."
    )
    excel_subparsers = excel_parser.add_subparsers(
        dest="excel_command", required=True
    )

    excel_export_parser = excel_subparsers.add_parser(
        "export", help="Export a DBC database to an Excel workbook."
    )
    excel_export_parser.add_argument("input", type=Path)
    excel_export_parser.add_argument("output", type=Path)

    excel_import_parser = excel_subparsers.add_parser(
        "import", help="Import an Excel workbook into a DBC database."
    )
    excel_import_parser.add_argument("input", type=Path)
    excel_import_parser.add_argument("output", type=Path)

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

    message_parser = subparsers.add_parser("message", help="Manage DBC messages.")
    message_subparsers = message_parser.add_subparsers(
        dest="message_command", required=True
    )

    message_list_parser = message_subparsers.add_parser("list", help="List messages.")
    message_list_parser.add_argument("path", type=Path)
    message_list_parser.add_argument("--name")
    message_list_parser.add_argument("--sender")

    message_show_parser = message_subparsers.add_parser("show", help="Show a message.")
    message_show_parser.add_argument("path", type=Path)
    message_show_parser.add_argument("reference")

    message_add_parser = message_subparsers.add_parser("add", help="Add a message.")
    message_add_parser.add_argument("path", type=Path)
    message_add_parser.add_argument("frame_id")
    message_add_parser.add_argument("name")
    message_add_parser.add_argument("--length", type=int, required=True)
    message_add_parser.add_argument("--sender", dest="senders", action="append")
    message_add_parser.add_argument("--extended", action="store_true")
    message_add_parser.add_argument("--fd", action="store_true")
    message_add_parser.add_argument("--cycle-time", type=int)
    message_add_parser.add_argument("--comment")
    _add_mutation_arguments(message_add_parser)

    message_update_parser = message_subparsers.add_parser(
        "update", help="Update a message."
    )
    message_update_parser.add_argument("path", type=Path)
    message_update_parser.add_argument("reference")
    message_update_parser.add_argument("--new-id")
    message_update_parser.add_argument("--new-name")
    message_update_parser.add_argument("--length", type=int)
    sender_group = message_update_parser.add_mutually_exclusive_group()
    sender_group.add_argument("--sender", dest="senders", action="append")
    sender_group.add_argument("--clear-senders", action="store_true")
    frame_type_group = message_update_parser.add_mutually_exclusive_group()
    frame_type_group.add_argument("--extended", dest="extended", action="store_true")
    frame_type_group.add_argument("--standard", dest="extended", action="store_false")
    fd_group = message_update_parser.add_mutually_exclusive_group()
    fd_group.add_argument("--fd", dest="fd", action="store_true")
    fd_group.add_argument("--classic", dest="fd", action="store_false")
    cycle_time_group = message_update_parser.add_mutually_exclusive_group()
    cycle_time_group.add_argument("--cycle-time", type=int)
    cycle_time_group.add_argument("--clear-cycle-time", action="store_true")
    message_comment_group = message_update_parser.add_mutually_exclusive_group()
    message_comment_group.add_argument("--comment")
    message_comment_group.add_argument("--clear-comment", action="store_true")
    message_update_parser.set_defaults(extended=None, fd=None)
    _add_mutation_arguments(message_update_parser)

    message_delete_parser = message_subparsers.add_parser(
        "delete", help="Delete a message."
    )
    message_delete_parser.add_argument("path", type=Path)
    message_delete_parser.add_argument("reference")
    _add_mutation_arguments(message_delete_parser)

    signal_parser = subparsers.add_parser("signal", help="Manage DBC signals.")
    signal_subparsers = signal_parser.add_subparsers(
        dest="signal_command", required=True
    )

    signal_list_parser = signal_subparsers.add_parser("list", help="List signals.")
    signal_list_parser.add_argument("path", type=Path)
    signal_list_parser.add_argument("message_ref")
    signal_list_parser.add_argument("--name")

    signal_show_parser = signal_subparsers.add_parser("show", help="Show a signal.")
    signal_show_parser.add_argument("path", type=Path)
    signal_show_parser.add_argument("message_ref")
    signal_show_parser.add_argument("name")

    signal_add_parser = signal_subparsers.add_parser("add", help="Add a signal.")
    signal_add_parser.add_argument("path", type=Path)
    signal_add_parser.add_argument("message_ref")
    signal_add_parser.add_argument("name")
    _add_signal_field_arguments(signal_add_parser, adding=True)
    _add_mutation_arguments(signal_add_parser)

    signal_update_parser = signal_subparsers.add_parser(
        "update", help="Update a signal."
    )
    signal_update_parser.add_argument("path", type=Path)
    signal_update_parser.add_argument("message_ref")
    signal_update_parser.add_argument("name")
    _add_signal_field_arguments(signal_update_parser, adding=False)
    _add_mutation_arguments(signal_update_parser)

    signal_delete_parser = signal_subparsers.add_parser(
        "delete", help="Delete a signal."
    )
    signal_delete_parser.add_argument("path", type=Path)
    signal_delete_parser.add_argument("message_ref")
    signal_delete_parser.add_argument("name")
    _add_mutation_arguments(signal_delete_parser)

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
        elif args.command == "compare":
            left = load_database(args.left, args.encoding)
            right = load_database(args.right, args.encoding)
            result = compare_databases(left, right)
        elif args.command == "excel":
            if args.excel_command == "export":
                db = load_database(args.input, args.encoding)
                result = {"input": str(args.input)}
                result.update(export_database(db, args.output))
            elif args.excel_command == "import":
                db, warnings = database_from_workbook(args.input)
                snapshot = DBCService(db).entity_snapshot()
                result = {
                    "input": str(args.input),
                    "format": FORMAT_NAME,
                    "schema_version": SCHEMA_VERSION,
                    "node_count": len(snapshot["nodes"]),
                    "message_count": len(snapshot["messages"]),
                    "signal_count": len(snapshot["signals"]),
                    "warnings": warnings,
                }
                result.update(
                    save_database(
                        db,
                        args.input,
                        args.output,
                        args.encoding,
                        backup=False,
                    )
                )
            else:
                raise DBCError(f"Unknown excel command: {args.excel_command}")
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
        elif args.command == "message":
            service = DBCService(load_database(args.path, args.encoding))
            if args.message_command == "list":
                result = {"messages": service.list_messages(args.name, args.sender)}
            elif args.message_command == "show":
                result = service.show_message(args.reference)
            else:
                if args.message_command == "add":
                    result = service.add_message(
                        parse_frame_id(args.frame_id),
                        args.name,
                        args.length,
                        args.senders or [],
                        args.extended,
                        args.fd,
                        args.cycle_time,
                        args.comment,
                    )
                elif args.message_command == "update":
                    changes = {}
                    if args.new_id is not None:
                        changes["frame_id"] = parse_frame_id(args.new_id)
                    if args.new_name is not None:
                        changes["name"] = args.new_name
                    if args.length is not None:
                        changes["length"] = args.length
                    if args.clear_senders:
                        changes["senders"] = []
                    elif args.senders is not None:
                        changes["senders"] = args.senders
                    if args.extended is not None:
                        changes["extended"] = args.extended
                    if args.fd is not None:
                        changes["fd"] = args.fd
                    if args.clear_cycle_time:
                        changes["cycle_time"] = None
                    elif args.cycle_time is not None:
                        changes["cycle_time"] = args.cycle_time
                    if args.clear_comment:
                        changes["comment"] = None
                    elif args.comment is not None:
                        changes["comment"] = args.comment
                    result = service.update_message(args.reference, **changes)
                elif args.message_command == "delete":
                    result = service.delete_message(args.reference)
                else:
                    raise DBCError(
                        f"Unknown message command: {args.message_command}"
                    )
                result.update(
                    save_database(
                        service.db,
                        args.path,
                        args.output,
                        args.encoding,
                        backup=not args.no_backup,
                    )
                )
        elif args.command == "signal":
            service = DBCService(load_database(args.path, args.encoding))
            if args.signal_command == "list":
                result = {
                    "signals": service.list_signals(args.message_ref, args.name)
                }
            elif args.signal_command == "show":
                result = service.show_signal(args.message_ref, args.name)
            else:
                if args.signal_command == "add":
                    fields = {
                        "start": args.start,
                        "length": args.length,
                        "byte_order": args.byte_order,
                        "is_signed": args.signed,
                        "receivers": args.receivers or [],
                        "is_multiplexer": args.multiplexer,
                    }
                    for field in ("factor", "offset", "minimum", "maximum", "unit", "comment"):
                        value = getattr(args, field)
                        if value is not None:
                            fields[field] = value
                    if args.choices is not None:
                        fields["choices"] = parse_choices(args.choices)
                    if args.multiplexer_of is not None:
                        fields["multiplexer_signal"] = args.multiplexer_of
                    if args.multiplexer_values is not None:
                        fields["multiplexer_ids"] = parse_multiplexer_values(
                            args.multiplexer_values
                        )
                    result = service.add_signal(args.message_ref, args.name, **fields)
                elif args.signal_command == "update":
                    changes = {}
                    if args.new_name is not None:
                        changes["name"] = args.new_name
                    for field in ("start", "length", "byte_order", "factor", "offset"):
                        value = getattr(args, field)
                        if value is not None:
                            changes[field] = value
                    if args.signed is not None:
                        changes["is_signed"] = args.signed
                    if args.multiplexer is not None:
                        changes["is_multiplexer"] = args.multiplexer
                    if args.clear_minimum:
                        changes["minimum"] = None
                    elif args.minimum is not None:
                        changes["minimum"] = args.minimum
                    if args.clear_maximum:
                        changes["maximum"] = None
                    elif args.maximum is not None:
                        changes["maximum"] = args.maximum
                    if args.clear_unit:
                        changes["unit"] = None
                    elif args.unit is not None:
                        changes["unit"] = args.unit
                    if args.clear_receivers:
                        changes["receivers"] = []
                    elif args.receivers is not None:
                        changes["receivers"] = args.receivers
                    if args.clear_choices:
                        changes["choices"] = None
                    elif args.choices is not None:
                        changes["choices"] = parse_choices(args.choices)
                    if args.clear_comment:
                        changes["comment"] = None
                    elif args.comment is not None:
                        changes["comment"] = args.comment
                    if args.clear_multiplexer:
                        if (
                            args.multiplexer_of is not None
                            or args.multiplexer_values is not None
                        ):
                            raise DBCError(
                                "--clear-multiplexer cannot be combined with a new assignment."
                            )
                        changes["multiplexer_signal"] = None
                        changes["multiplexer_ids"] = None
                    else:
                        if args.multiplexer_of is not None:
                            changes["multiplexer_signal"] = args.multiplexer_of
                        if args.multiplexer_values is not None:
                            changes["multiplexer_ids"] = parse_multiplexer_values(
                                args.multiplexer_values
                            )
                    result = service.update_signal(
                        args.message_ref, args.name, **changes
                    )
                elif args.signal_command == "delete":
                    result = service.delete_signal(args.message_ref, args.name)
                else:
                    raise DBCError(f"Unknown signal command: {args.signal_command}")
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
