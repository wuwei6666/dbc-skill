from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cantools.database.can import Database, Message, Signal

from scripts.dbc_skill.errors import DBCError
from scripts.dbc_skill.service import DBCService
from scripts.dbc_skill.storage import load_database, save_database


class NodeServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = DBCService(Database())

    def test_add_list_and_show_nodes(self):
        self.assertEqual(self.service.list_nodes(), [])
        self.assertEqual(
            self.service.add_node("ECU_B", None),
            {"name": "ECU_B", "comment": None},
        )
        self.assertEqual(
            self.service.add_node("ECU_A", "Gateway"),
            {"name": "ECU_A", "comment": "Gateway"},
        )

        self.assertEqual(
            self.service.list_nodes(),
            [
                {"name": "ECU_A", "comment": "Gateway"},
                {"name": "ECU_B", "comment": None},
            ],
        )
        self.assertEqual(
            self.service.show_node("ECU_B"),
            {"name": "ECU_B", "comment": None},
        )

    def test_partial_update_preserves_values_and_clear_comment(self):
        self.service.add_node("ECU_A", "Original")

        self.assertEqual(
            self.service.update_node("ECU_A", None, "Updated", False),
            {"name": "ECU_A", "comment": "Updated"},
        )
        self.assertEqual(
            self.service.update_node("ECU_A", None, None, False),
            {"name": "ECU_A", "comment": "Updated"},
        )
        self.assertEqual(
            self.service.update_node("ECU_A", "ECU_C", None, False),
            {"name": "ECU_C", "comment": "Updated"},
        )
        self.assertEqual(
            self.service.update_node("ECU_C", None, None, True),
            {"name": "ECU_C", "comment": None},
        )

    def test_duplicate_names_are_rejected(self):
        self.service.add_node("ECU_A", None)
        self.service.add_node("ECU_B", None)

        with self.assertRaises(DBCError):
            self.service.add_node("ECU_A", None)
        with self.assertRaises(DBCError):
            self.service.update_node("ECU_B", "ECU_A", None, False)

        self.assertEqual(
            self.service.show_node("ECU_B"),
            {"name": "ECU_B", "comment": None},
        )

    def test_missing_node_errors(self):
        operations = (
            ("show", lambda: self.service.show_node("Missing")),
            (
                "update",
                lambda: self.service.update_node("Missing", None, None, False),
            ),
            ("delete", lambda: self.service.delete_node("Missing")),
        )

        for operation, call in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(DBCError):
                    call()

    def test_delete_unreferenced_node(self):
        self.service.add_node("ECU_A", "Disposable")

        self.assertEqual(
            self.service.delete_node("ECU_A"),
            {"name": "ECU_A", "comment": "Disposable"},
        )
        self.assertEqual(self.service.list_nodes(), [])

    def test_rename_updates_references_and_referenced_delete_fails(self):
        service = DBCService(Database())
        service.add_node("ECU_A", None)
        service.add_node("ECU_B", None)
        service.db.messages.append(Message(
            frame_id=0x123, name="Status", length=8, signals=[], senders=["ECU_A"]
        ))
        service.db.refresh()
        service.db.messages[0].signals.append(
            Signal(
                name="State",
                start=0,
                length=8,
                receivers=["ECU_A", "ECU_B"],
            )
        )
        service.db.refresh()

        with self.assertRaises(DBCError):
            service.delete_node("ECU_A")
        service.update_node("ECU_A", "ECU_C", None, False)

        self.assertEqual(service.db.messages[0].senders, ["ECU_C"])
        self.assertEqual(
            service.db.messages[0].signals[0].receivers,
            ["ECU_C", "ECU_B"],
        )

    def test_signal_receiver_reference_prevents_delete(self):
        self.service.add_node("ECU_A", None)
        self.service.db.messages.append(
            Message(
                frame_id=0x123,
                name="Status",
                length=8,
                signals=[
                    Signal(name="State", start=0, length=8, receivers=["ECU_A"])
                ],
                senders=[],
            )
        )
        self.service.db.refresh()

        with self.assertRaises(DBCError):
            self.service.delete_node("ECU_A")

        self.assertEqual(self.service.show_node("ECU_A")["name"], "ECU_A")

    def test_save_reload_preserves_comment_and_renamed_references(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "nodes.dbc"
            service = DBCService(Database())
            service.add_node("ECU_A", "Gateway")
            service.add_node("ECU_B", None)
            service.db.messages.append(
                Message(
                    frame_id=0x123,
                    name="Status",
                    length=8,
                    signals=[
                        Signal(
                            name="State", start=0, length=8, receivers=["ECU_A"]
                        )
                    ],
                    senders=["ECU_A"],
                )
            )
            service.db.refresh()
            service.update_node("ECU_A", "ECU_C", None, False)

            save_database(service.db, source, None, "utf-8", backup=True)
            reloaded = DBCService(load_database(source, "utf-8"))

            self.assertEqual(
                reloaded.show_node("ECU_C"),
                {"name": "ECU_C", "comment": "Gateway"},
            )
            self.assertEqual(reloaded.db.messages[0].senders, ["ECU_C"])
            self.assertEqual(
                reloaded.db.messages[0].signals[0].receivers,
                ["ECU_C"],
            )


if __name__ == "__main__":
    unittest.main()
