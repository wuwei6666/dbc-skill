# DBC field and JSON reference

[CLI reference](cli-reference.md) · [English README](../README.md) · [中文 README](../README.zh-CN.md)

All JSON below describes the actual CLI serialization. Numbers are JSON numbers; nullable fields are `null`; booleans are `true` or `false`.

## JSON envelope

Successful commands emit:

```json
{"success": true, "operation": "signal", "result": {}}
```

Expected failures emit:

```json
{"success": false, "operation": "signal", "error": "description"}
```

| Key | Type | Meaning |
|---|---|---|
| `success` | boolean | Whether the command completed successfully. |
| `operation` | string | Top-level command: `init`, `summary`, `validate`, `compare`, `node`, `message`, or `signal`. |
| `result` | object | Success payload; shape depends on the operation. |
| `error` | string | Expected failure message; present instead of `result` on failure. |

Argument-parser usage errors are handled by argparse and do not use this JSON envelope.

## Summary and validation results

`summary PATH` returns:

| Key | Type | Meaning |
|---|---|---|
| `version` | string or null | DBC version string. |
| `node_count` | integer | Number of nodes. |
| `message_count` | integer | Number of messages. |
| `signal_count` | integer | Total signals across all messages. |

`validate PATH` returns `{"valid": true}` after strict loading, database refresh, and multiplexer metadata validation succeed.

## Node objects

Node list/show/add/update/delete results use:

| Key | Type | Meaning |
|---|---|---|
| `name` | string | Unique node name. |
| `comment` | string or null | Node comment. |

`node list` wraps these objects in `result.nodes`. Renaming a node updates matching message `senders` and signal `receivers`. A referenced node cannot be deleted.

## Message objects

Message list/show/add/update/delete results use:

| Key | Type | Meaning |
|---|---|---|
| `frame_id` | integer | Numeric frame ID; JSON uses decimal even when input was hexadecimal. |
| `name` | string | Unique message name. |
| `length` | integer | Message payload length in bytes. |
| `senders` | array of strings | Sending node names. |
| `is_extended_frame` | boolean | `false` for an 11-bit standard ID; `true` for a 29-bit extended ID. |
| `is_fd` | boolean | Whether the message is CAN FD. |
| `cycle_time` | integer or null | Cycle time in milliseconds. |
| `comment` | string or null | Message comment. |
| `signals` | array | Signal summaries in the message. |

Each entry in `signals` contains only:

| Key | Type | Meaning |
|---|---|---|
| `name` | string | Signal name. |
| `start` | integer | Start bit. |
| `length` | integer | Signal length in bits. |

`message list` wraps full message objects in `result.messages`. A successful `message delete` additionally includes:

| Key | Type | Meaning |
|---|---|---|
| `deleted_signal_count` | integer | Number of signals removed with the message. |

Standard IDs range from `0` to `0x7FF`; extended IDs range from `0` to `0x1FFFFFFF`. Classic CAN lengths are 1–8 bytes; CAN FD lengths are 1–64 bytes. Frame IDs and message names are independently unique. A message cannot shrink below its signal layout.

## Signal objects

Signal list/show/add/update/delete results use:

| Key | Type | CLI field | Meaning |
|---|---|---|---|
| `name` | string | positional `NAME`; `--new-name` | Unique signal name within the message. |
| `start` | integer | `--start` | Nonnegative start bit. |
| `length` | integer | `--length` | Positive signal length in bits. |
| `byte_order` | string | `--byte-order` | `little_endian` or `big_endian`; add default is `little_endian`. |
| `is_signed` | boolean | `--signed`, `--unsigned` | Signedness; add default is `false`. |
| `factor` | number | `--factor` | Scale used by physical conversion; add default is `1`. |
| `offset` | number | `--offset` | Offset used by physical conversion; add default is `0`. |
| `minimum` | number or null | `--minimum`, `--clear-minimum` | Physical minimum. |
| `maximum` | number or null | `--maximum`, `--clear-maximum` | Physical maximum. |
| `unit` | string or null | `--unit`, `--clear-unit` | Unit string. |
| `receivers` | array of strings | `--receiver`, `--clear-receivers` | Receiving node names; add default is empty. |
| `choices` | object or null | `--choice`, `--clear-choices` | Value labels; JSON object keys are decimal raw-value strings and values are labels. |
| `comment` | string or null | `--comment`, `--clear-comment` | Signal comment. |
| `is_multiplexer` | boolean | `--multiplexer`, `--no-multiplexer` | Whether this signal is a selector; add default is `false`. |
| `multiplexer_ids` | array of integers or null | `--multiplexer-values`, `--clear-multiplexer` | Sorted branch values, or null for no branch assignment. |
| `multiplexer_signal` | string or null | `--multiplexer-of`, `--clear-multiplexer` | Parent selector name, or null for no branch assignment. |

`signal list` wraps full signal objects in `result.signals`. `factor`, `offset`, `minimum`, and `maximum` must be finite numbers when present, and `minimum` cannot exceed `maximum`. Receivers must name existing nodes. Choices use `RAW=LABEL` CLI notation, with decimal or `0x` hexadecimal raw integers and nonempty labels.

An update preserves omitted fields. Supplying receivers or choices replaces the complete collection. The clear options have the exact results shown in the table; in particular, clearing receivers produces `[]`, while clearing choices, unit, or comment produces `null`.

## Signal bound representability

DBC cannot represent one-sided signal bounds: `minimum` and `maximum` must both be present or both be null. Always set or clear both. For example, use `--clear-minimum --clear-maximum` together; clearing only one fails without saving the mutation.

DBC reserves the integer 0|0 pair for absent bounds. The service/storage validator therefore rejects an integer zero pair and requires floating-point zero or absent bounds instead. CLI bound arguments are parsed as floating-point numbers, so both `0` and `0.0` input become representable floating-point zero; writing `--minimum 0.0 --maximum 0.0` makes that intent explicit. Negative-to-positive, positive-only, negative-only, and equal floating-point bounds are representable when `minimum <= maximum`.

These rules prevent silent reload changes. They do not imply that arbitrary physical ranges can be encoded without considering the signal's raw bit length and conversion.

## Multiplexer fields and validation

Standard multiplexing has a root selector and branch signals. Extended multiplexing allows a branch also to be a selector, forming a nested tree. The two roles are independent:

- `is_multiplexer: true` marks a selector.
- `multiplexer_signal` plus `multiplexer_ids` assigns a signal to a parent branch.
- A nested selector has all three fields populated; a root selector has only `is_multiplexer: true` and null branch fields.

Validation rules:

1. Parent and IDs must be assigned together. IDs must be nonempty, nonnegative integers and are sorted and deduplicated by CLI mutations.
2. The parent must exist in the same message and be a selector. Self-parenting and cycles are rejected.
3. If `--multiplexer-of` is omitted, automatic parent selection is available only for one ID and exactly one root selector. Multiple IDs or an ambiguous tree require an explicit parent.
4. `--clear-multiplexer` sets `multiplexer_signal` and `multiplexer_ids` to null; it does not clear `is_multiplexer`.
5. A selector with dependents cannot be deleted or have its selector role removed. Renaming a selector updates dependent parent names.
6. Layout overlap is validated with branch assignments. Branches may share bits only when their multiplexer relationships permit it.

`--multiplexer-values` uses comma-separated values and inclusive ranges, such as `1,2`, `2-4`, or the mixed decimal/hexadecimal form `0,2-4,0xA`. See the [CLI multiplexing examples](cli-reference.md#standard-and-extended-multiplexing).

Nested and multi-value/range relationships use DBC `SG_MUL_VAL_` records where required. Before replacing a destination, the save path reloads the temporary DBC and compares each signal's selector role, parent, and sorted IDs with the in-memory values. A mismatch rejects the save. This protects multiplexer metadata; it is not a guarantee of byte-for-byte or arbitrary DBC construct preservation.

## Mutation result fields

Successful entity mutations, and `init`, add these fields to the entity result (or return them alone for `init`):

| Key | Type | Meaning |
|---|---|---|
| `output` | string | Destination path actually written. |
| `backup` | string or null | Backup path, or null when no backup was made. |

For an in-place entity mutation with backups enabled, `backup` is `PATH.bak` and contains the source bytes from immediately before that save. A later in-place save replaces the previous `.bak`; copy backups elsewhere if multiple recovery points are needed. With `--output` to a different path, the input is not modified and `backup` is null. With `--no-backup`, `backup` is also null.

Saving serializes to a temporary file in the destination directory, strictly reloads it, checks multiplexer metadata, and then replaces the destination. cantools normalizes DBC text, so formatting and unsupported constructs are not promised to survive. The global `--encoding` controls both loading and saving; during `compare`, the same selected encoding is used for both inputs.

## Comparison result fields

`compare LEFT RIGHT` returns a result with:

| Key | Type | Meaning |
|---|---|---|
| `equal` | boolean | True when no added, removed, or modified entities exist. |
| `counts` | object | Aggregate `added`, `removed`, `modified`, and `unchanged` counts across all three entity types. |
| `nodes` | object | Node status groups. |
| `messages` | object | Message status groups. |
| `signals` | object | Signal status groups. |

Each entity object has `added`, `removed`, `modified`, and `unchanged` arrays. Modified entries have a `changes` object whose field values contain `left` and `right`. Signal identity uses `message_frame_id`, `message_is_extended_frame`, and `name`; message identity uses `frame_id` and `is_extended_frame`; node identity uses `name`.

See the [complete real comparison JSON](cli-reference.md#comparison-json-example) for exact paths and representative values.
