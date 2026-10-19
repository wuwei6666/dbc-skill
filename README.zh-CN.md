# DBC CRUD Agent Skill

[English](README.md)

本项目提供结构化命令行 Skill，用于创建、查看、更新、删除、验证和比较 CAN DBC 数据库。支持节点、报文、信号、Classic CAN 与 CAN FD 帧元数据、标准及扩展多路复用、JSON 输出，以及确定性的节点/报文/信号比较。

## 环境要求与安装

- Python 3
- `requirements.txt` 中固定的依赖（`cantools==40.7.1`）

在仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
source .venv/bin/activate
```

安装 Skill 时请保留仓库目录结构：`SKILL.md`、`references/`、`examples/` 和 `scripts/` 之间使用相对路径。所有命令均从仓库根目录执行。

## 快速开始

```bash
# 创建并验证空数据库。
python3 scripts/dbc_crud.py --json init demo.dbc
python3 scripts/dbc_crud.py --json validate demo.dbc

# 添加节点、报文和信号。
python3 scripts/dbc_crud.py --json node add demo.dbc ECU_A --comment "车身控制器"
python3 scripts/dbc_crud.py --json message add demo.dbc 0x123 Status --length 8 --sender ECU_A
python3 scripts/dbc_crud.py --json signal add demo.dbc Status State --start 0 --length 8

# 检查结果并再次验证。
python3 scripts/dbc_crud.py --json signal show demo.dbc Status State
python3 scripts/dbc_crud.py --json summary demo.dbc
python3 scripts/dbc_crud.py --json validate demo.dbc
```

报文引用可以使用名称、十进制帧 ID 或 `0x` 十六进制帧 ID。全局选项必须放在命令之前，例如 `python3 scripts/dbc_crud.py --json --encoding utf-8 summary demo.dbc`。

## 安全修改与规范化

- `node`、`message` 和 `signal` 的新增、更新、删除操作都通过 cantools 保存。默认原地保存会创建包含原始字节的 `PATH.bak`；检查结果期间请保留该备份。
- `--output OTHER.dbc` 写入独立文件并保持输入不变，是删除或实验性修改的优先选择。
- `--no-backup` 会在原地保存时禁用 `.bak`。仅对临时文件或已有其他备份的文件使用。
- 保存会规范化 DBC 文本，并不保证逐字节无损保留注释、格式或 cantools 未建模的构造。CLI 会先写临时文件、严格重新加载并检查多路复用元数据，然后替换目标文件。
- 默认编码为 UTF-8。可用全局 `--encoding` 指定源文件和目标文件编码，例如兼容旧文件时使用 `cp936`。

## CAN 与 DBC 能力

- 标准帧 ID 范围为 `0` 至 `0x7FF`；使用 `--extended` 的扩展帧 ID 范围为 `0` 至 `0x1FFFFFFF`。
- Classic CAN 报文长度为 1–8 字节；使用 `--fd` 的 CAN FD 报文长度为 1–64 字节。
- 标准多路复用使用根选择器和分支值。扩展多路复用支持嵌套选择器以及多个值/范围，并按需使用 DBC `SG_MUL_VAL_` 元数据。
- 信号最小值和最大值必须同时存在或同时缺省。整数 `0|0` 被保留为“无边界”；浮点零可以表示。清除或设置边界前请阅读字段参考。
- 比较时，节点按名称识别，报文按帧 ID 加帧类型识别，信号按父报文身份加信号名识别。有效输入无论相等或不同都返回退出码 0。

## 文档

- [Agent Skill](SKILL.md)
- [完整 CLI 参考与真实比较 JSON 示例](references/cli-reference.md)
- [DBC 字段与验证规则](references/dbc-fields.md)
- [Complete English workflow](examples/workflow.md)
- [完整中文工作流](examples/workflow.zh-CN.md)

两个工作流都使用临时副本，并通过 `--output` 将每次修改写入新文件，覆盖 CRUD、比例修改、标准和扩展多路复用、安全删除、比较、最终检查与验证。

## 测试

```bash
.venv/bin/python -m unittest tests.test_docs -v
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## 许可证

基于 [MIT License](LICENSE) 发布。
