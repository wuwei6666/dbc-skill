from __future__ import annotations

from cantools.database.can import Database, Message, Signal

from .service import DBCService


_ENTITY_TYPES = ("nodes", "messages", "signals")
_STATUSES = ("added", "removed", "modified", "unchanged")


def _message_identity(message: Message) -> tuple[int, bool]:
    return message.frame_id, message.is_extended_frame


def _message_identifier(identity: tuple[int, bool]) -> dict:
    frame_id, is_extended_frame = identity
    return {"frame_id": frame_id, "is_extended_frame": is_extended_frame}


def _signal_identifier(identity: tuple[int, bool, str]) -> dict:
    frame_id, is_extended_frame, name = identity
    return {
        "message_frame_id": frame_id,
        "message_is_extended_frame": is_extended_frame,
        "name": name,
    }


def _signal_details(message: Message, signal: Signal) -> dict:
    identity = (*_message_identity(message), signal.name)
    return {
        **_signal_identifier(identity),
        **DBCService._signal_to_dict(signal),
    }


def _message_details(message: Message) -> dict:
    details = DBCService._message_to_dict(message)
    details["signals"] = sorted(
        details["signals"],
        key=lambda signal: (signal["start"], signal["name"], signal["length"]),
    )
    return details


def _changes(left: dict, right: dict) -> dict:
    return {
        field: {"left": left[field], "right": right[field]}
        for field in sorted(left)
        if left[field] != right[field]
    }


def _compare_entities(left: dict, right: dict, identifier) -> dict:
    result = {status: [] for status in _STATUSES}
    for identity in sorted(set(left) | set(right)):
        if identity not in left:
            result["added"].append(right[identity])
        elif identity not in right:
            result["removed"].append(left[identity])
        elif left[identity] == right[identity]:
            result["unchanged"].append(identifier(identity))
        else:
            result["modified"].append(
                {
                    **identifier(identity),
                    "changes": _changes(left[identity], right[identity]),
                }
            )
    return result


def compare_databases(left: Database, right: Database) -> dict:
    left_nodes = {
        node.name: DBCService._node_to_dict(node) for node in left.nodes
    }
    right_nodes = {
        node.name: DBCService._node_to_dict(node) for node in right.nodes
    }
    left_messages = {
        _message_identity(message): _message_details(message)
        for message in left.messages
    }
    right_messages = {
        _message_identity(message): _message_details(message)
        for message in right.messages
    }
    left_signals = {
        (*_message_identity(message), signal.name): _signal_details(message, signal)
        for message in left.messages
        for signal in message.signals
    }
    right_signals = {
        (*_message_identity(message), signal.name): _signal_details(message, signal)
        for message in right.messages
        for signal in message.signals
    }

    result = {
        "nodes": _compare_entities(left_nodes, right_nodes, lambda name: {"name": name}),
        "messages": _compare_entities(
            left_messages, right_messages, _message_identifier
        ),
        "signals": _compare_entities(
            left_signals, right_signals, _signal_identifier
        ),
    }
    counts = {
        status: sum(len(result[entity_type][status]) for entity_type in _ENTITY_TYPES)
        for status in _STATUSES
    }
    equal = not any(counts[status] for status in ("added", "removed", "modified"))
    return {"equal": equal, "counts": counts, **result}
