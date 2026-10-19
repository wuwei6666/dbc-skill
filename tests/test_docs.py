import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_document(relative_path):
    path = ROOT / relative_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


class DocumentationContractTests(unittest.TestCase):
    def assert_contains_all(self, text, fragments):
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_skill_frontmatter_has_discovery_triggers(self):
        skill = read_document("SKILL.md")
        match = re.match(r"\A---\n(.*?)\n---\n", skill, re.DOTALL)

        self.assertIsNotNone(match, "SKILL.md must start with YAML frontmatter")
        frontmatter = match.group(1)
        self.assertRegex(frontmatter, r"(?m)^name: dbc-crud$")
        description_match = re.search(r"(?m)^description: (.+)$", frontmatter)
        self.assertIsNotNone(description_match)
        description = description_match.group(1)
        self.assertTrue(description.startswith("Use when "))
        self.assert_contains_all(
            description, ("DBC", "CAN", "CRUD", "comparison", "multiplexing")
        )

    def test_skill_has_bilingual_prompts_and_safe_cli_guidance(self):
        skill = read_document("SKILL.md")

        self.assert_contains_all(
            skill,
            (
                "python3 scripts/dbc_crud.py",
                "--json",
                "--output",
                "--no-backup",
                ".bak",
                "show",
                "validate",
                "Add a node",
                "Add a message",
                "Add a signal",
                "Edit a signal's scale",
                "Delete safely",
                "Compare two DBC files",
                "Create standard multiplexing",
                "Create extended multiplexing",
                "添加节点",
                "添加报文",
                "添加信号",
                "修改信号比例",
                "安全删除",
                "比较两个 DBC",
                "标准多路复用",
                "扩展多路复用",
                "## Quick reference",
                "## Common mistakes",
            ),
        )

    def test_readmes_cross_link_and_cover_setup_and_safety(self):
        english = read_document("README.md")
        chinese = read_document("README.zh-CN.md")

        self.assertIn("README.zh-CN.md", english)
        self.assertIn("README.md", chinese)
        for document in (english, chinese):
            self.assert_contains_all(
                document,
                (
                    "requirements.txt",
                    "python3 scripts/dbc_crud.py",
                    "references/cli-reference.md",
                    "references/dbc-fields.md",
                    ".bak",
                    "--output",
                ),
            )
        self.assertIn("examples/workflow.md", english)
        self.assertIn("examples/workflow.zh-CN.md", chinese)

    def test_cli_reference_covers_every_command(self):
        reference = read_document("references/cli-reference.md")
        operations = (
            "init PATH",
            "summary PATH",
            "validate PATH",
            "compare LEFT RIGHT",
            "node list PATH",
            "node show PATH NAME",
            "node add PATH NAME",
            "node update PATH NAME",
            "node delete PATH NAME",
            "message list PATH",
            "message show PATH REFERENCE",
            "message add PATH FRAME_ID NAME",
            "message update PATH REFERENCE",
            "message delete PATH REFERENCE",
            "signal list PATH MESSAGE_REF",
            "signal show PATH MESSAGE_REF NAME",
            "signal add PATH MESSAGE_REF NAME",
            "signal update PATH MESSAGE_REF NAME",
            "signal delete PATH MESSAGE_REF NAME",
        )

        self.assert_contains_all(reference, operations)

    def test_cli_reference_covers_every_option(self):
        reference = read_document("references/cli-reference.md")
        options = (
            "--json",
            "--encoding",
            "--output",
            "--no-backup",
            "--comment",
            "--new-name",
            "--clear-comment",
            "--name",
            "--sender",
            "--length",
            "--extended",
            "--fd",
            "--cycle-time",
            "--new-id",
            "--standard",
            "--classic",
            "--clear-cycle-time",
            "--start",
            "--byte-order",
            "--signed",
            "--unsigned",
            "--multiplexer",
            "--no-multiplexer",
            "--factor",
            "--offset",
            "--minimum",
            "--maximum",
            "--clear-minimum",
            "--clear-maximum",
            "--unit",
            "--clear-unit",
            "--receiver",
            "--clear-receivers",
            "--choice",
            "--clear-choices",
            "--clear-multiplexer",
            "--multiplexer-of",
            "--multiplexer-values",
        )

        self.assert_contains_all(reference, options)

    def test_multiplexer_value_and_range_syntax_is_explicit(self):
        for path in ("SKILL.md", "references/cli-reference.md"):
            document = read_document(path)
            self.assert_contains_all(
                document,
                (
                    "--multiplexer-values 1,2",
                    "--multiplexer-values 2-4",
                    "0,2-4,0xA",
                    "comma-separated",
                    "inclusive",
                ),
            )

    def test_signal_bound_and_normalization_limits_are_documented(self):
        fields = read_document("references/dbc-fields.md")
        skill = read_document("SKILL.md")

        self.assert_contains_all(
            fields,
            (
                "one-sided",
                "set or clear both",
                "integer 0|0",
                "floating-point zero",
                "0.0",
                "SG_MUL_VAL_",
            ),
        )
        self.assert_contains_all(
            skill,
            ("not byte-for-byte", "normalize", ".bak", "retain backups"),
        )

    def test_dbc_field_reference_covers_json_keys(self):
        fields = read_document("references/dbc-fields.md")
        keys = (
            "success",
            "operation",
            "result",
            "error",
            "version",
            "node_count",
            "message_count",
            "signal_count",
            "valid",
            "name",
            "comment",
            "frame_id",
            "length",
            "senders",
            "is_extended_frame",
            "is_fd",
            "cycle_time",
            "signals",
            "start",
            "byte_order",
            "is_signed",
            "factor",
            "offset",
            "minimum",
            "maximum",
            "unit",
            "receivers",
            "choices",
            "is_multiplexer",
            "multiplexer_ids",
            "multiplexer_signal",
            "deleted_signal_count",
            "output",
            "backup",
        )

        self.assert_contains_all(fields, keys)

    def test_comparison_example_is_real_json_with_exact_paths(self):
        reference = read_document("references/cli-reference.md")
        self.assertIn("<!-- comparison-json-example -->", reference)
        example_section = reference.split("<!-- comparison-json-example -->", 1)[1]
        match = re.search(r"```json\n(.*?)\n```", example_section, re.DOTALL)

        self.assertIsNotNone(match, "comparison example must be a JSON code block")
        payload = json.loads(match.group(1))
        self.assertTrue(payload["success"])
        self.assertEqual(payload["operation"], "compare")
        result = payload["result"]
        self.assertFalse(result["equal"])
        self.assertTrue(result["messages"]["added"])
        self.assertTrue(result["signals"]["added"])
        cycle_change = result["messages"]["modified"][0]["changes"]["cycle_time"]
        self.assertEqual(set(cycle_change), {"left", "right"})
        self.assert_contains_all(
            reference,
            (
                "result.equal",
                "result.messages.added",
                "result.signals.added",
                "result.messages.modified[0].changes.cycle_time.left",
                "result.messages.modified[0].changes.cycle_time.right",
                "exit code 0",
            ),
        )

    def test_bilingual_workflows_are_complete_and_non_overwriting(self):
        english = read_document("examples/workflow.md")
        chinese = read_document("examples/workflow.zh-CN.md")

        for document in (english, chinese):
            self.assert_contains_all(
                document,
                (
                    "mktemp -d",
                    "cp examples/example.dbc",
                    "CLI=(python3 scripts/dbc_crud.py --json)",
                    "--output",
                    "node add",
                    "message add",
                    "signal add",
                    "signal update",
                    "node delete",
                    "signal delete",
                    "compare",
                    "show",
                    "validate",
                    "summary",
                    "--multiplexer-values 1,2",
                    "--multiplexer-values 4-5",
                ),
            )

    def test_license_is_mit(self):
        license_text = read_document("LICENSE")

        self.assert_contains_all(
            license_text,
            (
                "MIT License",
                "Permission is hereby granted, free of charge",
                'THE SOFTWARE IS PROVIDED "AS IS"',
            ),
        )


if __name__ == "__main__":
    unittest.main()
