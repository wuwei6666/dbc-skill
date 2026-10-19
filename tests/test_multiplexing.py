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


class ExtendedMultiplexingTests(unittest.TestCase):
    def make_service(self):
        service = DBCService(Database())
        service.add_message(0x123, "Status", 8, [], False, False, None, None)
        return service

    def add_extended_multiplexing(self, service):
        service.add_signal("Status", "Mode", start=0, length=8, is_multiplexer=True)
        service.add_signal(
            "Status",
            "SubMode",
            start=8,
            length=8,
            is_multiplexer=True,
            multiplexer_signal="Mode",
            multiplexer_ids=[1, 2],
        )
        service.add_signal(
            "Status",
            "Payload",
            start=16,
            length=16,
            multiplexer_signal="SubMode",
            multiplexer_ids=[3],
        )
        service.add_signal("Status", "AliveCounter", start=32, length=8)

    def assert_extended_metadata(self, service):
        sub_mode = service.show_signal("Status", "SubMode")
        self.assertTrue(sub_mode["is_multiplexer"])
        self.assertEqual(sub_mode["multiplexer_signal"], "Mode")
        self.assertEqual(sub_mode["multiplexer_ids"], [1, 2])
        payload = service.show_signal("Status", "Payload")
        self.assertEqual(payload["multiplexer_signal"], "SubMode")
        self.assertEqual(payload["multiplexer_ids"], [3])

    def test_nested_multiplexing_round_trip_encode_decode_and_unrelated_update(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "extended.dbc"
            service = self.make_service()
            self.add_extended_multiplexing(service)
            self.assert_extended_metadata(service)

            save_database(service.db, source, None, "utf-8", backup=False)

            self.assertIn("SG_MUL_VAL_", source.read_text(encoding="utf-8"))
            reloaded = DBCService(load_database(source, "utf-8"))
            self.assert_extended_metadata(reloaded)
            data = reloaded.db.encode_message(
                0x123,
                {"Mode": 2, "SubMode": 3, "Payload": 0x1234, "AliveCounter": 7},
            )
            self.assertEqual(
                reloaded.db.decode_message(0x123, data),
                {"Mode": 2, "SubMode": 3, "Payload": 0x1234, "AliveCounter": 7},
            )

            from cantools.database.can.formats.dbc_specifics import DbcSpecifics

            alive_counter = next(
                signal
                for signal in reloaded.db.messages[0].signals
                if signal.name == "AliveCounter"
            )
            alive_counter.dbc = DbcSpecifics()
            original_dbc = alive_counter.dbc
            reloaded.update_signal("Status", "AliveCounter", comment="Updated")
            updated = next(
                signal
                for signal in reloaded.db.messages[0].signals
                if signal.name == "AliveCounter"
            )
            self.assertIs(updated.dbc, original_dbc)
            self.assert_extended_metadata(reloaded)
            save_database(reloaded.db, source, None, "utf-8", backup=False)
            self.assert_extended_metadata(DBCService(load_database(source, "utf-8")))

    def test_multi_value_range_round_trip_and_encode_decode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "ranges.dbc"
            service = self.make_service()
            service.add_signal(
                "Status", "Mode", start=0, length=8, is_multiplexer=True
            )
            service.add_signal(
                "Status",
                "Payload",
                start=8,
                length=8,
                multiplexer_signal="Mode",
                multiplexer_ids=[2, 3, 4, 10],
            )

            save_database(service.db, source, None, "utf-8", backup=False)

            self.assertIn("SG_MUL_VAL_", source.read_text(encoding="utf-8"))
            reloaded = DBCService(load_database(source, "utf-8"))
            self.assertEqual(
                reloaded.show_signal("Status", "Payload")["multiplexer_ids"],
                [2, 3, 4, 10],
            )
            data = reloaded.db.encode_message(0x123, {"Mode": 10, "Payload": 0x5A})
            self.assertEqual(
                reloaded.db.decode_message(0x123, data),
                {"Mode": 10, "Payload": 0x5A},
            )

    def test_invalid_extended_metadata_fails_before_replacing_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            for case in ("not-selector", "cycle", "duplicate", "negative"):
                with self.subTest(case=case):
                    source = Path(temporary_directory) / f"{case}.dbc"
                    service = self.make_service()
                    self.add_extended_multiplexing(service)
                    save_database(service.db, source, None, "utf-8", backup=False)
                    original = source.read_bytes()
                    signals = {
                        signal.name: signal
                        for signal in service.db.messages[0].signals
                    }
                    if case == "not-selector":
                        signals["SubMode"].is_multiplexer = False
                    elif case == "cycle":
                        signals["Mode"].multiplexer_signal = "SubMode"
                        signals["Mode"].multiplexer_ids = [3]
                    elif case == "duplicate":
                        signals["SubMode"].multiplexer_ids = [1, 1, 2]
                    else:
                        signals["Payload"].multiplexer_ids = [-1]

                    with self.assertRaises(DBCError):
                        save_database(service.db, source, None, "utf-8", backup=True)

                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(Path(str(source) + ".bak").exists())

    def test_validate_rejects_cyclic_extended_metadata(self):
        service = self.make_service()
        self.add_extended_multiplexing(service)
        mode = next(
            signal
            for signal in service.db.messages[0].signals
            if signal.name == "Mode"
        )
        mode.multiplexer_signal = "SubMode"
        mode.multiplexer_ids = [3]

        with self.assertRaises(DBCError):
            service.validate()

    def test_multiplexer_range_parsing(self):
        from scripts.dbc_skill.values import parse_multiplexer_values

        self.assertEqual(parse_multiplexer_values("0,2-4,0xA"), [0, 2, 3, 4, 10])
        with self.assertRaises(DBCError):
            parse_multiplexer_values("4-2")


if __name__ == "__main__":
    unittest.main()
