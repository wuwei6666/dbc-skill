# DBC CRUD Agent Skill Design

Date: 2026-10-18
Status: Approved for implementation

## 1. Purpose

Build a reusable Agent Skill that lets coding agents perform complete create, read, update, and delete operations on the primary entities in CAN DBC files: nodes (ECUs), messages (frames), and signals. The Skill will be documented primarily in English, include full Chinese documentation, and ship with executable scripts, examples, and automated tests.

The repository is `https://github.com/wuwei6666/dbc-skill.git`. The finished work will be committed and pushed to `main`.

## 2. Goals

- Provide a standard `SKILL.md` that agents can discover and follow.
- Provide a deterministic Python CLI suitable for both humans and agents.
- Support `list`, `show`, `add`, `update`, and `delete` for nodes, messages, and signals.
- Support creating a database, displaying a summary, and validating a database.
- Support standard and extended DBC multiplexing, including nested selectors and multiple multiplexer values or ranges where supported by the DBC format.
- Preserve common DBC metadata through load/edit/save round trips.
- Provide stable JSON output for automation and readable text output for people.
- Make mutations safe through validation, atomic writes, backups, and post-save reload checks.
- Include English and Chinese documentation, examples, and comprehensive tests.

## 3. Non-goals

- Decoding or encoding live CAN traffic.
- Supporting non-DBC formats such as ARXML, KCD, or SYM.
- Dedicated CRUD commands for every vendor-private DBC extension.
- Preserving original whitespace, statement ordering, or comments that the underlying parser does not model.
- Building a graphical DBC editor.

The CLI may normalize a DBC file when saving. It must not silently discard a modeled feature that it claims to support.

## 4. Chosen Approach

Use Python 3.9+ and `cantools` as the parser and DBC serializer. A small application service will own validation and mutations; a thin CLI will own argument parsing and output formatting. The Skill instructions will call the CLI rather than asking an agent to edit DBC text directly.

### Alternatives considered

- `canmatrix`: strong format-conversion support, but a broader object model and more conversion-oriented workflow than this Skill needs.
- Custom DBC text parser: potential formatting control, but unacceptable correctness and maintenance risk for bit layout, attributes, and multiplexing.

## 5. Repository Layout

```text
SKILL.md
README.md
README.zh-CN.md
LICENSE
requirements.txt
scripts/
  dbc_crud.py
  dbc_skill/
    __init__.py
    cli.py
    service.py
    formatting.py
references/
  cli-reference.md
  dbc-fields.md
examples/
  example.dbc
  workflow.md
  workflow.zh-CN.md
tests/
  __init__.py
  helpers.py
  test_service.py
  test_cli.py
  test_multiplexing.py
docs/superpowers/specs/
  2026-10-18-dbc-crud-skill-design.md
docs/superpowers/plans/
  2026-10-18-dbc-crud-skill.md
```

The layout may gain small focused modules if implementation shows a clear need, but the public CLI and Skill entry points will remain stable.

## 6. CLI Contract

Invoke the tool as:

```bash
python3 scripts/dbc_crud.py [global-options] <command> ...
```

Global options include `--json` for machine-readable output and `--encoding` for DBC input/output encoding. Mutation commands accept an input DBC path, an optional `--output` path, and `--no-backup` when an in-place backup is explicitly unwanted.

### File-level commands

- `init`: create a new, valid empty DBC database.
- `summary`: report counts and database-level information.
- `validate`: parse and validate without modifying the file.

### Entity commands

Each of `node`, `message`, and `signal` provides:

- `list`: enumerate entities with optional filters.
- `show`: return one entity with full supported detail.
- `add`: create an entity with validated fields.
- `update`: modify only supplied fields, including renaming.
- `delete`: remove an entity and report the result.

Messages are addressed by numeric frame ID, accepting decimal or `0x` hexadecimal notation, with name-based lookup available for listing and unambiguous show operations. Signals are addressed by parent message and signal name. Nodes are addressed by name.

The CLI returns zero on success, nonzero for validation or operational failures, and emits concise errors without a traceback for expected user errors.

## 7. Supported Fields

### Nodes

- Name
- Comment

### Messages

- Frame ID and standard/extended frame type
- Name
- DLC/length
- Transmitters
- CAN FD flag where supported
- Cycle time
- Comment
- Signals, shown as nested detail for read operations

### Signals

- Name
- Start bit and bit length
- Little-endian or big-endian byte order
- Signed or unsigned representation
- Factor and offset
- Minimum and maximum physical values
- Unit
- Receivers
- Comment
- Raw-value choices/enumerations
- Multiplexer role and relationships

Common metadata must survive an unrelated edit and a save/reload cycle. Tests will detect unintended loss of comments, choices, cycle time, and multiplexer metadata.

## 8. Multiplexing

Multiplexing is a first-class part of CRUD and validation.

### Standard multiplexing

- Create, show, update, and delete a multiplexer selector (`M`).
- Create, show, update, and delete branch signals (`m<N>`).
- Change or clear a signal's multiplexer assignment.
- Display the selector and branch value in text and JSON output.

### Extended multiplexing

- Model the parent selector for nested multiplexing.
- Support multiple values and ranges represented through `SG_MUL_VAL_` when exposed by `cantools`.
- Preserve extended multiplexer metadata across unrelated edits.
- Test save/reload and decoding for representative nested and multi-value cases.

If a particular extended-multiplexing construct cannot be represented or safely serialized by the selected library version, the command must fail explicitly before modifying the source file; it must not silently degrade to a non-multiplexed signal.

### Relationship safety

- Renaming a selector updates references held by its branch signals.
- Deleting a selector that still has dependent branches is rejected.
- A branch must reference an existing valid selector.
- Signal overlap validation must account for mutually exclusive branches rather than rejecting every overlapping branch layout.

## 9. Mutation and File Safety

- Parse and validate the input before any write.
- Validate all supplied values and entity relationships before any write.
- Reject duplicate node names, message IDs, and sibling signal names.
- Reject dangling transmitters, receivers, and multiplexer references unless the referenced node is created in the same operation.
- Deleting a message removes its contained signals and reports that behavior.
- Deleting a node still referenced by messages or signals is rejected.
- Serialize to a temporary file in the destination directory, then reload and validate that temporary file.
- Atomically replace the destination only after serialization and temporary-file reload validation both succeed.
- For in-place mutations, retain a `.bak` copy by default.
- If any write or reload step fails, retain the original source file and return an error.

## 10. Output and Localization

- The CLI and JSON schema use stable English keys and messages.
- Text output is concise and readable in a terminal.
- JSON output includes a success indicator, operation, affected entity, and relevant details; mutations also report output and backup paths.
- `SKILL.md`, `README.md`, references, and examples are primarily English.
- `README.zh-CN.md` and a Chinese workflow provide equivalent Chinese usage guidance.
- `SKILL.md` includes Chinese trigger examples so Chinese requests route to the same CLI workflows.
- UTF-8 comments and units are covered by round-trip tests; the tool also allows explicit alternative encodings for real-world DBC files.

## 11. Skill Behavior

The Skill instructs agents to:

1. Inspect and validate an existing DBC before editing it.
2. Use structured CLI commands instead of direct text edits.
3. Use JSON output when subsequent steps need exact values.
4. Avoid overwriting the source when the user requests a new file.
5. Keep default backups for in-place edits.
6. Verify mutations with `show`, `validate`, and, where useful, a before/after summary.
7. Explain normalization and backup behavior when relevant.
8. Never claim extended multiplexing or metadata preservation succeeded without a successful reload.

## 12. Testing and Acceptance

Use Python's standard `unittest` runner so the test suite needs no separate test framework.

### Unit and integration coverage

- Every CRUD operation for nodes, messages, and signals.
- Decimal and hexadecimal message IDs.
- Partial updates and rename behavior.
- Duplicate and missing entity errors.
- Signal bit layout, ranges, choices, comments, and receiver updates.
- Standard, nested, and multi-value/range multiplexing supported by the serializer.
- Protected node and selector deletion.
- Message deletion with nested signals.
- JSON success and error output.
- Backup creation, `--no-backup`, separate output files, and atomic-write failure behavior.
- Save/reload preservation of supported metadata.
- UTF-8 content and explicit encoding handling.
- Expected validation errors produce nonzero exits without tracebacks.

### End-to-end acceptance

From a clean virtual environment:

1. Install the declared dependencies.
2. Run the complete unit test suite.
3. Create a new DBC through the CLI.
4. Add nodes and messages.
5. Add ordinary, standard-multiplexed, and extended-multiplexed signals.
6. Query and update every entity type.
7. Delete entities and verify relationship protections.
8. Validate the final file and reload it with `cantools`.
9. Verify English and Chinese documentation commands match the implemented CLI.

All tests and the end-to-end workflow must pass before the final commit and push.

## 13. Delivery

- Review the final diff for correctness, documentation consistency, and accidental files.
- Do not commit virtual environments, caches, generated backups, or temporary output.
- Commit the completed Skill and push it to `origin/main`.
- Report the commit hash, GitHub URL, test result, and any explicit serialization limitations.
