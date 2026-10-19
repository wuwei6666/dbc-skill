---
name: dbc-crud
description: Use when creating, reading, updating, deleting, validating, or comparing DBC files for CAN/CAN FD networks, or converting between DBC and Excel workbooks; requests mention DBC CRUD, nodes, messages, signals, frame IDs, comparison, standard multiplexing, extended multiplexing, DBC 与 Excel 互转, or exporting DBC to Excel.
---

# DBC CRUD

Use the CLI from the repository root. Prefer `--json`, and never edit DBC text directly.

## Safe procedure

1. Validate the input before changing it:
   ```bash
   python3 scripts/dbc_crud.py --json validate file.dbc
   ```
2. Use `python3 scripts/dbc_crud.py`; place global `--json` and `--encoding` before the command.
3. In-place mutations create `PATH.bak` by default. Always retain backups. Use `--output OTHER.dbc` for non-overwriting edits; use `--no-backup` only for disposable files or when another backup exists.
4. Saving uses cantools to normalize DBC text; it is not byte-for-byte lossless preservation of formatting or unsupported constructs.
5. Verify changes with the relevant `node show`, `message show`, or `signal show`, then run `validate`. Use `summary` for counts and `compare` for differences.

## Quick reference

| Task | English / Chinese trigger examples | Operation |
|---|---|---|
| Add node | “Add a node” / “添加节点” | `node add` |
| Add message | “Add a message” / “添加报文” | `message add` |
| Add signal | “Add a signal” / “添加信号” | `signal add` |
| Edit scale | “Edit a signal's scale” / “修改信号比例” | `signal update ... --factor` |
| Delete safely | “Delete safely” / “安全删除” | Inspect references, then `delete`; prefer `--output` |
| Compare | “Compare two DBC files” / “比较两个 DBC” | `compare LEFT RIGHT` |
| Standard multiplexing | “Create standard multiplexing” / “创建标准多路复用” | Add one `--multiplexer` selector and branch IDs |
| Extended multiplexing | “Create extended multiplexing” / “创建扩展多路复用” | Nest selectors with `--multiplexer-of` and branch IDs |
| Export to Excel | “Export the DBC to Excel” / “导出为 Excel” | `excel export INPUT.dbc OUTPUT.xlsx` |
| Import from Excel | “Import the Excel workbook” / “从 Excel 导入” | `excel import INPUT.xlsx OUTPUT.dbc` |
| Verify Excel round-trip | “Verify the round trip” / “验证往返一致性” | `compare INPUT.dbc ROUNDTRIP.dbc` |

`--multiplexer-values` is one comma-separated argument: `--multiplexer-values 1,2` means IDs 1 and 2, while `--multiplexer-values 2-4` means the inclusive range 2, 3, 4. Decimal and `0x` hexadecimal values can be mixed, as in `0,2-4,0xA`. Every parent must be a selector; extended multiplexing can nest selectors and uses DBC `SG_MUL_VAL_` metadata where required.

Comparison JSON paths include `result.equal`, `result.messages.added`, and `result.signals.added`. Modified fields have `left`/`right` values under `changes`; see the [real comparison JSON example](references/cli-reference.md#comparison-json-example).

## Excel conversion

`excel export INPUT.dbc OUTPUT.xlsx` writes a five-sheet workbook (`Metadata`, `Nodes`, `Messages`, `Signals`, `Choices`); `excel import INPUT.xlsx OUTPUT.dbc` rebuilds the database from it. Import accepts only `.xlsx` files, rejects formula cells (paste as values first), validates the whole workbook before writing anything, and replaces `OUTPUT.dbc` atomically with `backup` always null. Extra sheets are ignored and listed in `result.warnings`. Verify a round trip semantically: export, import to a new file, then `compare` the two DBC files and check `result.equal`. The full workbook schema and cell syntax are in the [CLI reference](references/cli-reference.md#excel-conversion).

## Common mistakes

| Mistake | Correction |
|---|---|
| Editing DBC text directly | Use the structured CLI and validate afterward. |
| Guessing multiplexer separators or JSON keys | Use the exact syntax above and the documented comparison schema. |
| Setting only one signal bound | Set or clear both; see the representability rule in the field reference. |
| Deleting a referenced node or selector | Remove/reassign dependents first, or keep the referenced entity. |
| Assuming normalized output preserves every byte | Retain `.bak` or write to `--output`. |
| Treating comparison differences as an error | Valid equal and different inputs both return exit code 0. |
| Importing a `.xls` file or formula cells into DBC | Save as `.xlsx` and paste cells as values before `excel import`. |

## References

- [Complete CLI and comparison schema](references/cli-reference.md)
- [DBC fields, bounds, and multiplexing rules](references/dbc-fields.md)
- [English workflow](examples/workflow.md) / [中文工作流](examples/workflow.zh-CN.md)
