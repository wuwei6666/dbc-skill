# Complete English workflow

[中文工作流](workflow.zh-CN.md)

Run from the repository root with the virtual environment activated. The script copies `examples/example.dbc` into a temporary directory. Every mutation uses `--output`, so the original input and every intermediate stage remain unchanged until the temporary directory is removed.

The example adds a node and a standard-multiplexed message, edits a signal scale, updates and temporarily extends the existing nested multiplexing, safely deletes unreferenced entities, compares the result with the original, and validates the final file.

```bash
set -euo pipefail
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
CLI=(python3 scripts/dbc_crud.py --json)
ORIGINAL="$WORKDIR/original.dbc"
cp examples/example.dbc "$ORIGINAL"
CURRENT="$ORIGINAL"
STEP=0

edit() {
  local next
  STEP=$((STEP + 1))
  next="$(printf '%s/step-%02d.dbc' "$WORKDIR" "$STEP")"
  "${CLI[@]}" "$@" --output "$next"
  CURRENT="$next"
}

# Validate before any mutation.
"${CLI[@]}" validate "$ORIGINAL"

# Add a node, message, root selector, and two standard-multiplexed branches.
edit node add "$CURRENT" Gateway --comment "Gateway ECU"
edit message add "$CURRENT" 0x500 Diagnostics --length 8 --sender Gateway --cycle-time 100
edit signal add "$CURRENT" Diagnostics DiagMode --start 0 --length 8 --multiplexer
edit signal add "$CURRENT" Diagnostics Temperature --start 8 --length 16 --factor 0.5 --offset -40 --minimum -40 --maximum 215 --unit '°C' --receiver Gateway --multiplexer-of DiagMode --multiplexer-values 0
edit signal add "$CURRENT" Diagnostics Voltage --start 8 --length 16 --factor 0.1 --minimum 0 --maximum 100 --unit V --multiplexer-of DiagMode --multiplexer-values 1

# Edit the scale while preserving the other fields.
edit signal update "$CURRENT" Diagnostics Voltage --factor 0.25

# Use explicit comma and inclusive-range syntax in the existing extended tree.
edit signal update "$CURRENT" Status SubMode --multiplexer-values 1,2
edit signal add "$CURRENT" Status ExtendedPayload --start 40 --length 16 --multiplexer-of SubMode --multiplexer-values 4-5

# Inspect before safe deletion; both entities are unreferenced.
edit node add "$CURRENT" Scratch
"${CLI[@]}" node show "$CURRENT" Scratch
edit node delete "$CURRENT" Scratch
"${CLI[@]}" signal show "$CURRENT" Status ExtendedPayload
edit signal delete "$CURRENT" Status ExtendedPayload

# Verify the final entities, compare without modifying either input, and validate.
"${CLI[@]}" signal show "$CURRENT" Diagnostics Voltage
"${CLI[@]}" signal show "$CURRENT" Status SubMode
"${CLI[@]}" compare "$ORIGINAL" "$CURRENT"
"${CLI[@]}" validate "$CURRENT"
"${CLI[@]}" summary "$CURRENT"
```

The final summary has `node_count: 1`, `message_count: 2`, and `signal_count: 7`. Comparison returns exit code 0 even though `result.equal` is `false`; differences are data, not a CLI failure.
