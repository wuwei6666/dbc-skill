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


if __name__ == "__main__":
    unittest.main()
