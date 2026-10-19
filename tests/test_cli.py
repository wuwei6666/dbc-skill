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

    def test_unrepresentable_signal_bounds_preserve_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_bounds = ((None, 100), (-10, None), (0, 0))
            for index, (minimum, maximum) in enumerate(invalid_bounds):
                with self.subTest(minimum=minimum, maximum=maximum):
                    source = Path(temporary_directory) / f"bounds-{index}.dbc"
                    save_database(
                        cantools.database.Database(),
                        source,
                        None,
                        "utf-8",
                        backup=False,
                    )
                    original = source.read_bytes()
                    db = cantools.database.Database()
                    db.messages.append(
                        cantools.database.can.Message(
                            frame_id=0x123,
                            name="Status",
                            length=8,
                            signals=[
                                cantools.database.can.Signal(
                                    name="State",
                                    start=0,
                                    length=8,
                                    minimum=minimum,
                                    maximum=maximum,
                                )
                            ],
                        )
                    )

                    with self.assertRaises(DBCError) as raised:
                        save_database(db, source, None, "utf-8", backup=True)

                    self.assertIn("bound", str(raised.exception).lower())
                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(Path(str(source) + ".bak").exists())

    def test_reload_losing_multiplexer_id_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "extended.dbc"
            db = cantools.database.Database()
            db.messages.append(
                cantools.database.can.Message(
                    frame_id=0x123,
                    name="Status",
                    length=8,
                    signals=[
                        cantools.database.can.Signal(
                            name="Mode", start=0, length=8, is_multiplexer=True
                        ),
                        cantools.database.can.Signal(
                            name="SubMode",
                            start=8,
                            length=8,
                            is_multiplexer=True,
                            multiplexer_signal="Mode",
                            multiplexer_ids=[1, 2],
                        ),
                        cantools.database.can.Signal(
                            name="Payload",
                            start=16,
                            length=16,
                            multiplexer_signal="SubMode",
                            multiplexer_ids=[3],
                        ),
                    ],
                )
            )
            save_database(db, source, None, "utf-8", backup=False)
            original = source.read_bytes()
            real_load_file = cantools.database.load_file

            def load_and_lose_multiplexer_id(path, **kwargs):
                reloaded = real_load_file(path, **kwargs)
                sub_mode = next(
                    signal
                    for signal in reloaded.messages[0].signals
                    if signal.name == "SubMode"
                )
                sub_mode.multiplexer_ids = [1]
                return reloaded

            with mock.patch(
                "scripts.dbc_skill.storage.cantools.database.load_file",
                side_effect=load_and_lose_multiplexer_id,
            ):
                with self.assertRaises(DBCError) as raised:
                    save_database(db, source, None, "utf-8", backup=True)

            self.assertIn("multiplexer", str(raised.exception).lower())
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(Path(str(source) + ".bak").exists())

    def test_cantools_serialization_errors_preserve_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            for index, exception in enumerate(
                (TypeError("unsupported construct"), KeyError("corrupt metadata"))
            ):
                with self.subTest(exception=type(exception).__name__):
                    source = Path(temporary_directory) / f"serialize-{index}.dbc"
                    original = cantools.database.Database().as_dbc_string().encode(
                        "utf-8"
                    )
                    source.write_bytes(original)
                    db = load_database(source, "utf-8")

                    with mock.patch(
                        "scripts.dbc_skill.storage.Database.as_dbc_string",
                        side_effect=exception,
                    ):
                        with self.assertRaises(DBCError):
                            save_database(db, source, None, "utf-8", backup=True)

                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(Path(str(source) + ".bak").exists())

    def test_representable_comments_round_trip_with_explicit_encodings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            for encoding in ("utf-8", "cp936"):
                with self.subTest(encoding=encoding):
                    source = Path(temporary_directory) / f"comments-{encoding}.dbc"
                    comment = "温度 comment"
                    db = cantools.database.Database()
                    db.nodes.append(
                        cantools.database.can.Node(name="ECU", comment=comment)
                    )
                    db.messages.append(
                        cantools.database.can.Message(
                            frame_id=0x123,
                            name="Status",
                            length=8,
                            senders=["ECU"],
                            comment=comment,
                            signals=[
                                cantools.database.can.Signal(
                                    name="State",
                                    start=0,
                                    length=8,
                                    receivers=["ECU"],
                                    comment=comment,
                                )
                            ],
                        )
                    )

                    save_database(db, source, None, encoding, backup=False)
                    reloaded = load_database(source, encoding)

                    self.assertEqual(reloaded.nodes[0].comment, comment)
                    self.assertEqual(reloaded.messages[0].comment, comment)
                    self.assertEqual(reloaded.messages[0].signals[0].comment, comment)


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

            reloaded = load_database(source, "utf-8").messages[0]
            self.assertTrue(reloaded.is_extended_frame)
            self.assertTrue(reloaded.is_fd)

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
            self.assertFalse(reloaded.is_extended_frame)
            self.assertFalse(reloaded.is_fd)

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


class SignalCommandTests(unittest.TestCase):
    def save_fixture(self, path, signals=None):
        db = cantools.database.Database()
        db.nodes.extend(
            [
                cantools.database.can.Node(name="ECU_A"),
                cantools.database.can.Node(name="ECU_B"),
            ]
        )
        db.messages.append(
            cantools.database.can.Message(
                frame_id=0x123,
                name="Status",
                length=8,
                signals=signals or [],
                senders=["ECU_A"],
            )
        )
        save_database(db, path, None, "utf-8", backup=True)

    def test_signal_add_list_show_json_utf8_and_default_backup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "signals.dbc"
            self.save_fixture(source)
            original = source.read_bytes()

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "add",
                    str(source),
                    "0x123",
                    "Temperature",
                    "--start",
                    "7",
                    "--length",
                    "16",
                    "--byte-order",
                    "big_endian",
                    "--signed",
                    "--factor",
                    "0.5",
                    "--offset",
                    "-40",
                    "--minimum",
                    "-40",
                    "--maximum",
                    "215",
                    "--unit",
                    "°C",
                    "--receiver",
                    "ECU_A",
                    "--receiver",
                    "ECU_B",
                    "--choice",
                    "0=Off",
                    "--choice",
                    "0x1=On",
                    "--comment",
                    "温度 comment",
                ]
            )
            self.assertEqual(code, 0, err)
            expected = {
                "name": "Temperature",
                "start": 7,
                "length": 16,
                "byte_order": "big_endian",
                "is_signed": True,
                "factor": 0.5,
                "offset": -40.0,
                "minimum": -40.0,
                "maximum": 215.0,
                "unit": "°C",
                "receivers": ["ECU_A", "ECU_B"],
                "choices": {"0": "Off", "1": "On"},
                "comment": "温度 comment",
                "is_multiplexer": False,
                "multiplexer_ids": None,
                "multiplexer_signal": None,
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
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "Second",
                    "--start",
                    "16",
                    "--length",
                    "8",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)

            code, out, err = run_cli(
                ["--json", "signal", "list", str(source), "291", "--name", "Temperature"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"], {"signals": [expected]})

            code, out, err = run_cli(
                ["--json", "signal", "show", str(source), "Status", "Temperature"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"], expected)

            code, out, err = run_cli(["signal", "list", str(source), "Status"])
            self.assertEqual(code, 0, err)
            self.assertIn("Temperature", out)
            self.assertNotIn("Traceback", err)

    def test_signal_update_clear_and_delete_to_separate_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.dbc"
            output = Path(temporary_directory) / "deleted.dbc"
            self.save_fixture(source)
            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "State",
                    "--start",
                    "0",
                    "--length",
                    "8",
                    "--factor",
                    "2",
                    "--offset",
                    "1",
                    "--minimum",
                    "0",
                    "--maximum",
                    "100",
                    "--unit",
                    "rpm",
                    "--receiver",
                    "ECU_A",
                    "--choice",
                    "0=Off",
                    "--comment",
                    "Original",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "update",
                    str(source),
                    "0x123",
                    "State",
                    "--new-name",
                    "Renamed",
                    "--start",
                    "8",
                    "--length",
                    "16",
                    "--byte-order",
                    "little_endian",
                    "--signed",
                    "--factor",
                    "0.25",
                    "--offset",
                    "-1",
                    "--minimum",
                    "-10",
                    "--maximum",
                    "10",
                    "--unit",
                    "V",
                    "--receiver",
                    "ECU_B",
                    "--choice",
                    "0x0=Low",
                    "--comment",
                    "Updated",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertEqual(result["name"], "Renamed")
            self.assertEqual(result["start"], 8)
            self.assertEqual(result["length"], 16)
            self.assertTrue(result["is_signed"])
            self.assertEqual(result["factor"], 0.25)
            self.assertEqual(result["offset"], -1.0)
            self.assertEqual(result["minimum"], -10.0)
            self.assertEqual(result["maximum"], 10.0)
            self.assertEqual(result["unit"], "V")
            self.assertEqual(result["receivers"], ["ECU_B"])
            self.assertEqual(result["choices"], {"0": "Low"})
            self.assertEqual(result["comment"], "Updated")

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "update",
                    str(source),
                    "Status",
                    "Renamed",
                    "--unsigned",
                    "--clear-minimum",
                    "--clear-maximum",
                    "--clear-unit",
                    "--clear-receivers",
                    "--clear-choices",
                    "--clear-comment",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertFalse(result["is_signed"])
            self.assertIsNone(result["minimum"])
            self.assertIsNone(result["maximum"])
            self.assertIsNone(result["unit"])
            self.assertEqual(result["receivers"], [])
            self.assertIsNone(result["choices"])
            self.assertIsNone(result["comment"])
            self.assertEqual(result["factor"], 0.25)

            before_delete = source.read_bytes()
            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "delete",
                    str(source),
                    "Status",
                    "Renamed",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertEqual(result["name"], "Renamed")
            self.assertEqual(result["output"], str(output))
            self.assertIsNone(result["backup"])
            self.assertEqual(source.read_bytes(), before_delete)
            self.assertEqual(load_database(output, "utf-8").messages[0].signals, [])

    def test_one_sided_bound_changes_fail_and_preserve_source(self):
        operations = (
            ("update", "State", ("--clear-minimum",)),
            ("update", "State", ("--clear-maximum",)),
            ("add", "OnlyMaximum", ("--maximum", "100")),
            ("add", "OnlyMinimum", ("--minimum", "-10")),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            for index, (operation, name, options) in enumerate(operations):
                with self.subTest(operation=operation, name=name, options=options):
                    source = Path(temporary_directory) / f"bounds-{index}.dbc"
                    self.save_fixture(source)
                    code, out, err = run_cli(
                        [
                            "--json",
                            "signal",
                            "add",
                            str(source),
                            "Status",
                            "State",
                            "--start",
                            "0",
                            "--length",
                            "8",
                            "--minimum",
                            "-10",
                            "--maximum",
                            "100",
                            "--no-backup",
                        ]
                    )
                    self.assertEqual(code, 0, err)
                    original = source.read_bytes()
                    command = [
                        "--json",
                        "signal",
                        operation,
                        str(source),
                        "Status",
                        name,
                    ]
                    if operation == "add":
                        command.extend(("--start", "8", "--length", "8"))
                    command.extend(options)

                    code, out, err = run_cli(command)

                    self.assertEqual(code, 1)
                    payload = json.loads(out)
                    self.assertFalse(payload["success"])
                    self.assertIn("bound", payload["error"].lower())
                    self.assertNotIn("Traceback", out)
                    self.assertNotIn("Traceback", err)
                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(Path(str(source) + ".bak").exists())

    def test_absent_and_explicit_zero_bounds_survive_cli_reload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "bounds.dbc"
            self.save_fixture(source)
            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "State",
                    "--start",
                    "0",
                    "--length",
                    "8",
                    "--minimum",
                    "-10",
                    "--maximum",
                    "100",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "update",
                    str(source),
                    "Status",
                    "State",
                    "--clear-minimum",
                    "--clear-maximum",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            state = load_database(source, "utf-8").messages[0].signals[0]
            self.assertIsNone(state.minimum)
            self.assertIsNone(state.maximum)

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "update",
                    str(source),
                    "Status",
                    "State",
                    "--minimum",
                    "0",
                    "--maximum",
                    "0",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            state = load_database(source, "utf-8").messages[0].signals[0]
            self.assertEqual(state.minimum, 0.0)
            self.assertEqual(state.maximum, 0.0)

    def test_multiplexer_commands_rename_clear_and_encode_decode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "multiplexed.dbc"
            self.save_fixture(source)
            commands = (
                ["Mode", "0", "8", "--multiplexer"],
                ["Speed", "8", "16", "--multiplexer-values", "0"],
                [
                    "Rpm",
                    "8",
                    "16",
                    "--multiplexer-of",
                    "Mode",
                    "--multiplexer-values",
                    "1",
                ],
            )
            for name, start, length, *options in commands:
                code, out, err = run_cli(
                    [
                        "--json",
                        "signal",
                        "add",
                        str(source),
                        "Status",
                        name,
                        "--start",
                        start,
                        "--length",
                        length,
                        "--no-backup",
                    ]
                    + options
                )
                self.assertEqual(code, 0, err)

            code, out, err = run_cli(
                ["--json", "signal", "show", str(source), "Status", "Rpm"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"]["multiplexer_signal"], "Mode")
            self.assertEqual(json.loads(out)["result"]["multiplexer_ids"], [1])

            db = load_database(source, "utf-8")
            speed_data = db.encode_message(0x123, {"Mode": 0, "Speed": 0x1234})
            rpm_data = db.encode_message(0x123, {"Mode": 1, "Rpm": 0x5678})
            self.assertEqual(
                db.decode_message(0x123, speed_data), {"Mode": 0, "Speed": 0x1234}
            )
            self.assertEqual(
                db.decode_message(0x123, rpm_data), {"Mode": 1, "Rpm": 0x5678}
            )

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "update",
                    str(source),
                    "Status",
                    "Mode",
                    "--new-name",
                    "State",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            code, out, err = run_cli(
                ["--json", "signal", "show", str(source), "Status", "Speed"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["result"]["multiplexer_signal"], "State")

            original = source.read_bytes()
            code, out, err = run_cli(
                ["--json", "signal", "delete", str(source), "Status", "State"]
            )
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(out)["success"])
            self.assertEqual(source.read_bytes(), original)
            self.assertNotIn("Traceback", out)
            self.assertNotIn("Traceback", err)

            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "delete",
                    str(source),
                    "Status",
                    "Rpm",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            code, out, err = run_cli(
                [
                    "--json",
                    "signal",
                    "update",
                    str(source),
                    "Status",
                    "Speed",
                    "--clear-multiplexer",
                    "--no-backup",
                ]
            )
            self.assertEqual(code, 0, err)
            result = json.loads(out)["result"]
            self.assertIsNone(result["multiplexer_signal"])
            self.assertIsNone(result["multiplexer_ids"])

    def test_signal_expected_errors_preserve_source_without_tracebacks(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "errors.dbc"
            self.save_fixture(
                source,
                [
                    cantools.database.can.Signal(
                        name="Existing", start=0, length=8, receivers=["ECU_A"]
                    )
                ],
            )
            original = source.read_bytes()
            commands = (
                [
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "Existing",
                    "--start",
                    "8",
                    "--length",
                    "8",
                ],
                [
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "BadReceiver",
                    "--start",
                    "8",
                    "--length",
                    "8",
                    "--receiver",
                    "Missing",
                ],
                [
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "BadRange",
                    "--start",
                    "8",
                    "--length",
                    "8",
                    "--minimum",
                    "2",
                    "--maximum",
                    "1",
                ],
                [
                    "signal",
                    "add",
                    str(source),
                    "Status",
                    "BadChoice",
                    "--start",
                    "8",
                    "--length",
                    "8",
                    "--choice",
                    "missing-separator",
                ],
                [
                    "signal",
                    "update",
                    str(source),
                    "Status",
                    "Existing",
                    "--start",
                    "-1",
                ],
                ["signal", "show", str(source), "Status", "Missing"],
                ["signal", "delete", str(source), "Status", "Missing"],
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


if __name__ == "__main__":
    unittest.main()
