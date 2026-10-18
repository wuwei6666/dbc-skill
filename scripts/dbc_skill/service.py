from __future__ import annotations

import cantools
from cantools.database.can import Database, Node

from .errors import DBCError


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

    def _find_node(self, name: str) -> Node:
        for node in self.db.nodes:
            if node.name == name:
                return node
        raise DBCError(f"Node '{name}' not found.")

    @staticmethod
    def _node_to_dict(node: Node) -> dict:
        return {"name": node.name, "comment": node.comment}
