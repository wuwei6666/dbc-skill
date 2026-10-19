# DBC CRUD Agent Skill

[简体中文](README.zh-CN.md)

A structured command-line skill for creating, inspecting, updating, deleting, validating, and comparing CAN DBC databases, and for converting between DBC and Excel workbooks. It supports nodes, messages, signals, Classic CAN and CAN FD frame metadata, standard and extended multiplexing, JSON output, and deterministic node/message/signal comparison.

## Requirements and setup

- Python 3.9+
- The pinned dependencies in `requirements.txt` (`cantools==40.7.1`, `openpyxl==3.1.5`)

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
source .venv/bin/activate
```

Keep the repository layout intact when installing the skill: `SKILL.md`, `references/`, `examples/`, and `scripts/` use relative paths. Run commands from the repository root.

## Quick start

```bash
# Create and validate an empty database.
python3 scripts/dbc_crud.py --json init demo.dbc
python3 scripts/dbc_crud.py --json validate demo.dbc

# Add a node, a message, and a signal.
python3 scripts/dbc_crud.py --json node add demo.dbc ECU_A --comment "Body controller"
python3 scripts/dbc_crud.py --json message add demo.dbc 0x123 Status --length 8 --sender ECU_A
python3 scripts/dbc_crud.py --json signal add demo.dbc Status State --start 0 --length 8

# Inspect the result and validate again.
python3 scripts/dbc_crud.py --json signal show demo.dbc Status State
python3 scripts/dbc_crud.py --json summary demo.dbc
python3 scripts/dbc_crud.py --json validate demo.dbc
```

Message references accept a name or a decimal/`0x` hexadecimal frame ID. Put global options before the command, for example `python3 scripts/dbc_crud.py --json --encoding utf-8 summary demo.dbc`.

## Safe edits and normalization

- `node`, `message`, and `signal` add/update/delete operations save through cantools. An in-place save creates `PATH.bak` containing the original bytes by default; retain it while checking the result.
- `--output OTHER.dbc` writes a separate file and leaves the input unchanged. This is the safest choice for destructive or experimental edits.
- `--no-backup` disables the `.bak` copy for an in-place save. Use it only for disposable files or when another backup exists.
- Saving normalizes DBC text. It is not byte-for-byte lossless preservation of comments, formatting, or constructs that cantools does not model. The CLI writes a temporary file, reloads it strictly, checks all supported entity metadata, and then replaces the destination.
- The default encoding is UTF-8. Use global `--encoding` with the encoding used by the source and destination, such as `cp936` for a compatible legacy file.

## CAN and DBC capabilities

- Standard frame IDs: `0` through `0x7FF`; extended frame IDs: `0` through `0x1FFFFFFF` with `--extended`.
- Classic CAN message length: 1–8 bytes; CAN FD with `--fd`: 1–64 bytes.
- Standard multiplexing uses a root selector and branch values. Extended multiplexing supports nested selectors and multiple values/ranges through DBC `SG_MUL_VAL_` metadata.
- Signal bounds must both be present or both absent. Integer `0|0` is reserved for absent bounds; floating-point zero is representable. See the field reference before clearing or setting bounds.
- Comparison identifies nodes by name, messages by frame ID plus frame type, and signals by parent message identity plus signal name. Valid equal or different inputs return exit code 0.

## Excel conversion

```bash
python3 scripts/dbc_crud.py --json excel export INPUT.dbc OUTPUT.xlsx
python3 scripts/dbc_crud.py --json excel import INPUT.xlsx OUTPUT.dbc
```

- Export writes a five-sheet workbook (`Metadata`, `Nodes`, `Messages`, `Signals`, `Choices`) with dropdown validation for boolean and byte-order columns; an existing destination is replaced atomically without a backup.
- Import accepts only `.xlsx` files and rejects formula cells — paste computed cells as values before importing. The whole workbook is validated before anything is written, so a failed import never touches `OUTPUT.dbc`; a successful import replaces it atomically and `backup` is always `null`.
- Sheets beyond the five documented ones are ignored and listed in `result.warnings`.
- Verify a round trip semantically: export, import to a new DBC, then `compare` the two files and check `result.equal`.

The full workbook schema, column list, and cell syntax are in the [CLI reference](references/cli-reference.md#excel-conversion); result keys are in the [field reference](references/dbc-fields.md#excel-conversion-results).

## Documentation

- [Agent Skill](SKILL.md)
- [Complete CLI reference and real comparison JSON example](references/cli-reference.md)
- [DBC fields and validation rules](references/dbc-fields.md)
- [Complete English workflow](examples/workflow.md)
- [完整中文工作流](examples/workflow.zh-CN.md)

The workflows use a temporary copy and write every mutation to a new `--output` file. They demonstrate CRUD, scale editing, standard and extended multiplexing, safe deletion, comparison, a semantic Excel round trip, final inspection, and validation.

## Tests

```bash
.venv/bin/python -m unittest tests.test_docs -v
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## License

Released under the [MIT License](LICENSE).
