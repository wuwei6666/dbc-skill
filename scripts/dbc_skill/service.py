from __future__ import annotations

import re

import cantools
from cantools.database.can import Database, Message, Node
from cantools.database.can.formats.dbc import ATTRIBUTE_DEFINITION_VFRAMEFORMAT
from cantools.database.can.formats.dbc_specifics import DbcSpecifics

from .errors import DBCError


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
        if not isinstance(name, str) or not name:
            raise DBCError("Message name must be a non-empty string.")
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
