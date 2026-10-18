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


if __name__ == "__main__":
    unittest.main()
