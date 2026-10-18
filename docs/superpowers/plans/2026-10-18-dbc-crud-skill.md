# DBC CRUD Agent Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, bilingual Agent Skill that performs safe CRUD operations on DBC nodes, messages, signals, and standard or extended multiplexing relationships.

**Architecture:** A `cantools`-backed service mutates an in-memory database and returns plain dictionaries. A thin `argparse` CLI exposes those operations, while a storage module validates temporary output before atomically replacing the destination and retaining backups.

**Tech Stack:** Python 3.9+, `cantools==40.7.1`, `argparse`, `unittest`, Agent Skills `SKILL.md`.

**Spec:** `docs/superpowers/specs/2026-10-18-dbc-crud-skill-design.md`

## Global Constraints

- Support Python 3.9+ and pin `cantools==40.7.1` for the verified implementation.
- Use `from __future__ import annotations` in Python modules that use modern annotation expressions.
- Provide `list`, `show`, `add`, `update`, and `delete` for nodes, messages, and signals.
- Support `init`, `summary`, `validate`, and read-only structured `compare LEFT RIGHT` at file level.
- Support standard `M`/`m<N>` multiplexing and extended `SG_MUL_VAL_` relationships supported by `cantools`.
- Use structured CLI commands rather than direct DBC text edits.
- Serialize and reload a temporary file before atomically replacing the destination.
- Retain `<source>.bak` by default for in-place mutations.
- Use stable English CLI/JSON keys, English primary documentation, and equivalent Chinese documentation.
- Expected user errors return nonzero without tracebacks.
- Do not commit `.venv`, caches, backups, or generated output.

---

### Task 1: Bootstrap, Storage, and File-Level Commands

**Files:**
- Create: `requirements.txt`, `.gitignore`, `scripts/dbc_crud.py`
- Create: `scripts/dbc_skill/__init__.py`, `errors.py`, `storage.py`, `service.py`, `formatting.py`, `cli.py`
- Create: `tests/__init__.py`, `tests/helpers.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `DBCError(Exception)`, `load_database(path: Path, encoding: str) -> Database`.
- Produces: `save_database(db: Database, source: Path, output: Path | None, encoding: str, backup: bool) -> dict`.
- Produces: `DBCService(db).summary() -> dict` and `DBCService.validate() -> dict`.
- Produces: `main(argv: list[str] | None = None) -> int` for all later CLI tasks.

- [ ] **Step 1: Declare the isolated environment and ignore generated files**

Write `requirements.txt` as:

```text
cantools==40.7.1
```

Write `.gitignore` as:

```text
.venv/
__pycache__/
*.py[cod]
*.bak
.coverage
htmlcov/
```

Run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

- [ ] **Step 2: Write failing file-command tests**

Add `run_cli(args)` to `tests/helpers.py`; it calls `cli.main(args)`, captures stdout/stderr with `redirect_stdout` and `redirect_stderr`, and returns `(exit_code, stdout, stderr)`. Add tests that create a temporary directory and assert:

```python
code, out, err = run_cli(["--json", "init", str(path)])
self.assertEqual(code, 0, err)
self.assertTrue(json.loads(out)["success"])
code, out, err = run_cli(["--json", "summary", str(path)])
self.assertEqual(json.loads(out)["result"]["message_count"], 0)
code, out, err = run_cli(["validate", str(path)])
self.assertEqual(code, 0, err)
```

Also test that `validate` on a missing file returns `1`, emits `error` in JSON mode, and does not include `Traceback`.

- [ ] **Step 3: Run the tests to verify the missing implementation fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_cli -v
```

Expected: import failure because `scripts/dbc_skill/cli.py` does not exist.

- [ ] **Step 4: Implement the service, storage, and CLI foundation**

Define `DBCError` and wrap expected parser, validation, and I/O failures with concise path-aware messages. Implement `load_database` using:

```python
return cantools.database.load_file(str(path), encoding=encoding, strict=True)
```

Implement `save_database` in this exact order:

```python
db.refresh()
destination = output or source
in_place = destination == source
descriptor, temporary_name = tempfile.mkstemp(
    prefix=f".{destination.name}.", dir=destination.parent
)
os.close(descriptor)
temporary = Path(temporary_name)
try:
    temporary.write_text(db.as_dbc_string(), encoding=encoding, newline="")
    cantools.database.load_file(str(temporary), encoding=encoding, strict=True).refresh()
    if in_place and backup and source.exists():
        shutil.copy2(source, Path(str(source) + ".bak"))
    os.replace(temporary, destination)
finally:
    if temporary.exists():
        temporary.unlink()
```

Use `tempfile.mkstemp`, close its descriptor before writing, create destination parents only when requested by `init`, and return `{"output": str(destination), "backup": backup_path_or_none}`. Implement JSON/text output, `init`, `summary`, and `validate`; route `DBCError`, `OSError`, `KeyError`, and `cantools` errors through one expected-error boundary.

- [ ] **Step 5: Verify file commands and storage behavior**

Add a storage test that patches `os.replace` to raise `OSError`, then asserts the original bytes are unchanged. Add a normal in-place save test asserting `<source>.bak` exists and contains the original bytes.

Run:

```bash
.venv/bin/python -m unittest tests.test_cli -v
```

Expected: all file-command and storage tests pass.

- [ ] **Step 6: Commit the tested foundation**

```bash
git add requirements.txt .gitignore scripts tests
git commit -m "feat: add DBC CLI foundation"
```

---

### Task 2: Node CRUD

**Files:**
- Modify: `scripts/dbc_skill/service.py`, `scripts/dbc_skill/cli.py`
- Modify: `tests/test_service.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `main(argv)`, `load_database`, `save_database`, and `DBCError` from Task 1.
- Produces: `list_nodes() -> list[dict]`, `show_node(name: str) -> dict`.
- Produces: `add_node(name: str, comment: str | None) -> dict`.
- Produces: `update_node(name: str, new_name: str | None, comment: str | None, clear_comment: bool) -> dict`.
- Produces: `delete_node(name: str) -> dict`.

- [ ] **Step 1: Write failing node service and CLI tests**

Cover add/list/show, partial update, rename, duplicate rejection, missing-node errors, JSON output, and comment clearing. Add relationship tests:

```python
service.add_node("ECU_A", None)
service.add_node("ECU_B", None)
service.db.messages.append(Message(
    frame_id=0x123, name="Status", length=8, signals=[], senders=["ECU_A"]
))
service.db.refresh()
with self.assertRaises(DBCError):
    service.delete_node("ECU_A")
service.update_node("ECU_A", "ECU_C", None, False)
self.assertEqual(service.db.messages[0].senders, ["ECU_C"])
```

- [ ] **Step 2: Run node tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_service tests.test_cli -v
```

Expected: failures because node methods and subcommands are absent.

- [ ] **Step 3: Implement node mutations and reference updates**

Use `cantools.database.can.Node(name=name, comment=comment, dbc_specifics=old.dbc)` when replacing an existing node so comments serialize correctly. Reject duplicate names. On rename, replace old names in every `message.senders` and `signal.receivers` list. On delete, collect all message and signal references and raise `DBCError` if any exist. Return dictionaries with `name` and `comment` keys.

Add CLI syntax:

```text
node list PATH
node show PATH NAME
node add PATH NAME [--comment TEXT] [--output PATH] [--no-backup]
node update PATH NAME [--new-name NAME] [--comment TEXT | --clear-comment] [--output PATH] [--no-backup]
node delete PATH NAME [--output PATH] [--no-backup]
```

- [ ] **Step 4: Run node and regression tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_service tests.test_cli -v
```

Expected: all tests pass, including a save/reload test proving node comments and renamed references survive.

- [ ] **Step 5: Commit node CRUD**

```bash
git add scripts tests
git commit -m "feat: add DBC node CRUD"
```

---

### Task 3: Message CRUD

**Files:**
- Modify: `scripts/dbc_skill/service.py`, `scripts/dbc_skill/cli.py`
- Modify: `tests/test_service.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: node lookup and storage from Tasks 1–2.
- Produces: `parse_frame_id(value: str | int) -> int`, accepting decimal and `0x` hexadecimal.
- Produces: `list_messages(name: str | None = None, sender: str | None = None) -> list[dict]`.
- Produces: `show_message(reference: str | int) -> dict`.
- Produces: `add_message(frame_id: int, name: str, length: int, senders: list[str], extended: bool, fd: bool, cycle_time: int | None, comment: str | None) -> dict`.
- Produces: `update_message(reference: str | int, **changes) -> dict` and `delete_message(reference: str | int) -> dict`.

- [ ] **Step 1: Write failing message tests**

Test decimal/hex lookup, add/list/show, renaming, ID changes, standard/extended validation, DLC changes, sender validation, comments/cycle time/CAN FD round trips, and duplicate rejection. Test deletion result:

```python
result = service.delete_message("0x123")
self.assertEqual(result["deleted_signal_count"], 2)
with self.assertRaises(DBCError):
    service.show_message("0x123")
```

Test that shrinking DLC below an existing signal boundary raises `DBCError` and leaves the source file unchanged through the CLI.

- [ ] **Step 2: Run message tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_service tests.test_cli -v
```

Expected: failures because message methods and subcommands are absent.

- [ ] **Step 3: Implement message CRUD and validation**

Construct messages with `Message(frame_id=..., name=..., length=..., signals=[], senders=..., is_extended_frame=..., is_fd=..., cycle_time=..., comment=...)`. Enforce `0 <= standard_id <= 0x7FF`, `0 <= extended_id <= 0x1FFFFFFF`, `1 <= classic_length <= 8`, and `1 <= fd_length <= 64`. Validate every sender against `db.nodes`. Check duplicate IDs and names before calling `db.refresh()` so the library's warning-based duplicate handling cannot hide errors. Refresh after updates to recalculate lookup tables and validate signal boundaries.

Add CLI syntax with optional `--new-id`, `--new-name`, `--length`, `--sender` (repeatable), `--extended`/`--standard`, `--fd`/`--classic`, `--cycle-time`, `--comment`, `--clear-cycle-time`, and `--clear-comment` for `message update`.

- [ ] **Step 4: Run message and regression tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_service tests.test_cli -v
```

Expected: all tests pass, including metadata preservation after unrelated node edits.

- [ ] **Step 5: Commit message CRUD**

```bash
git add scripts tests
git commit -m "feat: add DBC message CRUD"
```

---

### Task 4: Signal CRUD and Standard Multiplexing

**Files:**
- Modify: `scripts/dbc_skill/service.py`, `scripts/dbc_skill/cli.py`
- Create: `scripts/dbc_skill/values.py`
- Modify: `tests/test_service.py`, `tests/test_cli.py`, `tests/test_multiplexing.py`

**Interfaces:**
- Consumes: message lookup and node references from Tasks 2–3.
- Produces: `parse_integer(value: str | int) -> int`, `parse_choices(values: list[str]) -> dict[int, str]`.
- Produces: `parse_multiplexer_values(value: str) -> list[int]`, expanding comma-separated values and inclusive ranges such as `0,2-4`.
- Produces: `list_signals(message_ref, name=None) -> list[dict]`, `show_signal(message_ref, name) -> dict`.
- Produces: `add_signal(message_ref, name, **fields) -> dict`, `update_signal(message_ref, name, **changes) -> dict`, and `delete_signal(message_ref, name) -> dict`.
- Produces JSON keys `start`, `length`, `byte_order`, `is_signed`, `factor`, `offset`, `minimum`, `maximum`, `unit`, `receivers`, `choices`, `comment`, `is_multiplexer`, `multiplexer_ids`, and `multiplexer_signal`.

- [ ] **Step 1: Write failing signal and standard-multiplexing tests**

Cover all supported fields, partial updates, choice parsing (`0=Off`, `0x1=On`), receiver validation, duplicate names, comments, and UTF-8 units/comments. Add standard multiplexing:

```python
service.add_signal("0x123", "Mode", start=0, length=8, is_multiplexer=True)
service.add_signal("0x123", "Speed", start=8, length=16,
                   multiplexer_signal="Mode", multiplexer_ids=[0])
service.add_signal("0x123", "Rpm", start=8, length=16,
                   multiplexer_signal="Mode", multiplexer_ids=[1])
service.db.refresh()
self.assertEqual(service.show_signal("0x123", "Rpm")["multiplexer_ids"], [1])
```

Test that deleting `Mode` while branches exist fails, renaming `Mode` updates both branches, clearing a branch assignment works, and `db.encode_message`/`decode_message` selects the correct branch after save/reload.

- [ ] **Step 2: Run signal tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_service tests.test_multiplexing tests.test_cli -v
```

Expected: failures because signal methods and subcommands are absent.

- [ ] **Step 3: Implement value parsers and signal CRUD**

Construct `Signal` with `conversion=IdentityConversion(scale=factor, offset=offset, choices=choices, is_float=False)` when conversion fields are supplied, then set remaining public properties. Require both `--start` and `--length` for `signal add`. Enforce positive length, nonnegative start, valid byte order, minimum <= maximum, existing receivers, and unique sibling names.

For a standard branch with one multiplexer ID and no explicit parent, auto-select the message's only root selector. Require `--multiplexer-of` when the parent is ambiguous or nested. Reject assignments to missing or non-selector parents. On selector rename, update every `signal.multiplexer_signal` reference. On selector role removal or deletion, reject while dependent branches exist. Call `message.refresh(strict=True)` and `db.refresh()` after every mutation so overlap checks respect active multiplexer branches.

Add CLI options for every produced field, with `--choice RAW=LABEL`, repeatable `--receiver`, `--multiplexer`, `--multiplexer-of`, `--multiplexer-values`, and explicit `--clear-*` options for nullable fields and multiplexer assignment.

- [ ] **Step 4: Run signal, multiplexing, and regression tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_service tests.test_multiplexing tests.test_cli -v
```

Expected: all tests pass; ordinary overlapping branches in different standard multiplexer modes are accepted, while overlap within one active branch fails.

- [ ] **Step 5: Commit signal CRUD**

```bash
git add scripts tests
git commit -m "feat: add signal CRUD and multiplexing"
```

---

### Task 5: Extended Multiplexing and Serialization Guarantees

**Files:**
- Modify: `scripts/dbc_skill/service.py`, `scripts/dbc_skill/storage.py`
- Modify: `tests/test_multiplexing.py`, `tests/test_cli.py`
- Create: `examples/example.dbc`

**Interfaces:**
- Consumes: `multiplexer_signal`, `multiplexer_ids`, `save_database`, and CLI signal fields from Task 4.
- Produces: verified nested and multi-value extended-multiplexing behavior, or an explicit pre-write `DBCError` for any construct that `cantools` cannot serialize.

- [ ] **Step 1: Write failing extended-multiplexing round-trip tests**

Create a root `Mode`, a nested `SubMode` active for `Mode` values `1` and `2`, and a leaf signal active for `SubMode=3`. Assert `SubMode.multiplexer_signal == "Mode"` and `SubMode.multiplexer_ids == [1, 2]`. Save and reload, then assert the same relationships and verify `SG_MUL_VAL_` appears in the serialized DBC. Encode/decode one active nested branch and ensure an unrelated update does not remove these properties.

Also test range parsing:

```python
self.assertEqual(parse_multiplexer_values("0,2-4,0xA"), [0, 2, 3, 4, 10])
with self.assertRaises(DBCError):
    parse_multiplexer_values("4-2")
```

- [ ] **Step 2: Run extended-multiplexing tests and inspect failures**

Run:

```bash
.venv/bin/python -m unittest tests.test_multiplexing -v
```

Expected: before implementation, nested relationship validation or serialization assertions fail. If `cantools==40.7.1` rejects a requested construct, capture that exact exception and convert it into a pre-write `DBCError`; do not weaken the test by dropping multiplexer metadata.

- [ ] **Step 3: Complete extended-multiplexing validation**

Validate parent/child acyclicity, selector roles, nonnegative multiplexer values, and duplicate/invalid ranges before saving. Preserve each signal's existing `dbc` specifics during updates. In `save_database`, compare the reloaded signals' `is_multiplexer`, `multiplexer_signal`, and `multiplexer_ids` with the in-memory values and raise `DBCError` on any mismatch before `os.replace`.

- [ ] **Step 4: Verify all safety and metadata guarantees**

Add a test that patches reload validation to lose a multiplexer ID and proves the destination remains byte-for-byte unchanged. Add UTF-8 and explicit `cp936` round-trip tests for representable comments.

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: the complete suite passes and generated files outside temporary test directories are absent.

- [ ] **Step 5: Commit extended multiplexing**

```bash
git add scripts tests examples/example.dbc
git commit -m "feat: support extended DBC multiplexing"
```

---

### Task 6: Structured DBC Comparison

**Files:**
- Create: `scripts/dbc_skill/compare.py`, `tests/test_compare.py`
- Modify: `scripts/dbc_skill/cli.py`, `scripts/dbc_skill/formatting.py`

**Interfaces:**
- Consumes: strict read-only loading, entity serialization dictionaries, JSON/text output, and the expected-error boundary from Tasks 1–5.
- Produces: `compare_databases(left: Database, right: Database) -> dict`.
- Produces: `compare LEFT RIGHT`, returning `equal`, per-entity `added`, `removed`, `modified`, and `unchanged` collections, plus change counts.
- Produces modified-field objects with stable `left` and `right` values; neither input is modified.

- [ ] **Step 1: Write failing comparison tests**

Build left and right databases in temporary files. Test identical files, one added/removed/modified node, message ID/type changes, message metadata changes, signal layout/conversion/choice/comment changes, and standard and extended multiplexer changes. Assert the core shape:

```python
result = compare_databases(left_db, right_db)
self.assertFalse(result["equal"])
self.assertEqual(result["messages"]["modified"][0]["changes"]["cycle_time"], {
    "left": 100, "right": 200
})
self.assertEqual(result["signals"]["added"][0]["name"], "NewSignal")
```

Match nodes by name, messages by `(frame_id, is_extended_frame)`, and signals by parent message identity plus signal name. Verify changed message IDs appear as remove/add, while a message rename with unchanged ID is a modification. Test text and JSON CLI output, confirm successful comparisons return `0` for both equal and different files, and assert input bytes remain unchanged.

- [ ] **Step 2: Run comparison tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_compare -v
```

Expected: failures because the comparison engine and `compare` subcommand are absent.

- [ ] **Step 3: Implement structured comparison**

Reuse the service's entity-to-dictionary conversion so every supported read field is compared consistently. Produce full details for added/removed entities, field-level `left`/`right` changes for modified entities, and stable identifiers for unchanged entities. Sort output deterministically by entity type, message identity, and name. Treat floating-point values exactly as serialized by the existing dictionaries; do not introduce a new tolerance policy.

Add CLI syntax:

```text
compare LEFT RIGHT
```

A valid comparison exits `0` whether `equal` is true or false. Parser and I/O failures use the existing nonzero traceback-free boundary. Do not accept mutation, output, backup, or no-backup options for this read-only command.

- [ ] **Step 4: Run comparison and regression tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_compare tests.test_multiplexing tests.test_cli -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass, including multiplexer metadata differences and identical-file `equal: true` results.

- [ ] **Step 5: Commit DBC comparison**

```bash
git add scripts tests
git commit -m "feat: compare DBC databases"
```

---

### Task 7: Agent Skill and Bilingual Documentation

**Files:**
- Create: `SKILL.md`, `README.zh-CN.md`, `LICENSE`
- Replace: `README.md`
- Create: `references/cli-reference.md`, `references/dbc-fields.md`
- Create: `examples/workflow.md`, `examples/workflow.zh-CN.md`
- Create: `tests/test_docs.py`

**Interfaces:**
- Consumes: the implemented CLI syntax and JSON keys from Tasks 1–6.
- Produces: an installable Skill whose commands can be copied and executed from the repository root.

- [ ] **Step 1: Write failing documentation contract tests**

Assert that `SKILL.md` has YAML frontmatter with `name: dbc-crud` and an English description containing DBC, CAN, CRUD, comparison, and multiplexing. Assert it includes Chinese trigger examples, structured-CLI instructions, backup warnings, and verification steps. Assert both README files link to each other and every documented entity operation plus `compare LEFT RIGHT` appears in `references/cli-reference.md`.

- [ ] **Step 2: Run documentation tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_docs -v
```

Expected: failures because the Skill and bilingual documents are absent.

- [ ] **Step 3: Write the Skill and complete documentation**

Use `SKILL.md` to instruct agents to validate first, use `python3 scripts/dbc_crud.py`, prefer `--json`, avoid direct text edits, retain backups, and verify with `show` plus `validate`. Include English and Chinese prompts for adding nodes/messages/signals, editing scale, deleting safely, comparing two DBC files, and creating standard or extended multiplexing.

Document every command and field in `references/cli-reference.md` and `references/dbc-fields.md`. Explain comparison identity rules, field-level `left`/`right` changes, `equal`, and the zero exit code for valid equal or different inputs. Explain DBC normalization, `.bak`, `--output`, `--no-backup`, encoding, standard versus extended frame IDs, and standard versus extended multiplexing. Provide complete English and Chinese workflows using only implemented commands, including a comparison example. Add an MIT `LICENSE` and dependency/setup instructions.

- [ ] **Step 4: Execute documentation examples and run the full suite**

Run the commands from `examples/workflow.md` against a temporary copy of `examples/example.dbc`, then run the equivalent Chinese workflow and compare final `--json summary` entity counts.

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests and both workflows pass; no whitespace errors.

- [ ] **Step 5: Commit the Skill and documentation**

```bash
git add SKILL.md README.md README.zh-CN.md LICENSE references examples tests/test_docs.py
git commit -m "docs: add bilingual DBC CRUD skill"
```

---

### Task 8: End-to-End Acceptance, Review, and GitHub Delivery

**Files:**
- Verify all repository files; modify only files needed to correct discovered defects.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a clean, tested commit pushed to `origin/main` and a final report containing the commit hash and verification evidence.

- [ ] **Step 1: Recreate the clean verification environment**

Run:

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Expected: dependency installation succeeds and every test passes from the clean environment.

- [ ] **Step 2: Exercise the real CLI end to end**

In a temporary directory, run `init`; add two nodes; add a message; add an ordinary signal; add a root selector, a standard branch, a nested selector with multiple values, and a nested leaf; run `list` and `show` for every entity type; update every entity type; compare the original backup with the edited file and verify field-level differences; attempt protected deletes; delete unreferenced entities; and run `validate`. Reload the result with:

```python
import cantools
db = cantools.database.load_file(output_path, encoding="utf-8", strict=True)
db.refresh()
print(len(db.nodes), len(db.messages), sum(len(m.signals) for m in db.messages))
```

Expected: commands exit zero except intentional protected-delete checks, intentional failures exit nonzero without tracebacks, and the final counts match the CLI summary.

- [ ] **Step 3: Review the deliverable**

Run:

```bash
git status --short
git diff --check
git log --oneline --decorate -8
.venv/bin/python scripts/dbc_crud.py --help
```

Inspect the complete diff from the initial commit for accidental files, stale comments, mismatched documentation, and unverified claims. Confirm `.venv`, backups, caches, and temporary DBC output are untracked and excluded.

- [ ] **Step 4: Push the reviewed commits**

```bash
git push origin main
git rev-parse HEAD
```

Expected: GitHub accepts `main`; record the final commit hash and repository URL for the user.
