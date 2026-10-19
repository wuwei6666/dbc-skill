from __future__ import annotations

import math
import re

import cantools
from cantools.database.can import Database, Message, Node, Signal
from cantools.database.can.formats.dbc import (
    ATTRIBUTE_DEFINITION_VFRAMEFORMAT,
    get_dbc_name,
)
from cantools.database.can.formats.dbc_specifics import DbcSpecifics
from cantools.database.conversion import BaseConversion

from .errors import DBCError
from .values import parse_integer, validate_signal_bounds


def _validate_dbc_name(name: str, entity_type: str) -> None:
    if not isinstance(name, str) or not name:
        raise DBCError(f"{entity_type} name must be a non-empty string.")
    normalized = get_dbc_name(name)
    if normalized != name:
        raise DBCError(
            f"{entity_type} name '{name}' would be rewritten by cantools as '{normalized}'."
        )


def parse_frame_id(value: str | int) -> int:
    if isinstance(value, bool):
        raise DBCError("Frame ID must be a decimal or 0x hexadecimal integer.")

    if isinstance(value, int):
        frame_id = value
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?[0-9]+", text):
            frame_id = int(text, 10)
        elif re.fullmatch(r"[+-]?0[xX][0-9a-fA-F]+", text):
            frame_id = int(text, 16)
        else:
            raise DBCError(
                f"Invalid frame ID '{value}'; use decimal or 0x hexadecimal notation."
            )
    else:
        raise DBCError("Frame ID must be a decimal or 0x hexadecimal integer.")

    if not 0 <= frame_id <= 0x1FFFFFFF:
        raise DBCError("Frame ID must be between 0 and 0x1FFFFFFF.")
    return frame_id


def validate_multiplexer_metadata(db: Database) -> None:
    for message in db.messages:
        signals_by_name = {}
        for signal in message.signals:
            if signal.name in signals_by_name:
                raise DBCError(
                    f"Signal '{signal.name}' is duplicated in message '{message.name}'."
                )
            signals_by_name[signal.name] = signal

        for signal in message.signals:
            if not isinstance(signal.is_multiplexer, bool):
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer role must be boolean."
                )
            parent_name = signal.multiplexer_signal
            multiplexer_ids = signal.multiplexer_ids
            if (parent_name is None) != (multiplexer_ids is None):
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer parent and IDs must be assigned together."
                )
            if parent_name is None:
                continue
            if not isinstance(parent_name, str) or not parent_name:
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer parent must be a non-empty signal name."
                )
            if isinstance(multiplexer_ids, (str, bytes)):
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer IDs must be nonnegative integers."
                )
            try:
                normalized_ids = list(multiplexer_ids)
            except TypeError as exc:
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer IDs must be nonnegative integers."
                ) from exc
            if not normalized_ids or any(
                isinstance(multiplexer_id, bool)
                or not isinstance(multiplexer_id, int)
                or multiplexer_id < 0
                for multiplexer_id in normalized_ids
            ):
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer IDs must be nonempty and nonnegative."
                )
            if len(set(normalized_ids)) != len(normalized_ids):
                raise DBCError(
                    f"Signal '{signal.name}' multiplexer IDs must not contain duplicates."
                )
            parent = signals_by_name.get(parent_name)
            if parent is None:
                raise DBCError(
                    f"Multiplexer parent '{parent_name}' not found for signal '{signal.name}'."
                )
            if not parent.is_multiplexer:
                raise DBCError(
                    f"Multiplexer parent '{parent_name}' is not a selector."
                )

        for signal in message.signals:
            seen = {signal.name}
            current = signal
            while current.multiplexer_signal is not None:
                parent_name = current.multiplexer_signal
                if parent_name in seen:
                    raise DBCError("Multiplexer assignments must not contain cycles.")
                seen.add(parent_name)
                current = signals_by_name[parent_name]


class DBCService:
    def __init__(self, db: Database):
        self.db = db

    def summary(self) -> dict:
        return {
            "version": self.db.version,
            "node_count": len(self.db.nodes),
            "message_count": len(self.db.messages),
            "signal_count": sum(len(message.signals) for message in self.db.messages),
        }

    def validate(self) -> dict:
        validate_multiplexer_metadata(self.db)
        try:
            self.db.refresh()
        except (KeyError, ValueError, cantools.database.errors.Error) as exc:
            raise DBCError(f"Invalid DBC database: {exc}") from exc
        return {"valid": True}

    def list_nodes(self) -> list[dict]:
        return [
            self._node_to_dict(node)
            for node in sorted(self.db.nodes, key=lambda node: node.name)
        ]

    def show_node(self, name: str) -> dict:
        return self._node_to_dict(self._find_node(name))

    def add_node(self, name: str, comment: str | None) -> dict:
        _validate_dbc_name(name, "Node")
        if any(node.name == name for node in self.db.nodes):
            raise DBCError(f"Node '{name}' already exists.")

        node = Node(name=name, comment=comment)
        self.db.nodes.append(node)
        return self._node_to_dict(node)

    def update_node(
        self,
        name: str,
        new_name: str | None,
        comment: str | None,
        clear_comment: bool,
    ) -> dict:
        old = self._find_node(name)
        updated_name = new_name if new_name is not None else name
        _validate_dbc_name(updated_name, "Node")
        if updated_name != name and any(
            node.name == updated_name for node in self.db.nodes
        ):
            raise DBCError(f"Node '{updated_name}' already exists.")

        if clear_comment:
            updated_comment = None
        elif comment is not None:
            updated_comment = comment
        else:
            updated_comment = old.comment

        replacement = Node(
            name=updated_name, comment=updated_comment, dbc_specifics=old.dbc
        )
        self.db.nodes[self.db.nodes.index(old)] = replacement

        if updated_name != name:
            for message in self.db.messages:
                message.senders[:] = [
                    updated_name if sender == name else sender
                    for sender in message.senders
                ]
                for signal in message.signals:
                    signal.receivers[:] = [
                        updated_name if receiver == name else receiver
                        for receiver in signal.receivers
                    ]

        return self._node_to_dict(replacement)

    def delete_node(self, name: str) -> dict:
        node = self._find_node(name)
        references = []
        for message in self.db.messages:
            if name in message.senders:
                references.append(f"message '{message.name}' senders")
            for signal in message.signals:
                if name in signal.receivers:
                    references.append(
                        f"message '{message.name}' signal '{signal.name}' receivers"
                    )

        if references:
            raise DBCError(
                f"Cannot delete node '{name}'; referenced by: {', '.join(references)}."
            )

        result = self._node_to_dict(node)
        self.db.nodes.remove(node)
        return result

    def list_messages(
        self, name: str | None = None, sender: str | None = None
    ) -> list[dict]:
        messages = self.db.messages
        if name is not None:
            messages = [message for message in messages if message.name == name]
        if sender is not None:
            messages = [message for message in messages if sender in message.senders]
        return [
            self._message_to_dict(message)
            for message in sorted(
                messages, key=lambda message: (message.frame_id, message.name)
            )
        ]

    def show_message(self, reference: str | int) -> dict:
        return self._message_to_dict(self._find_message(reference))

    def add_message(
        self,
        frame_id: int,
        name: str,
        length: int,
        senders: list[str],
        extended: bool,
        fd: bool,
        cycle_time: int | None,
        comment: str | None,
    ) -> dict:
        frame_id = parse_frame_id(frame_id)
        senders = self._validate_message_fields(
            frame_id, name, length, senders, extended, fd, cycle_time
        )
        self._check_message_duplicates(frame_id, name)

        try:
            message = Message(
                frame_id=frame_id,
                name=name,
                length=length,
                signals=[],
                senders=senders,
                is_extended_frame=extended,
                is_fd=fd,
                cycle_time=cycle_time,
                comment=comment,
            )
        except (KeyError, TypeError, ValueError, cantools.database.errors.Error) as exc:
            raise DBCError(f"Invalid message '{name}': {exc}") from exc

        self.db.messages.append(message)
        try:
            self._refresh_database()
        except DBCError:
            self.db.messages.remove(message)
            self._refresh_after_rollback()
            raise
        if message.is_fd:
            self._ensure_fd_metadata()
        return self._message_to_dict(message)

    def update_message(self, reference: str | int, **changes) -> dict:
        message = self._find_message(reference)
        allowed = {
            "frame_id",
            "name",
            "length",
            "senders",
            "extended",
            "fd",
            "cycle_time",
            "comment",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise DBCError(f"Unknown message fields: {', '.join(sorted(unknown))}.")

        frame_id = parse_frame_id(changes.get("frame_id", message.frame_id))
        name = changes.get("name", message.name)
        length = changes.get("length", message.length)
        extended = changes.get("extended", message.is_extended_frame)
        fd = changes.get("fd", message.is_fd)
        cycle_time = (
            changes["cycle_time"] if "cycle_time" in changes else message.cycle_time
        )
        comment = changes["comment"] if "comment" in changes else message.comment
        senders = self._validate_message_fields(
            frame_id,
            name,
            length,
            changes.get("senders", message.senders),
            extended,
            fd,
            cycle_time,
        )
        self._check_message_duplicates(frame_id, name, exclude=message)

        original = (
            message.frame_id,
            message.name,
            message.length,
            list(message.senders),
            message.is_extended_frame,
            message.is_fd,
            message.cycle_time,
            message.comment,
        )
        try:
            message.frame_id = frame_id
            message.name = name
            message.length = length
            message.senders[:] = senders
            message.is_extended_frame = extended
            message.is_fd = fd
            message.cycle_time = cycle_time
            message.comment = comment
            self._refresh_database()
        except (
            DBCError,
            KeyError,
            TypeError,
            ValueError,
            cantools.database.errors.Error,
        ) as exc:
            message.frame_id = original[0]
            message.name = original[1]
            message.length = original[2]
            message.senders[:] = original[3]
            message.is_extended_frame = original[4]
            message.is_fd = original[5]
            message.cycle_time = original[6]
            message.comment = original[7]
            self._refresh_after_rollback()
            if isinstance(exc, DBCError):
                raise
            raise DBCError(f"Invalid message update: {exc}") from exc

        if "extended" in changes or "fd" in changes:
            self._clear_frame_format_metadata(message)
        if message.is_fd:
            self._ensure_fd_metadata()
        return self._message_to_dict(message)

    def delete_message(self, reference: str | int) -> dict:
        message = self._find_message(reference)
        result = self._message_to_dict(message)
        result["deleted_signal_count"] = len(message.signals)
        index = self.db.messages.index(message)
        del self.db.messages[index]
        try:
            self._refresh_database()
        except DBCError:
            self.db.messages.insert(index, message)
            self._refresh_after_rollback()
            raise
        return result

    def list_signals(self, message_ref: str | int, name: str | None = None) -> list[dict]:
        message = self._find_message(message_ref)
        signals = message.signals
        if name is not None:
            signals = [signal for signal in signals if signal.name == name]
        return [
            self._signal_to_dict(signal)
            for signal in sorted(signals, key=lambda signal: (signal.start, signal.name))
        ]

    def show_signal(self, message_ref: str | int, name: str) -> dict:
        return self._signal_to_dict(self._find_signal(message_ref, name)[1])

    def add_signal(self, message_ref: str | int, name: str, **fields) -> dict:
        message = self._find_message(message_ref)
        allowed = {
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
            "choices",
            "comment",
            "is_multiplexer",
            "multiplexer_ids",
            "multiplexer_signal",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise DBCError(f"Unknown signal fields: {', '.join(sorted(unknown))}.")
        if "start" not in fields or "length" not in fields:
            raise DBCError("Both start and length are required when adding a signal.")

        signal = self._build_signal(message, name, fields)
        self._check_signal_duplicate(message, name)
        index = len(message.signals)
        message.signals.append(signal)
        try:
            self._refresh_signals(message)
        except DBCError:
            message.signals.pop(index)
            self._refresh_after_rollback()
            raise
        return self._signal_to_dict(signal)

    def update_signal(self, message_ref: str | int, name: str, /, **changes) -> dict:
        message, signal = self._find_signal(message_ref, name)
        allowed = {
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
            "choices",
            "comment",
            "is_multiplexer",
            "multiplexer_ids",
            "multiplexer_signal",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise DBCError(f"Unknown signal fields: {', '.join(sorted(unknown))}.")

        updated_name = changes.get("name", signal.name)
        replacement = self._build_signal(message, updated_name, changes, old=signal)
        self._check_signal_duplicate(message, updated_name, exclude=signal)
        dependents = [
            other
            for other in message.signals
            if other is not signal and other.multiplexer_signal == signal.name
        ]
        if signal.is_multiplexer and not replacement.is_multiplexer and dependents:
            raise DBCError(
                f"Cannot remove multiplexer role from '{signal.name}' while branches reference it."
            )

        index = message.signals.index(signal)
        changed_references = []
        message.signals[index] = replacement
        if updated_name != signal.name:
            for dependent in dependents:
                changed_references.append((dependent, dependent.multiplexer_signal))
                dependent.multiplexer_signal = updated_name
        try:
            self._refresh_signals(message)
        except DBCError:
            message.signals[index] = signal
            for dependent, old_parent in changed_references:
                dependent.multiplexer_signal = old_parent
            self._refresh_after_rollback()
            raise
        return self._signal_to_dict(replacement)

    def delete_signal(self, message_ref: str | int, name: str) -> dict:
        message, signal = self._find_signal(message_ref, name)
        dependents = [
            other.name
            for other in message.signals
            if other is not signal and other.multiplexer_signal == signal.name
        ]
        if dependents:
            raise DBCError(
                f"Cannot delete signal '{name}'; referenced by branches: {', '.join(dependents)}."
            )

        result = self._signal_to_dict(signal)
        index = message.signals.index(signal)
        message.signals.pop(index)
        try:
            self._refresh_signals(message)
        except DBCError:
            message.signals.insert(index, signal)
            self._refresh_after_rollback()
            raise
        return result

    def _find_signal(self, message_ref: str | int, name: str) -> tuple[Message, Signal]:
        message = self._find_message(message_ref)
        for signal in message.signals:
            if signal.name == name:
                return message, signal
        raise DBCError(f"Signal '{name}' not found in message '{message.name}'.")

    def _build_signal(
        self,
        message: Message,
        name: str,
        changes: dict,
        old: Signal | None = None,
    ) -> Signal:
        changes = dict(changes)
        changes.pop("name", None)
        if old is None:
            values = {
                "start": None,
                "length": None,
                "byte_order": "little_endian",
                "is_signed": False,
                "factor": 1,
                "offset": 0,
                "minimum": None,
                "maximum": None,
                "unit": None,
                "receivers": [],
                "choices": None,
                "comment": None,
                "is_multiplexer": False,
                "multiplexer_ids": None,
                "multiplexer_signal": None,
            }
        else:
            values = {
                "start": old.start,
                "length": old.length,
                "byte_order": old.byte_order,
                "is_signed": old.is_signed,
                "factor": old.scale,
                "offset": old.offset,
                "minimum": old.minimum,
                "maximum": old.maximum,
                "unit": old.unit,
                "receivers": list(old.receivers),
                "choices": (
                    {
                        raw_value: str(label)
                        for raw_value, label in old.choices.items()
                    }
                    if old.choices is not None
                    else None
                ),
                "comment": old.comment,
                "is_multiplexer": old.is_multiplexer,
                "multiplexer_ids": old.multiplexer_ids,
                "multiplexer_signal": old.multiplexer_signal,
            }
        values.update(changes)
        values = self._validate_signal_values(message, name, values, old=old)

        try:
            conversion = BaseConversion.factory(
                scale=values["factor"],
                offset=values["offset"],
                choices=values["choices"],
                is_float=old.is_float if old is not None else False,
            )
            comment = (
                values["comment"]
                if old is None or "comment" in changes
                else old.comments
            )
            return Signal(
                name=name,
                start=values["start"],
                length=values["length"],
                byte_order=values["byte_order"],
                is_signed=values["is_signed"],
                raw_initial=old.raw_initial if old is not None else None,
                raw_invalid=old.raw_invalid if old is not None else None,
                conversion=conversion,
                minimum=values["minimum"],
                maximum=values["maximum"],
                unit=values["unit"],
                dbc_specifics=old.dbc if old is not None else None,
                comment=comment,
                receivers=values["receivers"],
                is_multiplexer=values["is_multiplexer"],
                multiplexer_ids=values["multiplexer_ids"],
                multiplexer_signal=values["multiplexer_signal"],
                spn=old.spn if old is not None else None,
            )
        except (KeyError, TypeError, ValueError, cantools.database.errors.Error) as exc:
            raise DBCError(f"Invalid signal '{name}': {exc}") from exc

    def _validate_signal_values(
        self,
        message: Message,
        name: str,
        values: dict,
        old: Signal | None,
    ) -> dict:
        _validate_dbc_name(name, "Signal")
        values["start"] = parse_integer(values["start"])
        values["length"] = parse_integer(values["length"])
        if values["start"] < 0:
            raise DBCError("Signal start must be nonnegative.")
        if values["length"] <= 0:
            raise DBCError("Signal length must be positive.")
        if values["byte_order"] not in ("little_endian", "big_endian"):
            raise DBCError("Signal byte order must be little_endian or big_endian.")
        for field in ("is_signed", "is_multiplexer"):
            if not isinstance(values[field], bool):
                raise DBCError(f"Signal {field} must be boolean.")

        for field in ("factor", "offset", "minimum", "maximum"):
            value = values[field]
            if value is None and field in ("minimum", "maximum"):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DBCError(f"Signal {field} must be a number.")
            if isinstance(value, float) and not math.isfinite(value):
                raise DBCError(f"Signal {field} must be finite.")
        if (
            values["minimum"] is not None
            and values["maximum"] is not None
            and values["minimum"] > values["maximum"]
        ):
            raise DBCError("Signal minimum must not exceed maximum.")
        validate_signal_bounds(values["minimum"], values["maximum"])

        for field in ("unit", "comment"):
            if values[field] is not None and not isinstance(values[field], str):
                raise DBCError(f"Signal {field} must be a string or null.")

        receivers = values["receivers"]
        if isinstance(receivers, (str, bytes)):
            raise DBCError("Signal receivers must be a list of node names.")
        try:
            receivers = list(receivers)
        except TypeError as exc:
            raise DBCError("Signal receivers must be a list of node names.") from exc
        for receiver in receivers:
            if not isinstance(receiver, str):
                raise DBCError("Signal receiver names must be strings.")
            self._find_node(receiver)
        values["receivers"] = receivers

        choices = values["choices"]
        if choices is not None:
            if not isinstance(choices, dict):
                raise DBCError("Signal choices must be a dictionary of integer labels.")
            normalized_choices = {}
            for raw_value, label in choices.items():
                if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                    raise DBCError("Signal choice values must be integers.")
                if not isinstance(label, str) or not label:
                    raise DBCError("Signal choice labels must be non-empty strings.")
                normalized_choices[raw_value] = label
            values["choices"] = {
                raw_value: normalized_choices[raw_value]
                for raw_value in sorted(normalized_choices)
            }

        multiplexer_ids = values["multiplexer_ids"]
        if multiplexer_ids is not None:
            if isinstance(multiplexer_ids, (str, bytes)):
                raise DBCError("Multiplexer IDs must be a list of nonnegative integers.")
            try:
                multiplexer_ids = [
                    parse_integer(multiplexer_id)
                    for multiplexer_id in list(multiplexer_ids)
                ]
            except TypeError as exc:
                raise DBCError(
                    "Multiplexer IDs must be a list of nonnegative integers."
                ) from exc
            if not multiplexer_ids or any(
                multiplexer_id < 0 for multiplexer_id in multiplexer_ids
            ):
                raise DBCError("Multiplexer IDs must be nonempty and nonnegative.")
            multiplexer_ids = sorted(set(multiplexer_ids))
            values["multiplexer_ids"] = multiplexer_ids

        parent = values["multiplexer_signal"]
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise DBCError("Multiplexer parent must be a non-empty signal name.")
        if parent is None and multiplexer_ids is not None:
            if len(multiplexer_ids) != 1:
                raise DBCError(
                    "An explicit multiplexer parent is required for multiple IDs."
                )
            roots = [
                signal
                for signal in message.signals
                if signal is not old
                and signal.is_multiplexer
                and signal.multiplexer_signal is None
            ]
            if len(roots) != 1:
                raise DBCError(
                    "An explicit multiplexer parent is required unless the message has one root selector."
                )
            parent = roots[0].name
            values["multiplexer_signal"] = parent
        if (parent is None) != (multiplexer_ids is None):
            raise DBCError("Multiplexer parent and IDs must be assigned together.")

        if parent is not None:
            if parent == name:
                raise DBCError("A signal cannot be its own multiplexer parent.")
            candidates = [
                signal
                for signal in message.signals
                if signal is not old and signal.name == parent
            ]
            if not candidates:
                raise DBCError(f"Multiplexer parent '{parent}' not found.")
            parent_signal = candidates[0]
            seen = {name}
            current = parent_signal
            while current is not None:
                if current.name in seen:
                    raise DBCError("Multiplexer assignments must not contain cycles.")
                if not current.is_multiplexer:
                    raise DBCError(
                        f"Multiplexer parent '{current.name}' is not a selector."
                    )
                seen.add(current.name)
                ancestor_name = current.multiplexer_signal
                if ancestor_name is None:
                    break
                if ancestor_name == name:
                    raise DBCError("Multiplexer assignments must not contain cycles.")
                current = next(
                    (
                        signal
                        for signal in message.signals
                        if signal is not old and signal.name == ancestor_name
                    ),
                    None,
                )
                if current is None:
                    raise DBCError(f"Multiplexer parent '{ancestor_name}' not found.")
        return values

    @staticmethod
    def _check_signal_duplicate(
        message: Message, name: str, exclude: Signal | None = None
    ) -> None:
        if any(
            signal is not exclude and signal.name == name for signal in message.signals
        ):
            raise DBCError(f"Signal '{name}' already exists in message '{message.name}'.")

    def _refresh_signals(self, message: Message) -> None:
        try:
            message.refresh(strict=True)
        except (KeyError, TypeError, ValueError, cantools.database.errors.Error) as exc:
            raise DBCError(f"Invalid DBC database: {exc}") from exc
        self._refresh_database()

    @staticmethod
    def _signal_to_dict(signal: Signal) -> dict:
        return {
            "name": signal.name,
            "start": signal.start,
            "length": signal.length,
            "byte_order": signal.byte_order,
            "is_signed": signal.is_signed,
            "factor": signal.scale,
            "offset": signal.offset,
            "minimum": signal.minimum,
            "maximum": signal.maximum,
            "unit": signal.unit,
            "receivers": list(signal.receivers),
            "choices": (
                {
                    raw_value: str(signal.choices[raw_value])
                    for raw_value in sorted(signal.choices)
                }
                if signal.choices is not None
                else None
            ),
            "comment": signal.comment,
            "is_multiplexer": signal.is_multiplexer,
            "multiplexer_ids": (
                sorted(signal.multiplexer_ids)
                if signal.multiplexer_ids is not None
                else None
            ),
            "multiplexer_signal": signal.multiplexer_signal,
        }

    def _find_message(self, reference: str | int) -> Message:
        if isinstance(reference, str):
            try:
                frame_id = parse_frame_id(reference)
            except DBCError:
                frame_id = None
            if frame_id is not None:
                matches = [
                    message
                    for message in self.db.messages
                    if message.frame_id == frame_id
                ]
            else:
                matches = [
                    message for message in self.db.messages if message.name == reference
                ]
        else:
            frame_id = parse_frame_id(reference)
            matches = [
                message for message in self.db.messages if message.frame_id == frame_id
            ]

        if not matches:
            raise DBCError(f"Message '{reference}' not found.")
        if len(matches) > 1:
            raise DBCError(f"Message reference '{reference}' is ambiguous.")
        return matches[0]

    def _validate_message_fields(
        self,
        frame_id: int,
        name: str,
        length: int,
        senders: list[str],
        extended: bool,
        fd: bool,
        cycle_time: int | None,
    ) -> list[str]:
        _validate_dbc_name(name, "Message")
        if not isinstance(extended, bool) or not isinstance(fd, bool):
            raise DBCError("Message frame type and CAN FD flags must be boolean.")

        frame_kind = "Extended" if extended else "Standard"
        maximum_id = 0x1FFFFFFF if extended else 0x7FF
        if not 0 <= frame_id <= maximum_id:
            raise DBCError(
                f"{frame_kind} frame ID must be between 0 and 0x{maximum_id:X}."
            )

        maximum_length = 64 if fd else 8
        length_kind = "CAN FD" if fd else "Classic CAN"
        if (
            isinstance(length, bool)
            or not isinstance(length, int)
            or not 1 <= length <= maximum_length
        ):
            raise DBCError(
                f"{length_kind} message length must be between 1 and {maximum_length}."
            )

        if cycle_time is not None and (
            isinstance(cycle_time, bool)
            or not isinstance(cycle_time, int)
            or cycle_time < 0
        ):
            raise DBCError("Message cycle time must be a nonnegative integer.")

        if isinstance(senders, (str, bytes)):
            raise DBCError("Message senders must be a list of node names.")
        try:
            sender_list = list(senders)
        except TypeError as exc:
            raise DBCError("Message senders must be a list of node names.") from exc
        for sender in sender_list:
            self._find_node(sender)
        return sender_list

    def _check_message_duplicates(
        self, frame_id: int, name: str, exclude: Message | None = None
    ) -> None:
        for message in self.db.messages:
            if message is exclude:
                continue
            if message.frame_id == frame_id:
                raise DBCError(f"Message frame ID '{frame_id}' already exists.")
            if message.name == name:
                raise DBCError(f"Message name '{name}' already exists.")

    @staticmethod
    def _clear_frame_format_metadata(message: Message) -> None:
        if message.dbc is not None and message.dbc.attributes is not None:
            message.dbc.attributes.pop("VFrameFormat", None)

    def _ensure_fd_metadata(self) -> None:
        if self.db.dbc is None:
            self.db.dbc = DbcSpecifics()
        definitions = self.db.dbc.attribute_definitions
        if "VFrameFormat" not in definitions:
            definitions["VFrameFormat"] = ATTRIBUTE_DEFINITION_VFRAMEFORMAT

    def _refresh_database(self) -> None:
        try:
            self.db.refresh()
        except (
            KeyError,
            TypeError,
            ValueError,
            cantools.database.errors.Error,
        ) as exc:
            raise DBCError(f"Invalid DBC database: {exc}") from exc

    def _refresh_after_rollback(self) -> None:
        try:
            self.db.refresh()
        except (
            KeyError,
            TypeError,
            ValueError,
            cantools.database.errors.Error,
        ):
            pass

    @staticmethod
    def _message_to_dict(message: Message) -> dict:
        return {
            "frame_id": message.frame_id,
            "name": message.name,
            "length": message.length,
            "senders": list(message.senders),
            "is_extended_frame": message.is_extended_frame,
            "is_fd": message.is_fd,
            "cycle_time": message.cycle_time,
            "comment": message.comment,
            "signals": [
                {
                    "name": signal.name,
                    "start": signal.start,
                    "length": signal.length,
                }
                for signal in message.signals
            ],
        }

    def _find_node(self, name: str) -> Node:
        for node in self.db.nodes:
            if node.name == name:
                return node
        raise DBCError(f"Node '{name}' not found.")

    @staticmethod
    def _node_to_dict(node: Node) -> dict:
        return {"name": node.name, "comment": node.comment}
