# DBC and Excel Bidirectional Conversion Design

Date: 2026-10-19
Status: Approved for implementation

## 1. Purpose

Add reliable bidirectional conversion between DBC files and editable Excel `.xlsx` workbooks to the existing `dbc-crud` Agent Skill. The conversion must preserve the same primary entity model as the existing CRUD and comparison features: nodes, messages, signals, common metadata, and standard or extended multiplexing.

## 2. Research Summary

Several existing implementations were evaluated before choosing this design.

- `canmatrix` is the most mature general CAN database converter and documents `.xls(x)` support, but a local round-trip experiment with `canmatrix==1.3.2` showed that its `.xlsx` module was unavailable in the installed environment and its `.xls` path discarded the repository's complex multiplexed example frame. Its Excel format is primarily a human-readable matrix, estimates DLC on import, and does not preserve complex multiplexing.
- `HongleiHuang-amd/dbc2excel` is a useful one-way DBC-to-Excel GUI tool but has no reverse conversion and uses a different dependency and parsing model.
- `HuakeZhBo/dbcCov` offers bidirectional conversion but uses a simple text parser and does not implement value tables or the multiplexing fidelity required here.
- `tujinyu3517/can-csv-to-dbc` has a useful protocol-column design, but it is CSV-oriented and supports only single-level multiplexing.

The conclusion is to implement a canonical `.xlsx` format with `openpyxl` while retaining `cantools` and the existing `DBCService` as the only DBC mutation and validation engine.

## 3. Goals

- Add `excel export INPUT.dbc OUTPUT.xlsx`.
- Add `excel import INPUT.xlsx OUTPUT.dbc`.
- Preserve nodes, messages, signals, comments, choices, cycle time, CAN FD status, standard and extended multiplexing, and supported signal bounds.
- Provide a documented, versioned Excel schema suitable for human editing.
- Reuse existing service validation, atomic DBC writes, reload verification, JSON/text output, and traceback-free error handling.
- Validate a converted database semantically with the existing `compare` engine in end-to-end tests.
- Update the root Skill, bilingual documentation, examples, and tests.
- Pin `openpyxl==3.1.5` and continue supporting Python 3.9+.

## 4. Non-goals

- Legacy binary `.xls` import or export.
- canmatrix-compatible K-Matrix layout.
- Editing vendor-private DBC extensions through Excel.
- Preserving DBC whitespace or statement order.
- Converting CAN logs or MF4 data.
- Replacing the existing CRUD or comparison commands.

## 5. Command Contract

```bash
python3 scripts/dbc_crud.py excel export INPUT.dbc OUTPUT.xlsx
python3 scripts/dbc_crud.py excel import INPUT.xlsx OUTPUT.dbc
```

The existing global `--json` and `--encoding` options remain valid. `--encoding` controls DBC reading on export and DBC writing on import. Excel files are ZIP-based workbooks and do not use that text encoding.

Conversion commands are read-only for their source files. `excel export` atomically replaces an existing `.xlsx` destination without a backup. `excel import` writes through the existing `save_database` path; a distinct DBC destination is replaced according to the current CLI convention and the source workbook is never modified. Expected failures return nonzero without tracebacks and leave existing destination content unchanged whenever an output path was supplied.

Successful JSON results use the existing envelope and include:

- `input`
- `output`
- `format`
- `schema_version`
- `node_count`
- `message_count`
- `signal_count`
- `warnings`

Text output reports the same counts and output path.

## 6. Workbook Schema

The workbook format name is `dbc-skill-excel`, schema version `1`. It contains five worksheets: `Metadata`, `Nodes`, `Messages`, `Signals`, and `Choices`.

### 6.1 Metadata

A two-column `key` / `value` sheet:

- `format`: `dbc-skill-excel`
- `schema_version`: `1`
- `generator`: `dbc-skill/<repository version or tool name>`
- `dbc_version`: source DBC version string, when available
- `node_count`, `message_count`, `signal_count`: export-time counts for review and diagnostics

Unknown metadata keys are ignored. Missing or mismatched `format` or `schema_version` is an import error.

### 6.2 Nodes

Columns:

- `name`
- `comment`

Node names must be unique and must pass the existing DBC identifier validation.

### 6.3 Messages

Columns:

- `frame_id`
- `is_extended_frame`
- `name`
- `length`
- `senders`
- `is_fd`
- `cycle_time`
- `comment`

`frame_id` is exported as canonical hexadecimal text such as `0x1A2`. Import accepts hexadecimal or decimal text and integer cells. `senders` is a comma-separated list because DBC identifiers cannot contain commas. Message identity is `(frame_id, is_extended_frame)`. Empty-message rows are valid.

### 6.4 Signals

Columns:

- `message_frame_id`
- `message_is_extended_frame`
- `name`
- `start`
- `length`
- `byte_order`
- `is_signed`
- `factor`
- `offset`
- `minimum`
- `maximum`
- `unit`
- `receivers`
- `comment`
- `is_multiplexer`
- `multiplexer_signal`
- `multiplexer_ids`

`multiplexer_ids` uses the existing comma and inclusive-range syntax, for example `1,2,4-7`. `receivers` is comma-separated. Boolean cells accept `TRUE/FALSE`, `true/false`, `yes/no`, and `1/0` on import and are exported as Excel booleans. Structured numeric cells may be numeric or text.

### 6.5 Choices

A separate sheet avoids delimiter ambiguity in labels and supports arbitrary enum text:

- `message_frame_id`
- `message_is_extended_frame`
- `signal_name`
- `raw_value`
- `label`

Rows are grouped by parent signal during import. Raw values use the existing integer parser and may be decimal or hexadecimal. Each raw value must be unique within its signal.

### 6.6 Editing Aids

Export should provide freeze panes, filters, sensible column widths, boolean dropdowns, byte-order dropdowns, and header styling. These aids must not be required for a workbook to import successfully.

## 7. Import Architecture

Add a focused `scripts/dbc_skill/excel.py` module.

Export flow:

1. Load the DBC through the existing strict `load_database`.
2. Obtain a public entity snapshot from `DBCService` rather than duplicating serialization rules.
3. Validate schema invariants.
4. Build the workbook with `openpyxl`.
5. Save to a temporary `.xlsx` file in the destination directory.
6. Reopen the temporary workbook with `openpyxl.load_workbook` for verification.
7. Preserve an existing destination mode, then atomically replace the destination.

Import flow:

1. Reject non-`.xlsx` extensions and missing files with concise errors.
2. Open with `openpyxl.load_workbook(..., data_only=False)` so formula cells remain detectable.
3. Validate required sheets, headers, schema metadata, duplicate identities, references, value types, and formula use in structured cells.
4. Collect row-aware validation errors where practical and fail before writing.
5. Create an empty `cantools.database.Database` with the workbook DBC version.
6. Add nodes, messages, and signals through `DBCService` so all existing validation and rollback rules apply.
7. Attach grouped choices through the same signal field model.
8. Write through existing `save_database`, which serializes, reloads, verifies supported metadata, and atomically replaces the destination.

A public `DBCService.entity_snapshot()` method should return the same node/message/signal dictionaries used by export, comparison, and storage verification. This avoids private-method coupling and keeps comparison semantics consistent.

## 8. Validation and Security

- Reject unknown schema versions, missing required sheets, missing or duplicate headers, and duplicate rows or entity identities.
- Reject signals whose parent message is absent, choices whose parent signal is absent, senders or receivers whose nodes are absent, and multiplexer references that fail existing service validation.
- Reject formulas and external links in structured input cells.
- Treat text beginning with `=`, `+`, `-`, or `@` as a string on export by explicitly assigning string cell type rather than allowing Excel formula interpretation.
- Reject macro-enabled or encrypted workbooks when `openpyxl` cannot safely parse them as normal `.xlsx` files.
- Preserve UTF-8 workbook text; DBC encoding is applied only by the existing DBC load/save layer.
- Keep the existing rule that serializer-unrepresentable signal bounds fail before output replacement.
- Unknown extra worksheets are ignored and reported in `warnings`; unknown required-sheet columns are errors.

## 9. Comparison and Round-Trip Guarantee

The conversion is semantic, not byte-preserving. The required acceptance check is:

1. Export an existing DBC to `.xlsx`.
2. Import that `.xlsx` to a new DBC.
3. Run `compare original.dbc roundtrip.dbc`.
4. Assert `result.equal == true` for all supported fields.

The comparison test suite must cover ordinary signals, choices, comments, standard multiplexing, nested and multi-value extended multiplexing, empty messages, CAN FD, extended frames, and Unicode content. Any serializer-normalized field that cannot round-trip must already be rejected by the existing save verification.

## 10. Testing

Use the existing standard-library `unittest` pattern.

Coverage requirements:

- Workbook schema creation and reopening.
- Export counts, metadata, headers, styling-independent content, and deterministic ordering.
- Import of numeric and text cell types, boolean variants, hexadecimal IDs and raw choices, empty nullable cells, comments, and Unicode.
- Missing sheets, headers, rows, parents, nodes, duplicate identities, invalid booleans/ranges, formulas, unknown schema versions, and malformed workbooks.
- Standard and extended multiplexing round trips with encode/decode validation.
- Choices with commas, semicolons, Chinese text, and other delimiter-sensitive labels.
- Empty messages and messages with cleared senders.
- Atomic destination behavior and source preservation on expected failures.
- CLI text and JSON output, including stable result keys and traceback-free errors.
- Documentation contract tests for every new command, option, JSON key, and bilingual example.

## 11. Documentation and Skill Behavior

Update:

- `SKILL.md`
- `README.md`
- `README.zh-CN.md`
- `references/cli-reference.md`
- `references/dbc-fields.md`
- `examples/workflow.md`
- `examples/workflow.zh-CN.md`
- `requirements.txt`

Documentation must include the workbook sheet/column contract, value syntax, limitations, and a complete bilingual round-trip example using `compare` for verification. The Skill must instruct agents to use the conversion commands rather than manually editing workbook XML or DBC text.

## 12. Delivery

- Implement through test-driven tasks with subagent implementation and review.
- Keep the repository free of virtual environments, generated workbooks, caches, backups, and temporary output.
- Run the complete clean-environment suite and real CLI round-trip workflow.
- Commit, review, and push the finished work to `origin/main`.
