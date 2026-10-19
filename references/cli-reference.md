# CLI reference

[English README](../README.md) · [中文 README](../README.zh-CN.md) · [DBC field reference](dbc-fields.md)

Run every command from the repository root. The CLI uses `cantools==40.7.1` and `openpyxl==3.1.5`; it does not accept direct DBC snippets on standard input.

## Invocation, identifiers, and output

```bash
python3 scripts/dbc_crud.py [--json] [--encoding ENCODING] COMMAND ...
```

| Global option | Meaning |
|---|---|
| `--json` | Emit one JSON object on standard output. Place it before `COMMAND`. |
| `--encoding ENCODING` | Select the load/save encoding; default `utf-8`. Place it before `COMMAND`. |

`PATH`, `LEFT`, and `RIGHT` are file paths. `NAME` is an entity name. `REFERENCE` and `MESSAGE_REF` accept a message name, decimal frame ID, or `0x` hexadecimal frame ID. `FRAME_ID` and `--new-id` accept decimal or `0x` hexadecimal integers.

Node, message, and signal names that cantools would rewrite, such as `ECU A` or `Status-Message`, are rejected instead of being silently normalized.

Successful JSON has `success`, `operation`, and `result`; expected failures have `success`, `operation`, and `error`. See [DBC fields](dbc-fields.md) for every result key.

### Mutation destination and backups

The entity `add`, `update`, and `delete` commands accept:

| Option | Meaning |
|---|---|
| `--output OTHER.dbc` | Write to another path. A distinct destination leaves the input unchanged and has no `.bak`; an existing distinct destination is replaced without its own backup. If `OTHER.dbc` resolves to the same file as `PATH`, the operation is treated as in-place for backup purposes. |
| `--no-backup` | For an in-place mutation, do not create `PATH.bak`. |

Without `--output`, these commands replace `PATH` and create `PATH.bak` by default when the source exists. The backup contains the original bytes. Existing destination permission modes are preserved. Saving still normalizes the destination through cantools; it is not byte-for-byte lossless. `init`, `summary`, `validate`, `compare`, `list`, and `show` do not accept mutation options.

## File and database commands

### Create an empty database

```bash
python3 scripts/dbc_crud.py init PATH
```

Creates parent directories as needed. `init` writes an empty database; it has no `--output` or `--no-backup` option. If `PATH` already exists, `init` replaces it and creates `PATH.bak` containing the previous bytes; otherwise no backup is created.

### Summarize a database

```bash
python3 scripts/dbc_crud.py summary PATH
```

Returns `version`, `node_count`, `message_count`, and `signal_count`.

### Validate a database

```bash
python3 scripts/dbc_crud.py validate PATH
```

Strictly loads and refreshes the database and validates multiplexer metadata. Returns `result.valid: true` on success.

### Compare two databases

```bash
python3 scripts/dbc_crud.py compare LEFT RIGHT
```

Read-only: neither input is normalized, replaced, or backed up. See [Comparison identity and JSON](#comparison-identity-and-json) below.

## Excel conversion

`excel` converts between a DBC database and an Excel workbook. Both subcommands are covered by the global `--json` envelope; `--encoding` controls DBC loading (export) and DBC saving (import), never the workbook itself.

### Export a database to Excel

```bash
python3 scripts/dbc_crud.py excel export INPUT.dbc OUTPUT.xlsx
```

Loads `INPUT.dbc` strictly and writes the five-sheet workbook described below to `OUTPUT.xlsx`. The workbook is first written to a temporary file in the destination directory, reloaded to verify its sheet structure, and then moved into place atomically. An existing `OUTPUT.xlsx` is replaced without a backup, preserving its permission mode. Boolean and `byte_order` columns carry dropdown validation to guide manual edits.

### Import a database from Excel

```bash
python3 scripts/dbc_crud.py excel import INPUT.xlsx OUTPUT.dbc
```

- The input must use the `.xlsx` extension (case-insensitive); legacy `.xls` workbooks are rejected before reading.
- The entire workbook is validated before anything is written — headers, cell types, cross-sheet references, signal bounds, and multiplexer rules — so a failed import never modifies `OUTPUT.dbc`. All problems are reported together as `Sheet '<name>' row <n> field '<field>': <detail>` lines and the command exits 1.
- The database is rebuilt through the same service as the CRUD commands, so every rule in [DBC fields](dbc-fields.md) applies, including bound representability and multiplexer validation.
- A successful import replaces an existing `OUTPUT.dbc` atomically without creating a `.bak` copy: `backup` is always `null` in the result.
- Sheets other than the five documented sheets are ignored, and their names are reported in `result.warnings`.

### Formula safety

Formulas are not allowed in structured cells: any data row containing a formula fails the import with "formulas are not allowed in structured cells". Before importing a workbook that was computed in Excel, copy the edited region and use Paste Special → Values (or paste as values in your spreadsheet application) so every structured cell holds a literal.

### Workbook schema

A workbook has exactly five sheets in this order: `Metadata`, `Nodes`, `Messages`, `Signals`, `Choices`. Row 1 holds the headers; columns may be reordered, but every documented header must be present exactly once, headers must be nonempty text, and unknown columns are rejected. Fully blank rows are skipped.

`Metadata` columns: `key`, `value`.

| Key | Meaning |
|---|---|
| `format` | Required; must be `dbc-skill-excel`. |
| `schema_version` | Required; must be `1`. |
| `generator` | Written by export (`dbc-skill/dbc_crud.py`); ignored on import. |
| `dbc_version` | Optional DBC version string, written by export when present. |
| `node_count`, `message_count`, `signal_count` | Entity counts written by export; ignored on import. |

Duplicate metadata keys are rejected; unlisted extra keys are ignored.

`Nodes` columns: `name` (required, unique), `comment` (optional).

`Messages` columns: `frame_id`, `is_extended_frame`, `name` (required, unique), `length` (required), `senders`, `is_fd`, `cycle_time`, `comment`.

`Signals` columns: `message_frame_id`, `message_is_extended_frame`, `name` (required), `start` (required), `length` (required), `byte_order`, `is_signed`, `factor`, `offset`, `minimum`, `maximum`, `unit`, `receivers`, `comment`, `is_multiplexer`, `multiplexer_signal`, `multiplexer_ids`. A signal's parent message is identified by `(message_frame_id, message_is_extended_frame)`, matching comparison identity.

`Choices` columns: `message_frame_id`, `message_is_extended_frame`, `signal_name`, `raw_value`, `label`. A Choices row belongs to the signal named `signal_name` inside the message identified by `(message_frame_id, message_is_extended_frame)`; the parent signal must exist. `raw_value` is a decimal or `0x` hexadecimal integer, unique per signal; `label` is required text.

### Cell syntax and defaults

- **Frame IDs** (`frame_id`, `message_frame_id`): decimal or `0x` hexadecimal. Export writes uppercase `0x` hexadecimal text.
- **Booleans** (`is_extended_frame`, `message_is_extended_frame`, `is_fd`, `is_signed`, `is_multiplexer`): `TRUE/FALSE`, `yes/no`, or `1/0`, case-insensitive; blank means `FALSE`.
- **`byte_order`**: `little_endian` or `big_endian`; blank means `little_endian`.
- **Name lists** (`senders`, `receivers`): one comma-separated cell; blank means none. Every name must exist as a node.
- **`multiplexer_ids`**: the same comma-separated values and inclusive ranges as the CLI `--multiplexer-values` argument — `1,2`, `2-4`, or the mixed `0,2-4,0xA`. A bare integer cell is a single ID; blank means no branch assignment. Export compacts sorted IDs into ranges such as `2-4`.
- **Multiplexer structure**: `multiplexer_signal` names the parent selector in the same message, and `multiplexer_ids` lists its branch values; set both or neither, exactly as with the CLI. Root selectors have `is_multiplexer` TRUE with blank parent and IDs.
- **Defaults for blank cells**: `factor` → 1, `offset` → 0, booleans → FALSE, `byte_order` → `little_endian`, name lists → empty, `cycle_time`/`minimum`/`maximum` and optional text → null. Signal bounds must be both present or both blank.

### Semantic round-trip verification

Export and import preserve every supported node, message, signal, choice, and multiplexer relationship. Verify a round trip semantically with `compare`; entity order and DBC formatting may differ from the source even when `result.equal` is true.

```bash
python3 scripts/dbc_crud.py --json excel export INPUT.dbc OUTPUT.xlsx
python3 scripts/dbc_crud.py --json excel import OUTPUT.xlsx ROUNDTRIP.dbc
python3 scripts/dbc_crud.py --json compare INPUT.dbc ROUNDTRIP.dbc
python3 scripts/dbc_crud.py --json validate ROUNDTRIP.dbc
```

See [Excel conversion results](dbc-fields.md#excel-conversion-results) for the exact result keys, including `warnings` and the always-null `backup`.

## Node commands

### List nodes

```bash
python3 scripts/dbc_crud.py node list PATH
```

Returns `result.nodes`, sorted by node name.

### Show a node

```bash
python3 scripts/dbc_crud.py node show PATH NAME
```

### Add a node

```bash
python3 scripts/dbc_crud.py node add PATH NAME [--comment TEXT] [--output OTHER.dbc] [--no-backup]
```

`--comment` sets an optional comment. Duplicate names are rejected.

### Update a node

```bash
python3 scripts/dbc_crud.py node update PATH NAME [--new-name NAME] [--comment TEXT | --clear-comment] [--output OTHER.dbc] [--no-backup]
```

- `--new-name` renames the node and updates message sender and signal receiver references.
- `--comment` replaces the comment; `--clear-comment` sets it to null. They are mutually exclusive.
- Omitted fields remain unchanged.

### Delete a node

```bash
python3 scripts/dbc_crud.py node delete PATH NAME [--output OTHER.dbc] [--no-backup]
```

Deletion fails if any message sender or signal receiver references the node.

## Message commands

### List messages

```bash
python3 scripts/dbc_crud.py message list PATH [--name NAME] [--sender NODE]
```

`--name` keeps an exact message name; `--sender` keeps messages whose sender list contains the node. Results are sorted by frame ID and name.

### Show a message

```bash
python3 scripts/dbc_crud.py message show PATH REFERENCE
```

### Add a message

```bash
python3 scripts/dbc_crud.py message add PATH FRAME_ID NAME --length BYTES [--sender NODE] [--extended] [--fd] [--cycle-time MS] [--comment TEXT] [--output OTHER.dbc] [--no-backup]
```

| Option | Meaning |
|---|---|
| `--length BYTES` | Required. Classic CAN: 1–8; CAN FD: 1–64. |
| `--sender NODE` | Add a sender; repeat for multiple senders. Every sender must already exist. Default no senders. |
| `--extended` | Use an extended frame ID. Default standard. Standard IDs are at most `0x7FF`; extended IDs are at most `0x1FFFFFFF`. |
| `--fd` | Mark as CAN FD. Default Classic CAN. |
| `--cycle-time MS` | Set a nonnegative integer cycle time in milliseconds. Default null. |
| `--comment TEXT` | Set an optional comment. Default null. |

Frame IDs and names must each be unique.

### Update a message

```bash
python3 scripts/dbc_crud.py message update PATH REFERENCE [--new-id FRAME_ID] [--new-name NAME] [--length BYTES] [--sender NODE | --clear-senders] [--extended | --standard] [--fd | --classic] [--cycle-time MS | --clear-cycle-time] [--comment TEXT | --clear-comment] [--output OTHER.dbc] [--no-backup]
```

- `--new-id` and `--new-name` change identity fields; duplicates are rejected.
- Repeated `--sender` replaces the sender list with the supplied values. `--clear-senders` replaces it with an empty list; the two options are mutually exclusive. Omitting both preserves the current list.
- `--extended` / `--standard` select the frame type; `--fd` / `--classic` select CAN FD or Classic CAN.
- `--cycle-time` sets a nonnegative integer; `--clear-cycle-time` sets null.
- `--comment` replaces the comment; `--clear-comment` sets null.
- Shrinking `--length` below any signal boundary is rejected. Other omitted fields remain unchanged.

### Delete a message

```bash
python3 scripts/dbc_crud.py message delete PATH REFERENCE [--output OTHER.dbc] [--no-backup]
```

Deletes the message and all of its signals. The result adds `deleted_signal_count` to the deleted message object.

## Signal commands

### List signals in a message

```bash
python3 scripts/dbc_crud.py signal list PATH MESSAGE_REF [--name NAME]
```

`--name` keeps an exact signal name. Results are sorted by start bit and name.

### Show a signal

```bash
python3 scripts/dbc_crud.py signal show PATH MESSAGE_REF NAME
```

### Add a signal

```bash
python3 scripts/dbc_crud.py signal add PATH MESSAGE_REF NAME --start BIT --length BITS [--byte-order little_endian|big_endian] [--signed] [--factor NUMBER] [--offset NUMBER] [--minimum NUMBER] [--maximum NUMBER] [--unit TEXT] [--receiver NODE] [--choice RAW=LABEL] [--comment TEXT] [--multiplexer] [--multiplexer-of PARENT] [--multiplexer-values VALUES] [--output OTHER.dbc] [--no-backup]
```

| Option | Meaning |
|---|---|
| `--start BIT` | Required nonnegative start bit. |
| `--length BITS` | Required positive signal length in bits. |
| `--byte-order` | `little_endian` (default) or `big_endian`. |
| `--signed` | Signed signal; default unsigned. |
| `--factor` | Physical-value scale; default `1`. |
| `--offset` | Physical-value offset; default `0`. |
| `--minimum`, `--maximum` | Physical bounds. Set both or neither; see the representability rule in [DBC fields](dbc-fields.md#signal-bound-representability). |
| `--unit` | Unit string; default null. |
| `--receiver NODE` | Add an existing receiver node; repeat for multiple receivers. Default empty. |
| `--choice RAW=LABEL` | Add a value label; repeat for multiple choices. `RAW` is decimal or `0x` hexadecimal. |
| `--comment` | Comment string; default null. |
| `--multiplexer` | Make this signal a multiplexer selector. |
| `--multiplexer-of PARENT` | Name the parent selector for a branch or nested selector. |
| `--multiplexer-values VALUES` | Assign nonempty, nonnegative branch IDs using the exact syntax below. |

Signals must fit in the message without invalid overlap. Overlap between branches is allowed only when their multiplexer assignments make it valid.

### Update a signal

```bash
python3 scripts/dbc_crud.py signal update PATH MESSAGE_REF NAME [--new-name NAME] [--start BIT] [--length BITS] [--byte-order little_endian|big_endian] [--signed | --unsigned] [--factor NUMBER] [--offset NUMBER] [--minimum NUMBER | --clear-minimum] [--maximum NUMBER | --clear-maximum] [--unit TEXT | --clear-unit] [--receiver NODE | --clear-receivers] [--choice RAW=LABEL | --clear-choices] [--comment TEXT | --clear-comment] [--multiplexer | --no-multiplexer] [--multiplexer-of PARENT] [--multiplexer-values VALUES] [--clear-multiplexer] [--output OTHER.dbc] [--no-backup]
```

- `--new-name` renames the signal. Renaming a selector also updates its branches' parent references.
- `--signed` / `--unsigned` and `--multiplexer` / `--no-multiplexer` are mutually exclusive pairs. A selector with dependents cannot have its selector role removed.
- Repeated `--receiver` or `--choice` replaces the complete receiver list or choice map. `--clear-receivers` produces an empty list; `--clear-choices` produces null.
- `--clear-minimum` and `--clear-maximum` clear their respective bounds. Because one-sided bounds are not representable, clear both together.
- `--clear-unit` and `--clear-comment` set those fields to null.
- `--multiplexer-of` and `--multiplexer-values` update branch assignment. `--clear-multiplexer` clears both parent and IDs; it cannot be combined with a new assignment and does not itself change `is_multiplexer`.
- Other omitted fields remain unchanged.

### Delete a signal

```bash
python3 scripts/dbc_crud.py signal delete PATH MESSAGE_REF NAME [--output OTHER.dbc] [--no-backup]
```

Deletion fails while other signals name this signal as their multiplexer parent. Delete or reassign those branches first.

## Standard and extended multiplexing

`--multiplexer-values` takes one comma-separated argument of decimal or `0x` hexadecimal nonnegative integers and inclusive ranges:

- `--multiplexer-values 1,2` produces IDs `[1, 2]`.
- `--multiplexer-values 2-4` produces the inclusive IDs `[2, 3, 4]`.
- Values and ranges can be mixed: `--multiplexer-values 0,2-4,0xA` produces `[0, 2, 3, 4, 10]`.

Do not use spaces instead of commas, repeated flags for multiple IDs, or descending ranges such as `4-2`. If the argument contains spaces, quote it so the shell passes one argument. Duplicate IDs are normalized away and the resulting list is sorted.

A parent and IDs must be assigned together, and every parent must have `is_multiplexer: true`. With exactly one root selector and one ID, `--multiplexer-of` may be omitted for automatic parent selection. Use an explicit parent for multiple IDs, nested selectors, or ambiguous trees. Cycles and missing/non-selector parents are rejected.

Standard multiplexing example: one root selector with two branches that may share bit positions because their IDs differ.

```bash
python3 scripts/dbc_crud.py signal add file.dbc Status Mode --start 0 --length 8 --multiplexer
python3 scripts/dbc_crud.py signal add file.dbc Status Speed --start 8 --length 16 --multiplexer-of Mode --multiplexer-values 0
python3 scripts/dbc_crud.py signal add file.dbc Status Rpm --start 8 --length 16 --multiplexer-of Mode --multiplexer-values 1
```

Extended multiplexing example: `SubMode` is both a branch of `Mode` and a selector for `Payload`.

```bash
python3 scripts/dbc_crud.py signal add file.dbc Status Mode --start 0 --length 8 --multiplexer
python3 scripts/dbc_crud.py signal add file.dbc Status SubMode --start 8 --length 8 --multiplexer --multiplexer-of Mode --multiplexer-values 1,2
python3 scripts/dbc_crud.py signal add file.dbc Status Payload --start 16 --length 16 --multiplexer-of SubMode --multiplexer-values 2-4
```

Nested and multi-value/range relationships are serialized through DBC `SG_MUL_VAL_` where required. Save reloads the temporary file and compares every supported entity identity and field, including multiplexer metadata, before replacement. These checks do not claim lossless preservation of unrelated formatting or unsupported DBC constructs.

## Comparison identity and JSON

Comparison is deterministic and read-only.

- **Nodes:** identity is `name`. A rename is a removal plus an addition.
- **Messages:** identity is `(frame_id, is_extended_frame)`. A name change is `modified`; changing frame ID or frame type is a removal plus an addition.
- **Signals:** identity is `(message_frame_id, message_is_extended_frame, name)`. A signal rename is a removal plus an addition.
- **Statuses:** each entity group has `added`, `removed`, `modified`, and `unchanged`. Added/removed entries contain full entity details; modified entries contain identity plus `changes`; unchanged entries contain identity only.
- **Changes:** each changed field is `{"left": OLD, "right": NEW}`. Floats are compared exactly, without a tolerance.
- **Equality and counts:** `result.equal` is true only when there are no added, removed, or modified entities. `result.counts` aggregates each status across nodes, messages, and signals.

Useful exact paths in the JSON envelope are:

- `result.equal`
- `result.counts.added`, `result.counts.removed`, `result.counts.modified`, `result.counts.unchanged`
- `result.nodes.added`, `result.messages.added`, `result.signals.added` (and the equivalent `removed`, `modified`, `unchanged` groups)
- `result.messages.modified[0].changes.cycle_time.left`
- `result.messages.modified[0].changes.cycle_time.right`

### Comparison JSON example

<!-- comparison-json-example -->

This is real output from `python3 scripts/dbc_crud.py --json compare left.dbc right.dbc`. The right file adds the `Telemetry` message and its `Voltage` signal and changes `Status.cycle_time` from 100 to 200; both files retain the unchanged `State` signal.

```json
{
  "operation": "compare",
  "result": {
    "counts": {
      "added": 2,
      "modified": 1,
      "removed": 0,
      "unchanged": 1
    },
    "equal": false,
    "messages": {
      "added": [
        {
          "comment": null,
          "cycle_time": null,
          "frame_id": 1280,
          "is_extended_frame": false,
          "is_fd": false,
          "length": 8,
          "name": "Telemetry",
          "senders": [],
          "signals": [
            {
              "length": 16,
              "name": "Voltage",
              "start": 0
            }
          ]
        }
      ],
      "modified": [
        {
          "changes": {
            "cycle_time": {
              "left": 100,
              "right": 200
            }
          },
          "frame_id": 291,
          "is_extended_frame": false
        }
      ],
      "removed": [],
      "unchanged": []
    },
    "nodes": {
      "added": [],
      "modified": [],
      "removed": [],
      "unchanged": []
    },
    "signals": {
      "added": [
        {
          "byte_order": "little_endian",
          "choices": null,
          "comment": null,
          "factor": 0.1,
          "is_multiplexer": false,
          "is_signed": false,
          "length": 16,
          "maximum": null,
          "message_frame_id": 1280,
          "message_is_extended_frame": false,
          "minimum": null,
          "multiplexer_ids": null,
          "multiplexer_signal": null,
          "name": "Voltage",
          "offset": 0,
          "receivers": [],
          "start": 0,
          "unit": null
        }
      ],
      "modified": [],
      "removed": [],
      "unchanged": [
        {
          "message_frame_id": 291,
          "message_is_extended_frame": false,
          "name": "State"
        }
      ]
    }
  },
  "success": true
}
```

In this example, `result.messages.added[0].name` is `Telemetry`, `result.signals.added[0].name` is `Voltage`, and `result.messages.modified[0].changes.cycle_time` is `{"left": 100, "right": 200}`.

## Exit codes

- `0`: success. For `compare`, both valid equal and valid different inputs return exit code 0.
- `1`: an expected load, validation, CRUD, encoding, or save error. JSON mode emits the error object without a traceback.
- `2`: command-line usage error from the argument parser, such as an unknown option or a missing required argument.
