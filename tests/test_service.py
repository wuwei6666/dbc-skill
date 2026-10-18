from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cantools.database.can import Database, Message, Signal

from scripts.dbc_skill import service as service_module
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


class MessageServiceTests(unittest.TestCase):
    def make_service(self, message=None):
        service = DBCService(Database())
        service.add_node("ECU_A", None)
        service.add_node("ECU_B", None)
        if message is not None:
            service.db.messages.append(message)
            service.db.refresh()
        return service

    def make_message(self, **overrides):
        fields = {
            "frame_id": 0x123,
            "name": "Status",
            "length": 8,
            "signals": [],
            "senders": ["ECU_A"],
            "cycle_time": 100,
            "comment": "Original",
        }
        fields.update(overrides)
        return Message(**fields)

    def test_parse_frame_id_accepts_decimal_and_hex(self):
        self.assertEqual(service_module.parse_frame_id(291), 0x123)
        self.assertEqual(service_module.parse_frame_id("291"), 0x123)
        self.assertEqual(service_module.parse_frame_id("0x123"), 0x123)
        self.assertEqual(service_module.parse_frame_id("0X123"), 0x123)

        for value in ("", "xyz", "0x", "0b10", "-1", 1.5, True):
            with self.subTest(value=value):
                with self.assertRaises(DBCError):
                    service_module.parse_frame_id(value)

    def test_add_list_filter_and_show_messages(self):
        service = self.make_service()
        expected = {
            "frame_id": 0x123,
            "name": "Status",
            "length": 8,
            "senders": ["ECU_A"],
            "is_extended_frame": False,
            "is_fd": False,
            "cycle_time": 100,
            "comment": "Status comment",
            "signals": [],
        }

        self.assertEqual(
            service.add_message(
                0x123,
                "Status",
                8,
                ["ECU_A"],
                False,
                False,
                100,
                "Status comment",
            ),
            expected,
        )
        service.add_message(
            0x100, "Heartbeat", 1, ["ECU_B"], False, False, None, None
        )

        self.assertEqual(
            [message["name"] for message in service.list_messages()],
            ["Heartbeat", "Status"],
        )
        self.assertEqual(service.list_messages(name="Status"), [expected])
        self.assertEqual(service.list_messages(sender="ECU_A"), [expected])
        self.assertEqual(service.list_messages(sender="Missing"), [])
        self.assertEqual(service.show_message("291"), expected)
        self.assertEqual(service.show_message("0x123"), expected)
        self.assertEqual(service.show_message("Status"), expected)

    def test_update_rename_and_id_change_preserve_unspecified_fields(self):
        service = self.make_service(self.make_message())

        renamed = service.update_message("0x123", name="Renamed")
        self.assertEqual(renamed["frame_id"], 0x123)
        self.assertEqual(renamed["length"], 8)
        self.assertEqual(renamed["senders"], ["ECU_A"])
        self.assertEqual(renamed["cycle_time"], 100)
        self.assertEqual(renamed["comment"], "Original")

        changed = service.update_message("Renamed", frame_id=0x124)
        self.assertEqual(changed["name"], "Renamed")
        self.assertEqual(service.show_message("0x124"), changed)
        with self.assertRaises(DBCError):
            service.show_message("0x123")

    def test_update_frame_type_fd_metadata_and_clear_nullable_fields(self):
        service = self.make_service(self.make_message())

        updated = service.update_message(
            "Status",
            extended=True,
            fd=True,
            length=64,
            cycle_time=250,
            comment="Updated",
        )
        self.assertTrue(updated["is_extended_frame"])
        self.assertTrue(updated["is_fd"])
        self.assertEqual(updated["length"], 64)
        self.assertEqual(updated["cycle_time"], 250)
        self.assertEqual(updated["comment"], "Updated")

        cleared = service.update_message(
            "Status",
            extended=False,
            fd=False,
            length=8,
            cycle_time=None,
            comment=None,
        )
        self.assertFalse(cleared["is_extended_frame"])
        self.assertFalse(cleared["is_fd"])
        self.assertIsNone(cleared["cycle_time"])
        self.assertIsNone(cleared["comment"])

    def test_frame_id_and_dlc_boundaries_are_enforced(self):
        invalid_ids = (
            (-1, False),
            (0x800, False),
            (-1, True),
            (0x20000000, True),
        )
        for frame_id, extended in invalid_ids:
            with self.subTest(frame_id=frame_id, extended=extended):
                service = self.make_service()
                with self.assertRaises(DBCError):
                    service.add_message(
                        frame_id, "Invalid", 8, [], extended, False, None, None
                    )
                self.assertEqual(service.list_messages(), [])

        for fd, length in ((False, 0), (False, 9), (True, 0), (True, 65)):
            with self.subTest(fd=fd, length=length):
                service = self.make_service()
                with self.assertRaises(DBCError):
                    service.add_message(
                        0x123, "Invalid", length, [], False, fd, None, None
                    )
                self.assertEqual(service.list_messages(), [])

        service = self.make_service()
        self.assertEqual(
            service.add_message(0, "Zero", 1, [], False, False, None, None)[
                "frame_id"
            ],
            0,
        )
        self.assertEqual(
            service.add_message(
                0x7FF, "MaxStandard", 8, [], False, False, None, None
            )["frame_id"],
            0x7FF,
        )
        maximum = service.add_message(
            0x1FFFFFFF, "MaxExtended", 64, [], True, True, None, None
        )
        self.assertEqual(maximum["frame_id"], 0x1FFFFFFF)
        self.assertEqual(maximum["length"], 64)

    def test_senders_are_validated_and_replaceable(self):
        service = self.make_service(self.make_message())

        with self.assertRaises(DBCError):
            service.add_message(
                0x124, "Invalid", 8, ["Missing"], False, False, None, None
            )
        with self.assertRaises(DBCError):
            service.update_message("Status", senders=["Missing"])
        self.assertEqual(service.show_message("Status")["senders"], ["ECU_A"])

        self.assertEqual(
            service.update_message("Status", senders=["ECU_B", "ECU_A"])[
                "senders"
            ],
            ["ECU_B", "ECU_A"],
        )
        self.assertEqual(service.update_message("Status", senders=[])["senders"], [])

    def test_duplicate_ids_and_names_are_rejected_before_mutation(self):
        service = self.make_service(self.make_message())
        service.add_message(0x124, "Other", 8, [], False, False, None, None)

        with self.assertRaises(DBCError):
            service.add_message(
                0x123, "DuplicateId", 8, [], True, False, None, None
            )
        with self.assertRaises(DBCError):
            service.add_message(
                0x125, "Status", 8, [], False, False, None, None
            )
        with self.assertRaises(DBCError):
            service.update_message("Other", frame_id=0x123)
        with self.assertRaises(DBCError):
            service.update_message("Other", name="Status")

        self.assertEqual(service.show_message("Other")["frame_id"], 0x124)
        self.assertEqual(len(service.list_messages()), 2)

    def test_delete_reports_signal_count_and_missing_messages_fail(self):
        message = self.make_message(
            length=2,
            signals=[
                Signal(name="First", start=0, length=8),
                Signal(name="Second", start=8, length=8),
            ],
        )
        service = self.make_service(message)

        result = service.delete_message("0x123")
        self.assertEqual(result["name"], "Status")
        self.assertEqual(result["deleted_signal_count"], 2)
        self.assertEqual(service.list_messages(), [])

        operations = (
            ("show", lambda: service.show_message("0x123")),
            ("show-name", lambda: service.show_message("Missing")),
            ("update", lambda: service.update_message("291", name="New")),
            ("delete", lambda: service.delete_message("0x123")),
        )
        for operation, call in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(DBCError):
                    call()

    def test_shrinking_dlc_below_signal_boundary_fails_without_mutation(self):
        service = self.make_service(
            self.make_message(
                length=3,
                signals=[Signal(name="Wide", start=8, length=16)],
            )
        )

        with self.assertRaises(DBCError):
            service.update_message("Status", length=2)

        self.assertEqual(service.show_message("Status")["length"], 3)

    def test_message_metadata_survives_node_edit_and_save_reload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "messages.dbc"
            service = self.make_service()
            service.add_message(
                0x1FFFF,
                "FdStatus",
                64,
                ["ECU_A"],
                True,
                True,
                50,
                "状态 comment",
            )
            service.update_node("ECU_A", None, "Updated node", False)

            save_database(service.db, source, None, "utf-8", backup=True)
            reloaded = DBCService(load_database(source, "utf-8"))
            message = reloaded.show_message("FdStatus")

            self.assertEqual(message["frame_id"], 0x1FFFF)
            self.assertTrue(message["is_extended_frame"])
            self.assertTrue(message["is_fd"])
            self.assertEqual(message["length"], 64)
            self.assertEqual(message["senders"], ["ECU_A"])
            self.assertEqual(message["cycle_time"], 50)
            self.assertEqual(message["comment"], "状态 comment")


if __name__ == "__main__":
    unittest.main()
