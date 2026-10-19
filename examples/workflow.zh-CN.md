# 完整中文工作流

[English workflow](workflow.md)

请在仓库根目录运行，并先激活虚拟环境。脚本会把 `examples/example.dbc` 复制到临时目录。每次修改都使用 `--output` 写入新文件，因此在清理临时目录之前，原始输入和所有中间阶段都保持不变。

本示例会添加节点和一个标准多路复用报文，修改信号比例，更新并临时扩展现有的嵌套多路复用树，安全删除无依赖实体，将结果与原始文件比较，最后检查并验证文件。

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

# 修改前先验证。
"${CLI[@]}" validate "$ORIGINAL"

# 添加节点、报文、根选择器和两个标准多路复用分支。
edit node add "$CURRENT" Gateway --comment "Gateway ECU"
edit message add "$CURRENT" 0x500 Diagnostics --length 8 --sender Gateway --cycle-time 100
edit signal add "$CURRENT" Diagnostics DiagMode --start 0 --length 8 --multiplexer
edit signal add "$CURRENT" Diagnostics Temperature --start 8 --length 16 --factor 0.5 --offset -40 --minimum -40 --maximum 215 --unit '°C' --receiver Gateway --multiplexer-of DiagMode --multiplexer-values 0
edit signal add "$CURRENT" Diagnostics Voltage --start 8 --length 16 --factor 0.1 --minimum 0 --maximum 100 --unit V --multiplexer-of DiagMode --multiplexer-values 1

# 修改比例，其他字段保持不变。
edit signal update "$CURRENT" Diagnostics Voltage --factor 0.25

# 在现有扩展树中明确使用逗号列表和闭区间语法。
edit signal update "$CURRENT" Status SubMode --multiplexer-values 1,2
edit signal add "$CURRENT" Status ExtendedPayload --start 40 --length 16 --multiplexer-of SubMode --multiplexer-values 4-5

# 删除前先检查；这两个实体均未被引用。
edit node add "$CURRENT" Scratch
"${CLI[@]}" node show "$CURRENT" Scratch
edit node delete "$CURRENT" Scratch
"${CLI[@]}" signal show "$CURRENT" Status ExtendedPayload
edit signal delete "$CURRENT" Status ExtendedPayload

# 检查最终实体，只读比较两个输入，并验证结果。
"${CLI[@]}" signal show "$CURRENT" Diagnostics Voltage
"${CLI[@]}" signal show "$CURRENT" Status SubMode
"${CLI[@]}" compare "$ORIGINAL" "$CURRENT"
"${CLI[@]}" validate "$CURRENT"
"${CLI[@]}" summary "$CURRENT"
```

最终摘要为 `node_count: 1`、`message_count: 2`、`signal_count: 7`。虽然比较结果的 `result.equal` 为 `false`，但有效比较仍返回退出码 0；差异属于结果数据，不是 CLI 错误。
