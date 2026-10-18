from __future__ import annotations

import cantools
from cantools.database.can import Database

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
