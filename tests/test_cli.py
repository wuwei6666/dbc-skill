import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cantools

from scripts.dbc_skill.errors import DBCError
from scripts.dbc_skill.storage import load_database, save_database
from tests.helpers import run_cli


class FileCommandTests(unittest.TestCase):
    def test_init_summary_and_validate(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "empty.dbc"

            code, out, err = run_cli(["--json", "init", str(path)])
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["success"])

            code, out, err = run_cli(["--json", "summary", str(path)])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"]["message_count"], 0)

            code, out, err = run_cli(["validate", str(path)])
            self.assertEqual(code, 0, err)

    def test_validate_missing_file_returns_json_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "missing.dbc"

            code, out, err = run_cli(["--json", "validate", str(path)])

            self.assertEqual(code, 1)
            self.assertIn("error", json.loads(out))
            self.assertNotIn("Traceback", out)
            self.assertNotIn("Traceback", err)

    def test_unknown_encoding_returns_json_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "valid.dbc"
            source.write_bytes(cantools.database.Database().as_dbc_string().encode())

            for command, path in (("init", root / "new.dbc"), ("validate", source)):
                with self.subTest(command=command):
                    code, out, err = run_cli(
                        ["--json", "--encoding", "no-such-codec", command, str(path)]
                    )

                    self.assertEqual(code, 1)
                    payload = json.loads(out)
                    self.assertFalse(payload["success"])
                    self.assertIn("error", payload)
                    self.assertNotIn("Traceback", out)
                    self.assertNotIn("Traceback", err)


class StorageTests(unittest.TestCase):
    def test_replace_failure_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "original.dbc"
            original = cantools.database.Database().as_dbc_string().encode("utf-8")
            source.write_bytes(original)
            db = load_database(source, "utf-8")

            with mock.patch(
                "scripts.dbc_skill.storage.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaises(DBCError):
                    save_database(db, source, None, "utf-8", backup=True)

            self.assertEqual(source.read_bytes(), original)

    def test_in_place_save_retains_original_bytes_in_backup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "original.dbc"
            original = cantools.database.Database().as_dbc_string().encode("utf-8")
            source.write_bytes(original)
            db = load_database(source, "utf-8")

            result = save_database(db, source, None, "utf-8", backup=True)

            backup = Path(str(source) + ".bak")
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(result["backup"], str(backup))


class NodeCommandTests(unittest.TestCase):
    def initialize(self, path):
        code, out, err = run_cli(["--json", "init", str(path)])
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["success"])

    def test_node_add_list_show_json_and_default_backup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "nodes.dbc"
            self.initialize(source)
            original = source.read_bytes()

            code, out, err = run_cli(
                [
                    "--json",
                    "node",
                    "add",
                    str(source),
                    "ECU_A",
                    "--comment",
                    "Gateway",
                ]
            )

            self.assertEqual(code, 0, err)
            self.assertEqual(
                json.loads(out)["result"],
                {
                    "name": "ECU_A",
                    "comment": "Gateway",
                    "output": str(source),
                    "backup": str(source) + ".bak",
                },
            )
            self.assertEqual(Path(str(source) + ".bak").read_bytes(), original)

            code, out, err = run_cli(
                ["--json", "node", "add", str(source), "ECU_B", "--no-backup"]
            )
            self.assertEqual(code, 0, err)

            code, out, err = run_cli(["--json", "node", "list", str(source)])
            self.assertEqual(code, 0, err)
            self.assertEqual(
                json.loads(out)["result"],
                {
                    "nodes": [
                        {"name": "ECU_A", "comment": "Gateway"},
                        {"name": "ECU_B", "comment": None},
                    ]
                },
            )

            code, out, err = run_cli(
                ["--json", "node", "show", str(source), "ECU_A"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(
                json.loads(out)["result"],
                {"name": "ECU_A", "comment": "Gateway"},
            )

            code, out, err = run_cli(["node", "list", str(source)])
            self.assertEqual(code, 0, err)
            self.assertIn("ECU_A", out)
            self.assertNotIn("Traceback", err)

    def test_node_update_clear_and_delete_to_separate_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "nodes.dbc"
            output = Path(temporary_directory) / "deleted.dbc"
            self.initialize(source)
            run_cli(
                [
                    "--json",
                    "node",
                    "add",
                    str(source),
                    "ECU_A",
                    "--comment",
                    "Original",
                ]
            )

            code, out, err = run_cli(
                [
                    "--json",
                    "node",
                    "update",
                    str(source),
                    "ECU_A",
                    "--comment",
                    "Updated",
                ]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"]["comment"], "Updated")

            code, out, err = run_cli(
                [
                    "--json",
                    "node",
                    "update",
                    str(source),
                    "ECU_A",
                    "--new-name",
                    "ECU_B",
                ]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(
                json.loads(out)["result"]["comment"],
                "Updated",
            )

            backup = Path(str(source) + ".bak")
            backup.unlink()
            code, out, err = run_cli(
                [
                    "--json",
                    "node",
                    "update",
                    str(source),
                    "ECU_B",
                    "--clear-comment",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            self.assertIsNone(json.loads(out)["result"]["comment"])
            self.assertFalse(backup.exists())

            before_delete = source.read_bytes()
            code, out, err = run_cli(
                [
                    "--json",
                    "node",
                    "delete",
                    str(source),
                    "ECU_B",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(
                json.loads(out)["result"],
                {
                    "name": "ECU_B",
                    "comment": None,
                    "output": str(output),
                    "backup": None,
                },
            )
            self.assertEqual(source.read_bytes(), before_delete)
            self.assertEqual(load_database(output, "utf-8").nodes, [])

    def test_node_duplicate_and_missing_errors_are_traceback_free(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "nodes.dbc"
            self.initialize(source)
            run_cli(["--json", "node", "add", str(source), "ECU_A"])
            run_cli(["--json", "node", "add", str(source), "ECU_B"])

            commands = (
                ["node", "add", str(source), "ECU_A"],
                ["node", "update", str(source), "ECU_B", "--new-name", "ECU_A"],
                ["node", "show", str(source), "Missing"],
                ["node", "update", str(source), "Missing"],
                ["node", "delete", str(source), "Missing"],
            )
            for command in commands:
                with self.subTest(command=command):
                    code, out, err = run_cli(["--json"] + command)

                    self.assertEqual(code, 1)
                    self.assertFalse(json.loads(out)["success"])
                    self.assertIn("error", json.loads(out))
                    self.assertNotIn("Traceback", out)
                    self.assertNotIn("Traceback", err)

    def test_referenced_node_delete_fails_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "nodes.dbc"
            db = cantools.database.Database()
            db.nodes.append(cantools.database.can.Node(name="ECU_A"))
            db.messages.append(
                cantools.database.can.Message(
                    frame_id=0x123,
                    name="Status",
                    length=8,
                    signals=[],
                    senders=["ECU_A"],
                )
            )
            save_database(db, source, None, "utf-8", backup=True)
            original = source.read_bytes()

            code, out, err = run_cli(
                ["--json", "node", "delete", str(source), "ECU_A"]
            )

            self.assertEqual(code, 1)
            self.assertFalse(json.loads(out)["success"])
            self.assertIn("referenced", json.loads(out)["error"])
            self.assertNotIn("Traceback", out)
            self.assertNotIn("Traceback", err)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(Path(str(source) + ".bak").exists())


class MessageCommandTests(unittest.TestCase):
    def initialize(self, path):
        code, out, err = run_cli(["--json", "init", str(path)])
        self.assertEqual(code, 0, err)
        for node in ("ECU_A", "ECU_B"):
            code, out, err = run_cli(
                ["--json", "node", "add", str(path), node, "--no-backup"]
            )
            self.assertEqual(code, 0, err)

    def save_fixture(self, path, messages):
        db = cantools.database.Database()
        db.nodes.extend(
            [
                cantools.database.can.Node(name="ECU_A"),
                cantools.database.can.Node(name="ECU_B"),
            ]
        )
        db.messages.extend(messages)
        save_database(db, path, None, "utf-8", backup=True)

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
        return cantools.database.can.Message(**fields)

    def test_message_add_list_filter_show_and_default_backup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "messages.dbc"
            self.initialize(source)
            original = source.read_bytes()

            code, out, err = run_cli(
                [
                    "--json",
                    "message",
                    "add",
                    str(source),
                    "0x123",
                    "Status",
                    "--length",
                    "8",
                    "--sender",
                    "ECU_A",
                    "--cycle-time",
                    "100",
                    "--comment",
                    "Status comment",
                ]
            )

            self.assertEqual(code, 0, err)
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
                json.loads(out)["result"],
                {
                    **expected,
                    "output": str(source),
                    "backup": str(source) + ".bak",
                },
            )
            self.assertEqual(Path(str(source) + ".bak").read_bytes(), original)

            code, out, err = run_cli(
                [
                    "--json",
                    "message",
                    "add",
                    str(source),
                    "256",
                    "Heartbeat",
                    "--length",
                    "1",
                    "--sender",
                    "ECU_B",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)

            code, out, err = run_cli(
                ["--json", "message", "list", str(source), "--sender", "ECU_A"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"], {"messages": [expected]})

            code, out, err = run_cli(
                ["--json", "message", "list", str(source), "--name", "Heartbeat"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(
                [item["name"] for item in json.loads(out)["result"]["messages"]],
                ["Heartbeat"],
            )

            code, out, err = run_cli(
                ["--json", "message", "show", str(source), "291"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"], expected)

            code, out, err = run_cli(["message", "list", str(source)])
            self.assertEqual(code, 0, err)
            self.assertIn("Status", out)
            self.assertNotIn("Traceback", err)

    def test_message_update_all_fields_and_clear_options(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "messages.dbc"
            self.save_fixture(source, [self.make_message()])

            code, out, err = run_cli(
                [
                    "--json",
                    "message",
                    "update",
                    str(source),
                    "0x123",
                    "--new-id",
                    "0x456",
                    "--new-name",
                    "Renamed",
                    "--length",
                    "64",
                    "--sender",
                    "ECU_B",
                    "--sender",
                    "ECU_A",
                    "--extended",
                    "--fd",
                    "--cycle-time",
                    "250",
                    "--comment",
                    "Updated",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertEqual(result["frame_id"], 0x456)
            self.assertEqual(result["name"], "Renamed")
            self.assertEqual(result["length"], 64)
            self.assertEqual(result["senders"], ["ECU_B", "ECU_A"])
            self.assertTrue(result["is_extended_frame"])
            self.assertTrue(result["is_fd"])
            self.assertEqual(result["cycle_time"], 250)
            self.assertEqual(result["comment"], "Updated")

            code, out, err = run_cli(
                [
                    "--json",
                    "message",
                    "update",
                    str(source),
                    "Renamed",
                    "--standard",
                    "--classic",
                    "--length",
                    "8",
                    "--clear-cycle-time",
                    "--clear-comment",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertFalse(result["is_extended_frame"])
            self.assertFalse(result["is_fd"])
            self.assertEqual(result["length"], 8)
            self.assertIsNone(result["cycle_time"])
            self.assertIsNone(result["comment"])
            self.assertEqual(result["senders"], ["ECU_B", "ECU_A"])

            reloaded = load_database(source, "utf-8").messages[0]
            self.assertEqual(reloaded.frame_id, 0x456)
            self.assertEqual(reloaded.name, "Renamed")
            self.assertEqual(reloaded.senders, ["ECU_B", "ECU_A"])
            self.assertIsNone(reloaded.cycle_time)
            self.assertIsNone(reloaded.comment)

    def test_message_delete_to_separate_output_reports_signal_count(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.dbc"
            output = Path(temporary_directory) / "deleted.dbc"
            self.save_fixture(
                source,
                [
                    self.make_message(
                        length=2,
                        signals=[
                            cantools.database.can.Signal(
                                name="First", start=0, length=8
                            ),
                            cantools.database.can.Signal(
                                name="Second", start=8, length=8
                            ),
                        ],
                    )
                ],
            )
            original = source.read_bytes()

            code, out, err = run_cli(
                [
                    "--json",
                    "message",
                    "delete",
                    str(source),
                    "0x123",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertEqual(result["name"], "Status")
            self.assertEqual(result["deleted_signal_count"], 2)
            self.assertEqual(result["output"], str(output))
            self.assertIsNone(result["backup"])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(load_database(output, "utf-8").messages, [])

    def test_message_expected_errors_are_traceback_free_and_preserve_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "messages.dbc"
            self.save_fixture(
                source,
                [
                    self.make_message(),
                    self.make_message(
                        frame_id=0x124,
                        name="Other",
                        senders=[],
                        cycle_time=None,
                        comment=None,
                    ),
                ],
            )
            original = source.read_bytes()
            commands = (
                ["message", "add", str(source), "0x123", "Duplicate", "--length", "8"],
                ["message", "add", str(source), "0x125", "Status", "--length", "8"],
                ["message", "add", str(source), "0x800", "BadId", "--length", "8"],
                [
                    "message",
                    "add",
                    str(source),
                    "0x126",
                    "BadClassicLength",
                    "--length",
                    "9",
                ],
                [
                    "message",
                    "add",
                    str(source),
                    "0x126",
                    "BadFdLength",
                    "--length",
                    "65",
                    "--fd",
                ],
                [
                    "message",
                    "add",
                    str(source),
                    "0x126",
                    "BadSender",
                    "--length",
                    "8",
                    "--sender",
                    "Missing",
                ],
                ["message", "update", str(source), "Other", "--new-id", "0x123"],
                ["message", "show", str(source), "Missing"],
                ["message", "delete", str(source), "0x999"],
            )

            for command in commands:
                with self.subTest(command=command):
                    code, out, err = run_cli(["--json"] + command)
                    self.assertEqual(code, 1)
                    self.assertFalse(json.loads(out)["success"])
                    self.assertIn("error", json.loads(out))
                    self.assertNotIn("Traceback", out)
                    self.assertNotIn("Traceback", err)
                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(Path(str(source) + ".bak").exists())

    def test_shrinking_dlc_below_signal_boundary_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "messages.dbc"
            self.save_fixture(
                source,
                [
                    self.make_message(
                        length=3,
                        signals=[
                            cantools.database.can.Signal(
                                name="Wide", start=8, length=16
                            )
                        ],
                    )
                ],
            )
            original = source.read_bytes()

            code, out, err = run_cli(
                [
                    "--json",
                    "message",
                    "update",
                    str(source),
                    "Status",
                    "--length",
                    "2",
                ]
            )

            self.assertEqual(code, 1)
            self.assertFalse(json.loads(out)["success"])
            self.assertIn("error", json.loads(out))
            self.assertNotIn("Traceback", out)
            self.assertNotIn("Traceback", err)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(Path(str(source) + ".bak").exists())


if __name__ == "__main__":
    unittest.main()
