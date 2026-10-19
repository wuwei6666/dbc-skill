# DBC and Excel Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lossless semantic DBC ↔ `.xlsx` conversion for nodes, messages, signals, choices, and standard or extended multiplexing.

**Architecture:** A focused `excel.py` module owns workbook schema, styling, parsing, and atomic workbook writes. Export uses a public `DBCService.entity_snapshot()`; import rebuilds a `cantools Database` through existing `DBCService` mutation methods and persists through existing `save_database`.

**Tech Stack:** Python 3.9+, `cantools==40.7.1`, `openpyxl==3.1.5`, `argparse`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-19-dbc-excel-conversion-design.md`

## Global Constraints

- Support Python 3.9+ and pin `cantools==40.7.1` plus `openpyxl==3.1.5`.
- Add `excel export INPUT.dbc OUTPUT.xlsx` and `excel import INPUT.xlsx OUTPUT.dbc`.
- Use workbook format `dbc-skill-excel`, schema version `1`, and sheets `Metadata`, `Nodes`, `Messages`, `Signals`, and `Choices`.
- Preserve nodes, messages, signals, comments, choices, cycle time, CAN FD status, standard and extended multiplexing, and supported signal bounds.
- Use `DBCService` and `save_database` for DBC validation and persistence; do not introduce canmatrix or a second DBC serializer.
- Reject legacy `.xls`, malformed workbooks, formulas in structured cells, missing parents, duplicate identities, and unknown schema versions without replacing destinations.
- Treat text beginning with `=`, `+`, `-`, or `@` as strings on export.
- Use stable English CLI/JSON keys, English primary documentation, and equivalent Chinese documentation.
- Expected user errors return nonzero without tracebacks.
- Do not commit virtual environments, generated workbooks, caches, backups, or temporary output.

---

### Task 1: Entity Snapshot and Excel Export Engine

**Files:**
- Modify: `requirements.txt`
- Modify: `scripts/dbc_skill/service.py`
- Modify: `scripts/dbc_skill/storage.py`
- Create: `scripts/dbc_skill/excel.py`
- Create: `tests/test_excel.py`

**Interfaces:**
- Consumes: existing `Database`, `DBCService`, and `_supported_metadata` behavior.
- Produces: `DBCService.entity_snapshot() -> dict` with sorted `nodes`, `messages`, and `signals` lists identical to the current storage verification snapshot.
- Produces: `export_database(db: Database, output: Path) -> dict`.
- Produces: workbook constants `FORMAT_NAME`, `SCHEMA_VERSION`, `METADATA_HEADERS`, `NODE_HEADERS`, `MESSAGE_HEADERS`, `SIGNAL_HEADERS`, and `CHOICE_HEADERS`.

- [ ] **Step 1: Add the dependency and write failing snapshot/export tests**

Set `requirements.txt` to:

```text
cantools==40.7.1
openpyxl==3.1.5
```

Install it in `.venv`. In `tests/test_excel.py`, build a database through `DBCService` with a node comment containing `=not-a-formula`, an empty message, and a standard-multiplexed signal. Assert `entity_snapshot()` has the same shape and ordering currently produced by storage verification. Call `export_database`, reopen the workbook, and assert all five sheets, exact headers, metadata values, canonical `0x` IDs, boolean cell values, multiplexer fields, and that the comment cell has `data_type == "s"`.

- [ ] **Step 2: Run export tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_excel -v
```

Expected: `ModuleNotFoundError` for `scripts.dbc_skill.excel` and missing `entity_snapshot`.

- [ ] **Step 3: Implement the public snapshot and workbook export**

Move the current sorting/dictionary logic from `storage._supported_metadata` into `DBCService.entity_snapshot()` without changing its output; make storage call the new public method. In `excel.py`, define the exact schema headers from the spec and implement:

```python
def export_database(db: Database, output: Path) -> dict:
    snapshot = DBCService(db).entity_snapshot()
    # Build Metadata, Nodes, Messages, Signals, and Choices sheets.
    # Save a temporary .xlsx, reopen it with load_workbook, preserve an
    # existing destination mode, then os.replace it atomically.
```

Use `cell.data_type = "s"` after assigning structured text. Add freeze panes, filters, column widths, boolean and byte-order dropdowns, and deterministic ordering. Return `{"output": str(output), "format": FORMAT_NAME, "schema_version": SCHEMA_VERSION, "node_count": ..., "message_count": ..., "signal_count": ..., "warnings": []}`.

- [ ] **Step 4: Verify export and storage regressions**

Add tests that patch `os.replace` in `excel.py` to raise `OSError` and prove an existing workbook remains byte-for-byte unchanged. Run:

```bash
.venv/bin/python -m unittest tests.test_excel tests.test_cli tests.test_service tests.test_multiplexing -v
```

Expected: all selected export, storage, CRUD, and multiplexing regressions pass.

- [ ] **Step 5: Commit the export engine**

```bash
git add requirements.txt scripts/dbc_skill/service.py scripts/dbc_skill/storage.py scripts/dbc_skill/excel.py tests/test_excel.py
git commit -m "feat: export DBC databases to Excel"
```

---

### Task 2: Excel Import Engine and Validation

**Files:**
- Modify: `scripts/dbc_skill/excel.py`
- Modify: `tests/test_excel.py`

**Interfaces:**
- Consumes: `DBCService.add_node`, `add_message`, `add_signal`, workbook constants, and export behavior from Task 1.
- Produces: `database_from_workbook(path: Path) -> tuple[Database, list[str]]`.
- Produces row-aware `DBCError` messages containing sheet, row, and field.

- [ ] **Step 1: Write failing import and validation tests**

Create a workbook with all schema sheets, one node, one empty message, one multiplexed message, Unicode comments, a choice label containing commas and semicolons, and numeric/boolean cells in multiple accepted forms. Assert the imported database snapshot equals the expected snapshot. Add a matrix of malformed workbooks: missing `Signals`, duplicate headers, wrong schema version, formula in a structured cell, duplicate message identity, missing parent message, missing receiver node, duplicate choice raw value, invalid boolean, and invalid multiplexer range. Each must raise `DBCError` before any DBC is returned.

- [ ] **Step 2: Run import tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_excel -v
```

Expected: failures because `database_from_workbook` is absent.

- [ ] **Step 3: Implement workbook parsing and database construction**

Implement header/index validation, metadata validation, structured cell coercion, list parsing, formula rejection, duplicate/reference tracking, and row-aware error collection. Build an empty `Database(version=metadata.get("dbc_version") or None)`, then call `DBCService.add_node`, `add_message`, and `add_signal` in schema order. Group `Choices` rows by `(message_frame_id, message_is_extended_frame, signal_name)` and pass the resulting `choices` dictionary to the matching `add_signal` call. Ignore unknown extra sheets by appending their names to `warnings`; reject unknown required-sheet columns.

- [ ] **Step 4: Verify import and export round trip at module level**

Add a module-level DBC → workbook → database test using the repository example and assert `compare_databases(original, imported)["equal"] is True`. Run:

```bash
.venv/bin/python -m unittest tests.test_excel tests.test_compare -v
```

Expected: all tests pass; every malformed workbook fails before a destination is created.

- [ ] **Step 5: Commit the import engine**

```bash
git add scripts/dbc_skill/excel.py tests/test_excel.py
git commit -m "feat: import DBC databases from Excel"
```

---

### Task 3: Excel CLI and End-to-End Round Trip

**Files:**
- Modify: `scripts/dbc_skill/cli.py`
- Modify: `scripts/dbc_skill/formatting.py` if its generic text rendering cannot already display conversion results
- Modify: `tests/test_excel.py`

**Interfaces:**
- Consumes: `export_database`, `database_from_workbook`, `load_database`, and `save_database`.
- Produces: CLI commands `excel export INPUT.dbc OUTPUT.xlsx` and `excel import INPUT.xlsx OUTPUT.dbc` with JSON result keys from the spec.

- [ ] **Step 1: Write failing CLI round-trip tests**

Use `tests.helpers.run_cli`. Export `examples/example.dbc` to a temporary `.xlsx`, import it to `roundtrip.dbc`, and compare the two files through the existing `compare` command. Assert exit code `0`, `result.equal is True`, and JSON keys `input`, `output`, `format`, `schema_version`, `node_count`, `message_count`, `signal_count`, and `warnings`. Add text-mode output checks, `.xls` rejection, malformed workbook failure, and source/destination byte preservation tests.

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_excel -v
```

Expected: argparse reports that `excel` is an invalid command.

- [ ] **Step 3: Register and dispatch the commands**

Add an `excel` subparser with nested `export` and `import` commands. Dispatch export through `load_database` and `export_database`. Dispatch import through `database_from_workbook` and `save_database(db, source=input_path, output=output_path, encoding=args.encoding, backup=False)`. Merge conversion metadata and storage output keys into the existing result envelope. Keep expected errors inside the existing traceback-free boundary.

- [ ] **Step 4: Verify real CLI behavior and regression suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_excel -v
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass, including the repository example's nested extended multiplexing after a real CLI round trip.

- [ ] **Step 5: Commit the CLI integration**

```bash
git add scripts/dbc_skill/cli.py scripts/dbc_skill/formatting.py tests/test_excel.py
git commit -m "feat: add Excel conversion commands"
```

---

### Task 4: Skill and Bilingual Conversion Documentation

**Files:**
- Modify: `SKILL.md`, `README.md`, `README.zh-CN.md`
- Modify: `references/cli-reference.md`, `references/dbc-fields.md`
- Modify: `examples/workflow.md`, `examples/workflow.zh-CN.md`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: implemented CLI, workbook schema, result keys, and validation rules from Tasks 1–3.
- Produces: documented bilingual commands and a complete executable round-trip workflow.

- [ ] **Step 1: Write failing documentation contract tests**

Extend `tests/test_docs.py` to require `excel export INPUT.dbc OUTPUT.xlsx`, `excel import INPUT.xlsx OUTPUT.dbc`, all five sheet names, every schema column, `format`, `schema_version`, `warnings`, `.xlsx`-only behavior, formula-safety guidance, and bilingual round-trip examples ending in `compare`.

- [ ] **Step 2: Run documentation tests and verify failure**

Run:

```bash
.venv/bin/python -m unittest tests.test_docs -v
```

Expected: missing Excel conversion fragments.

- [ ] **Step 3: Write the documentation**

Document the workbook contract, boolean/ID/multiplexer syntax, choices sheet, unknown-sheet warnings, replacement behavior, formula safety, `.xls` rejection, and semantic round-trip verification. Add Chinese trigger examples to `SKILL.md` and complete English/Chinese workflow steps that export, import, compare, and validate. Update dependency setup to `cantools==40.7.1` and `openpyxl==3.1.5`.

- [ ] **Step 4: Execute the documented workflows and full suite**

Run both bilingual workflow scripts against temporary directories, then:

```bash
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests, workflows, and whitespace checks pass.

- [ ] **Step 5: Commit the documentation**

```bash
git add SKILL.md README.md README.zh-CN.md references examples tests/test_docs.py
git commit -m "docs: document DBC Excel conversion"
```

---

### Task 5: Final Verification, Review, and GitHub Delivery

**Files:**
- Verify all repository files; modify only files needed to correct review findings.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a clean, reviewed commit pushed to `origin/main`.

- [ ] **Step 1: Recreate the clean environment**

Run:

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Expected: both pinned dependencies install and the complete suite passes.

- [ ] **Step 2: Exercise real conversion end to end**

In a temporary directory, export the repository example to `.xlsx`; reopen it with `openpyxl`; import it to a new DBC; run `compare`; validate the result; and verify nested multiplexer encode/decode still works. Also export a Unicode/choices-rich file and verify source and destination preservation for malformed input.

- [ ] **Step 3: Review the complete deliverable**

Run:

```bash
git status --short
git diff --check
git log --oneline --decorate -10
.venv/bin/python scripts/dbc_crud.py excel --help
```

Dispatch the final whole-deliverable code reviewer and fix all Critical/Important findings with regression tests.

- [ ] **Step 4: Push the reviewed work**

After a fresh full-suite run and clean status:

```bash
git push origin main
git rev-parse HEAD
```

Expected: GitHub accepts `main`; record the final commit hash and repository URL.
