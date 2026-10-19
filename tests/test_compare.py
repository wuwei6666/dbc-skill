from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from cantools.database.can import Database

from scripts.dbc_skill import cli
from scripts.dbc_skill.compare import compare_databases
from scripts.dbc_skill.service import DBCService
from scripts.dbc_skill.storage import load_database, save_database
from tests.helpers import run_cli


class ComparisonTestCase(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.fixture_index = 0

    def make_service(self, with_nodes=False):
        service = DBCService(Database())
        if with_nodes:
            service.add_node("ECU_A", None)
            service.add_node("ECU_B", None)
        return service

    def write_pair(self, left, right):
        self.fixture_index += 1
        left_path = self.root / f"left-{self.fixture_index}.dbc"
        right_path = self.root / f"right-{self.fixture_index}.dbc"
        save_database(left.db, left_path, None, "utf-8", backup=False)
        save_database(right.db, right_path, None, "utf-8", backup=False)
        return left_path, right_path

    def compare(self, left, right):
        left_path, right_path = self.write_pair(left, right)
        return compare_databases(
            load_database(left_path, "utf-8"),
            load_database(right_path, "utf-8"),
        )

    def add_message(self, service, **overrides):
        fields = {
            "frame_id": 0x123,
            "name": "Status",
            "length": 8,
            "senders": [],
            "extended": False,
            "fd": False,
            "cycle_time": None,
            "comment": None,
        }
        fields.update(overrides)
        return service.add_message(**fields)


class ComparisonEngineTests(ComparisonTestCase):
    def test_identical_files_are_equal_with_stable_unchanged_identifiers(self):
        left = self.make_service(with_nodes=True)
        right = self.make_service(with_nodes=True)
        for service in (left, right):
            self.add_message(service, cycle_time=100)
            service.add_signal("Status", "State", start=0, length=8)

        left_path, right_path = self.write_pair(left, right)
        left_db = load_database(left_path, "utf-8")
        right_db = load_database(right_path, "utf-8")
        left_before = DBCService(left_db).list_messages()
        right_before = DBCService(right_db).list_messages()

        result = compare_databases(left_db, right_db)

        self.assertTrue(result["equal"])
        self.assertEqual(
            result["counts"],
            {"added": 0, "removed": 0, "modified": 0, "unchanged": 4},
        )
        for entity_type in ("nodes", "messages", "signals"):
            for status in ("added", "removed", "modified"):
                self.assertEqual(result[entity_type][status], [])
        self.assertEqual(
            result["nodes"]["unchanged"], [{"name": "ECU_A"}, {"name": "ECU_B"}]
        )
        self.assertEqual(
            result["messages"]["unchanged"],
            [{"frame_id": 0x123, "is_extended_frame": False}],
        )
        self.assertEqual(
            result["signals"]["unchanged"],
            [
                {
                    "message_frame_id": 0x123,
                    "message_is_extended_frame": False,
                    "name": "State",
                }
            ],
        )
        self.assertEqual(DBCService(left_db).list_messages(), left_before)
        self.assertEqual(DBCService(right_db).list_messages(), right_before)

    def test_nodes_report_full_details_changes_and_counts(self):
        left = self.make_service()
        right = self.make_service()
        for name, comment in (
            ("Removed", "remove me"),
            ("Shared", None),
            ("Changed", "old"),
        ):
            left.add_node(name, comment)
        for name, comment in (
            ("Added", "new node"),
            ("Changed", "new"),
            ("Shared", None),
        ):
            right.add_node(name, comment)

        result = self.compare(left, right)

        self.assertFalse(result["equal"])
        self.assertEqual(
            result["nodes"]["added"],
            [{"name": "Added", "comment": "new node"}],
        )
        self.assertEqual(
            result["nodes"]["removed"],
            [{"name": "Removed", "comment": "remove me"}],
        )
        self.assertEqual(
            result["nodes"]["modified"],
            [
                {
                    "name": "Changed",
                    "changes": {"comment": {"left": "old", "right": "new"}},
                }
            ],
        )
        self.assertEqual(result["nodes"]["unchanged"], [{"name": "Shared"}])
        self.assertEqual(
            result["counts"],
            {"added": 1, "removed": 1, "modified": 1, "unchanged": 1},
        )

    def test_message_identity_id_type_and_rename_semantics(self):
        left = self.make_service()
        right = self.make_service()
        self.add_message(left, name="Before")
        self.add_message(right, name="After")
        self.add_message(left, frame_id=0x124, name="ChangedId")
        self.add_message(right, frame_id=0x125, name="ChangedId")
        self.add_message(left, frame_id=0x126, name="ChangedType")
        self.add_message(
            right, frame_id=0x126, name="ChangedType", extended=True
        )
        self.add_message(left, frame_id=0x127, name="Same")
        self.add_message(right, frame_id=0x127, name="Same")

        result = self.compare(left, right)
        messages = result["messages"]

        self.assertEqual(
            messages["modified"],
            [
                {
                    "frame_id": 0x123,
                    "is_extended_frame": False,
                    "changes": {"name": {"left": "Before", "right": "After"}},
                }
            ],
        )
        self.assertEqual(
            [
                (item["frame_id"], item["is_extended_frame"])
                for item in messages["removed"]
            ],
            [(0x124, False), (0x126, False)],
        )
        self.assertEqual(
            [
                (item["frame_id"], item["is_extended_frame"])
                for item in messages["added"]
            ],
            [(0x125, False), (0x126, True)],
        )
        self.assertEqual(
            messages["added"][0],
            {
                "frame_id": 0x125,
                "name": "ChangedId",
                "length": 8,
                "senders": [],
                "is_extended_frame": False,
                "is_fd": False,
                "cycle_time": None,
                "comment": None,
                "signals": [],
            },
        )
        self.assertEqual(
            messages["unchanged"],
            [{"frame_id": 0x127, "is_extended_frame": False}],
        )
        self.assertEqual(
            result["counts"],
            {"added": 2, "removed": 2, "modified": 1, "unchanged": 1},
        )

    def test_message_metadata_changes_use_serialized_fields(self):
        left = self.make_service(with_nodes=True)
        right = self.make_service(with_nodes=True)
        self.add_message(
            left,
            senders=["ECU_A"],
            cycle_time=100,
            comment="Original",
        )
        self.add_message(
            right,
            length=64,
            senders=["ECU_B", "ECU_A"],
            fd=True,
            cycle_time=200,
            comment="Updated",
        )

        result = self.compare(left, right)

        self.assertEqual(len(result["messages"]["modified"]), 1)
        self.assertEqual(
            result["messages"]["modified"][0]["changes"],
            {
                "length": {"left": 8, "right": 64},
                "senders": {
                    "left": ["ECU_A"],
                    "right": ["ECU_B", "ECU_A"],
                },
                "is_fd": {"left": False, "right": True},
                "cycle_time": {"left": 100, "right": 200},
                "comment": {"left": "Original", "right": "Updated"},
            },
        )

    def test_signal_layout_conversion_choices_comments_and_membership(self):
        left = self.make_service(with_nodes=True)
        right = self.make_service(with_nodes=True)
        self.add_message(left)
        self.add_message(right)
        left.add_signal("Status", "UnchangedSignal", start=56, length=8)
        right.add_signal("Status", "UnchangedSignal", start=56, length=8)
        left.add_signal("Status", "RemovedSignal", start=16, length=8)
        left.add_signal(
            "Status",
            "ModifiedSignal",
            start=0,
            length=8,
            factor=2,
            offset=1,
            minimum=0,
            maximum=100,
            unit="rpm",
            receivers=["ECU_A"],
            choices={0: "Off"},
            comment="Original",
        )
        right.add_signal("Status", "NewSignal", start=24, length=8)
        right.add_signal(
            "Status",
            "ModifiedSignal",
            start=7,
            length=16,
            byte_order="big_endian",
            is_signed=True,
            factor=0.5,
            offset=-40,
            minimum=-40,
            maximum=215,
            unit="V",
            receivers=["ECU_B"],
            choices={1: "On"},
            comment="Updated",
        )

        result = self.compare(left, right)
        signals = result["signals"]

        self.assertEqual(
            signals["added"],
            [
                {
                    "message_frame_id": 0x123,
                    "message_is_extended_frame": False,
                    "name": "NewSignal",
                    "start": 24,
                    "length": 8,
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
            ],
        )
        self.assertEqual(signals["removed"][0]["name"], "RemovedSignal")
        self.assertEqual(
            signals["unchanged"],
            [
                {
                    "message_frame_id": 0x123,
                    "message_is_extended_frame": False,
                    "name": "UnchangedSignal",
                }
            ],
        )
        self.assertEqual(len(signals["modified"]), 1)
        modified = signals["modified"][0]
        self.assertEqual(modified["name"], "ModifiedSignal")
        self.assertEqual(modified["message_frame_id"], 0x123)
        self.assertFalse(modified["message_is_extended_frame"])
        self.assertEqual(
            modified["changes"],
            {
                "start": {"left": 0, "right": 7},
                "length": {"left": 8, "right": 16},
                "byte_order": {
                    "left": "little_endian",
                    "right": "big_endian",
                },
                "is_signed": {"left": False, "right": True},
                "factor": {"left": 2, "right": 0.5},
                "offset": {"left": 1, "right": -40},
                "minimum": {"left": 0, "right": -40},
                "maximum": {"left": 100, "right": 215},
                "unit": {"left": "rpm", "right": "V"},
                "receivers": {"left": ["ECU_A"], "right": ["ECU_B"]},
                "choices": {"left": {0: "Off"}, "right": {1: "On"}},
                "comment": {"left": "Original", "right": "Updated"},
            },
        )

    def test_standard_multiplexer_relationship_changes(self):
        left = self.make_service()
        right = self.make_service()
        self.add_message(left)
        self.add_message(right)
        left.add_signal("Status", "Mode", start=0, length=8)
        left.add_signal("Status", "Speed", start=8, length=16)
        right.add_signal(
            "Status", "Mode", start=0, length=8, is_multiplexer=True
        )
        right.add_signal(
            "Status",
            "Speed",
            start=8,
            length=16,
            multiplexer_signal="Mode",
            multiplexer_ids=[0],
        )

        result = self.compare(left, right)
        modified = {
            item["name"]: item["changes"]
            for item in result["signals"]["modified"]
        }

        self.assertEqual(
            modified,
            {
                "Mode": {"is_multiplexer": {"left": False, "right": True}},
                "Speed": {
                    "multiplexer_ids": {"left": None, "right": [0]},
                    "multiplexer_signal": {"left": None, "right": "Mode"},
                },
            },
        )
        self.assertEqual(result["messages"]["unchanged"][0]["frame_id"], 0x123)

    def test_extended_multiplexer_parent_and_range_changes(self):
        left = self.make_service()
        right = self.make_service()
        for service in (left, right):
            self.add_message(service)
            service.add_signal(
                "Status", "Mode", start=0, length=8, is_multiplexer=True
            )
        left.add_signal(
            "Status",
            "SubMode",
            start=8,
            length=8,
            is_multiplexer=True,
            multiplexer_signal="Mode",
            multiplexer_ids=[1, 2],
        )
        left.add_signal(
            "Status",
            "Payload",
            start=16,
            length=16,
            multiplexer_signal="SubMode",
            multiplexer_ids=[3],
        )
        right.add_signal(
            "Status",
            "SubMode",
            start=8,
            length=8,
            is_multiplexer=True,
            multiplexer_signal="Mode",
            multiplexer_ids=[2, 4],
        )
        right.add_signal(
            "Status",
            "Payload",
            start=16,
            length=16,
            multiplexer_signal="Mode",
            multiplexer_ids=[5],
        )

        result = self.compare(left, right)
        modified = {
            item["name"]: item["changes"]
            for item in result["signals"]["modified"]
        }

        self.assertEqual(
            modified["SubMode"],
            {"multiplexer_ids": {"left": [1, 2], "right": [2, 4]}},
        )
        self.assertEqual(
            modified["Payload"],
            {
                "multiplexer_ids": {"left": [3], "right": [5]},
                "multiplexer_signal": {"left": "SubMode", "right": "Mode"},
            },
        )
        self.assertEqual(
            result["signals"]["unchanged"],
            [
                {
                    "message_frame_id": 0x123,
                    "message_is_extended_frame": False,
                    "name": "Mode",
                }
            ],
        )

    def test_float_changes_do_not_use_a_tolerance(self):
        left = self.make_service()
        right = self.make_service()
        self.add_message(left)
        self.add_message(right)
        left.add_signal("Status", "Gain", start=0, length=8, factor=1.0)
        right.add_signal(
            "Status", "Gain", start=0, length=8, factor=1.0000001
        )

        result = self.compare(left, right)

        self.assertEqual(
            result["signals"]["modified"][0]["changes"]["factor"],
            {"left": 1.0, "right": 1.0000001},
        )


class ComparisonCliTests(ComparisonTestCase):
    def test_json_and_text_return_zero_and_preserve_input_bytes(self):
        left = self.make_service()
        right = self.make_service()
        self.add_message(left, cycle_time=100)
        self.add_message(right, cycle_time=200)
        left_path, right_path = self.write_pair(left, right)
        left_bytes = left_path.read_bytes()
        right_bytes = right_path.read_bytes()

        code, out, err = run_cli(
            ["--json", "compare", str(left_path), str(right_path)]
        )

        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["operation"], "compare")
        self.assertFalse(payload["result"]["equal"])
        self.assertEqual(
            payload["result"]["messages"]["modified"][0]["changes"]["cycle_time"],
            {"left": 100, "right": 200},
        )
        second_code, second_out, second_err = run_cli(
            ["--json", "compare", str(left_path), str(right_path)]
        )
        self.assertEqual((second_code, second_out, second_err), (0, out, ""))

        code, text_out, err = run_cli(["compare", str(left_path), str(right_path)])

        self.assertEqual(code, 0, err)
        self.assertIn("Equal: no", text_out)
        self.assertIn("Counts:", text_out)
        self.assertIn('"cycle_time": {"left": 100, "right": 200}', text_out)
        self.assertNotIn("Traceback", text_out + err)

        code, out, err = run_cli(["--json", "compare", str(left_path), str(left_path)])

        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["result"]["equal"])
        code, text_out, err = run_cli(["compare", str(left_path), str(left_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("Equal: yes", text_out)
        self.assertEqual(left_path.read_bytes(), left_bytes)
        self.assertEqual(right_path.read_bytes(), right_bytes)
        self.assertFalse(Path(str(left_path) + ".bak").exists())
        self.assertFalse(Path(str(right_path) + ".bak").exists())

    def test_load_errors_are_nonzero_and_traceback_free(self):
        left = self.make_service()
        right = self.make_service()
        left_path, right_path = self.write_pair(left, right)
        missing_path = self.root / "missing.dbc"
        invalid_path = self.root / "invalid.dbc"
        invalid_path.write_text("this is not a DBC", encoding="utf-8")
        original_bytes = {
            path: path.read_bytes() for path in (left_path, right_path, invalid_path)
        }

        for first, second in (
            (missing_path, right_path),
            (left_path, missing_path),
            (left_path, invalid_path),
        ):
            with self.subTest(first=first, second=second):
                code, out, err = run_cli(
                    ["--json", "compare", str(first), str(second)]
                )

                self.assertEqual(code, 1)
                payload = json.loads(out)
                self.assertFalse(payload["success"])
                self.assertEqual(payload["operation"], "compare")
                self.assertIn("error", payload)
                self.assertNotIn("Traceback", out)
                self.assertNotIn("Traceback", err)
                for path, expected in original_bytes.items():
                    self.assertEqual(path.read_bytes(), expected)

    def test_mutation_and_backup_options_are_rejected_by_the_parser(self):
        left = self.make_service()
        right = self.make_service()
        left_path, right_path = self.write_pair(left, right)
        output_path = self.root / "output.dbc"
        original_left = left_path.read_bytes()
        original_right = right_path.read_bytes()

        for options in (
            ["--output", str(output_path)],
            ["--no-backup"],
            ["--backup"],
        ):
            with self.subTest(options=options):
                stderr = StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    cli.main(
                        ["compare", str(left_path), str(right_path)] + options
                    )

                self.assertEqual(raised.exception.code, 2)
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertEqual(left_path.read_bytes(), original_left)
                self.assertEqual(right_path.read_bytes(), original_right)
                self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
