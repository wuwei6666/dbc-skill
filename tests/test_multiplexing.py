from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cantools.database.can import Database

from scripts.dbc_skill.errors import DBCError
from scripts.dbc_skill.service import DBCService
from scripts.dbc_skill.storage import load_database, save_database


class StandardMultiplexingTests(unittest.TestCase):
    def make_service(self):
        service = DBCService(Database())
        service.add_message(0x123, "Status", 8, [], False, False, None, None)
        return service

    def add_standard_multiplexing(self, service):
        service.add_signal("0x123", "Mode", start=0, length=8, is_multiplexer=True)
        service.add_signal(
            "0x123",
            "Speed",
            start=8,
            length=16,
            multiplexer_signal="Mode",
            multiplexer_ids=[0],
        )
        service.add_signal(
            "0x123",
            "Rpm",
            start=8,
            length=16,
            multiplexer_signal="Mode",
            multiplexer_ids=[1],
        )

    def test_standard_multiplexing_round_trip_and_encode_decode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "multiplexed.dbc"
            service = self.make_service()
            self.add_standard_multiplexing(service)
            service.db.refresh()
            self.assertEqual(
                service.show_signal("0x123", "Rpm")["multiplexer_ids"], [1]
            )

            save_database(service.db, source, None, "utf-8", backup=True)
            reloaded = DBCService(load_database(source, "utf-8"))
            self.assertEqual(
                reloaded.show_signal("Status", "Speed")["multiplexer_signal"],
                "Mode",
            )
            self.assertEqual(
                reloaded.show_signal("Status", "Rpm")["multiplexer_ids"], [1]
            )

            speed_data = reloaded.db.encode_message(
                0x123, {"Mode": 0, "Speed": 0x1234}
            )
            rpm_data = reloaded.db.encode_message(0x123, {"Mode": 1, "Rpm": 0x5678})
            self.assertEqual(
                reloaded.db.decode_message(0x123, speed_data),
                {"Mode": 0, "Speed": 0x1234},
            )
            self.assertEqual(
                reloaded.db.decode_message(0x123, rpm_data),
                {"Mode": 1, "Rpm": 0x5678},
            )

    def test_selector_rename_updates_branches_and_unsafe_changes_fail(self):
        service = self.make_service()
        self.add_standard_multiplexing(service)

        with self.assertRaises(DBCError):
            service.delete_signal("Status", "Mode")
        with self.assertRaises(DBCError):
            service.update_signal("Status", "Mode", is_multiplexer=False)
        self.assertTrue(service.show_signal("Status", "Mode")["is_multiplexer"])
        self.assertEqual(
            service.show_signal("Status", "Speed")["multiplexer_signal"], "Mode"
        )

        renamed = service.update_signal("Status", "Mode", name="State")
        self.assertTrue(renamed["is_multiplexer"])
        for branch in ("Speed", "Rpm"):
            self.assertEqual(
                service.show_signal("Status", branch)["multiplexer_signal"],
                "State",
            )
        with self.assertRaises(DBCError):
            service.delete_signal("Status", "State")

        service.delete_signal("Status", "Speed")
        service.delete_signal("Status", "Rpm")
        self.assertEqual(service.delete_signal("Status", "State")["name"], "State")
        self.assertEqual(service.list_signals("Status"), [])

    def test_branch_assignment_can_be_cleared_and_restored(self):
        service = self.make_service()
        service.add_signal("Status", "Mode", start=0, length=8, is_multiplexer=True)
        service.add_signal(
            "Status", "Speed", start=8, length=16, multiplexer_ids=[0]
        )

        cleared = service.update_signal(
            "Status", "Speed", multiplexer_signal=None, multiplexer_ids=None
        )
        self.assertIsNone(cleared["multiplexer_signal"])
        self.assertIsNone(cleared["multiplexer_ids"])
        data = service.db.encode_message(0x123, {"Mode": 0, "Speed": 0x1234})
        self.assertEqual(
            service.db.decode_message(0x123, data), {"Mode": 0, "Speed": 0x1234}
        )

        restored = service.update_signal("Status", "Speed", multiplexer_ids=[1])
        self.assertEqual(restored["multiplexer_signal"], "Mode")
        self.assertEqual(restored["multiplexer_ids"], [1])

    def test_overlap_validation_respects_branch_ids_and_rolls_back(self):
        service = self.make_service()
        self.add_standard_multiplexing(service)

        with self.assertRaises(DBCError):
            service.add_signal(
                "Status",
                "Conflict",
                start=8,
                length=16,
                multiplexer_signal="Mode",
                multiplexer_ids=[0],
            )
        service.add_signal(
            "Status",
            "Temperature",
            start=8,
            length=16,
            multiplexer_signal="Mode",
            multiplexer_ids=[2],
        )
        with self.assertRaises(DBCError):
            service.update_signal("Status", "Temperature", multiplexer_ids=[0])

        self.assertEqual(
            service.show_signal("Status", "Temperature")["multiplexer_ids"], [2]
        )
        self.assertNotIn(
            "Conflict",
            [signal["name"] for signal in service.list_signals("Status")],
        )

    def test_parent_auto_selection_and_validation(self):
        service = self.make_service()
        with self.assertRaises(DBCError):
            service.add_signal(
                "Status", "Orphan", start=8, length=8, multiplexer_ids=[0]
            )

        service.add_signal("Status", "Mode", start=0, length=8, is_multiplexer=True)
        automatic = service.add_signal(
            "Status", "Speed", start=8, length=8, multiplexer_ids=[0]
        )
        self.assertEqual(automatic["multiplexer_signal"], "Mode")

        with self.assertRaises(DBCError):
            service.add_signal(
                "Status", "NeedsParent", start=24, length=8, multiplexer_ids=[2, 3]
            )
        service.add_signal(
            "Status", "Alternate", start=16, length=8, is_multiplexer=True
        )
        with self.assertRaises(DBCError):
            service.add_signal(
                "Status", "Ambiguous", start=24, length=8, multiplexer_ids=[1]
            )
        explicit = service.add_signal(
            "Status",
            "Explicit",
            start=24,
            length=8,
            multiplexer_signal="Alternate",
            multiplexer_ids=[1],
        )
        self.assertEqual(explicit["multiplexer_signal"], "Alternate")

        for parent in ("Missing", "Speed"):
            with self.subTest(parent=parent):
                with self.assertRaises(DBCError):
                    service.add_signal(
                        "Status",
                        "InvalidParent",
                        start=32,
                        length=8,
                        multiplexer_signal=parent,
                        multiplexer_ids=[0],
                    )
        with self.assertRaises(DBCError):
            service.add_signal(
                "Status",
                "MissingValues",
                start=32,
                length=8,
                multiplexer_signal="Mode",
            )


if __name__ == "__main__":
    unittest.main()
