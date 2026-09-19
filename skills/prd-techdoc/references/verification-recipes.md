# 交付前机器化自检手册

本文件定义可执行的自检步骤。**这些检查是交付门槛，不是可选建议**：任何一项不通过都必须先修文档再重跑，最终答复要给出“检查项 / 结果”的数字。机器化检查全部由本 skill 内置的 `scripts/` 本地 Python 脚本完成，不依赖 MCP 服务、宿主子代理工具或预装 mmdc。

约定：
- `$md` 表示被校验的技术文档路径。
- `$work` 表示 skill 运行时工作目录（`.agents/.env` 所在目录），默认为当前目录。
- **依赖用 uv 管理**：优先 `uv run scripts/xxx.py ...`，uv 依据脚本内联元数据（PEP 723）自动创建隔离环境并安装依赖，不污染全局；无 uv 时纯标准库脚本（check-doc / check-mermaid）可直接 `python` 运行，db-schema-check 在无 pymysql 时自动降级 mysql CLI。
- 命令示例跨平台通用（bash / PowerShell / cmd 均按原样执行）。
- 所有脚本只读文档，不修改文档；修改一律走主调用方。
- 脚本以非零退出码表示发现问题：`1` = 检查未通过；`2` = 输入或环境缺失（降级场景，不视为文档失败）。

## 0. 环境信息（.agents/.env）

本地脚本需要的可选配置保存在 `$work/.agents/.env`（UTF-8，`键=值`，`#` 注释）：

| 键 | 用途 |
| --- | --- |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | 真实 MySQL 连接（第 4 步用） |
| `MMDC_PATH` / `CHROME_PATH` | 可选 mermaid-cli 真实渲染器（第 2 步用） |
| `BACKEND_PATH` / `FRONTEND_PATH` | 前后端项目路径（风格对齐用） |

- 缺少所需键时脚本以退出码 2 结束并打印 `MISSING_ENV`；此时由主调用方提示用户输入，写入 `.agents/.env` 后重跑。脚本自身不写该文件。
- 用户拒绝提供时按各步降级说明处理，不阻塞交付。
- 键清单与示例见 `scripts/env.example`。

## 1. 结构与一致性自检（P0）

```bash
uv run scripts/check-doc.py --md $md        # 推荐：uv 隔离运行
python scripts/check-doc.py --md $md        # 等效：纯标准库直接运行
```

覆盖并输出以下数字（通过标准与判定）：
- 一级标题：`h1_count=6`、`h1_order=OK`、`forbidden=0`（数量、名称与顺序符合 Output Contract；未出现 `方案概述`、`背景`、`收益`、`风险`、`排期`、`迁移方案`、`验收用例`、`事务与并发` 等禁用章节）
- 状态机：`state_diagrams=N bad_headings=0 bad_notes=0`（每个 stateDiagram 的最近上级标题必须是二级标题，闭图后必须紧跟列表/引用说明）
- 增量字典：`missing_table=0`、`orphan_table=0`、`duplicate_table=0`、`type_invalid=0`、`empty_table=0`（使用清单编码与字典枚举项三级标题一一对应；字典类型只出现 常量字典/全局字典/自定义字典）
- 重复状态字段：`status_field_candidates=N`（列出全部 xxx_status/status 列，人工确认同实体不存在取值一一对应的同义双状态字段）
- 悬空引用：`dangling_refs=0`（“见《某章节》”必须指向存在的标题）
- 非 MySQL 方言：`non_mysql_hits=0`（命中即说明输出了其他数据库方言或相关讨论，必须删除后重跑）
- ER/SQL 对应（P1）：`er_without_table=0 table_without_er=0`（复用/外部表除外，人工确认）

退出码 0 表示 P0 全部通过（P1 项仅提示不阻断）。P0 项命中会逐条打印 `行号 + 原文`。

重复状态字段判定要点：
- 两个状态列的取值能一一映射（例如 A 的 X/Y/Z 恰好对应 B 的空/部分/全部）→ 必须合并为一个，保留业务口径更明确、并能直接映射页面文案的那个。
- 合并后，未发生状态用 NULL 表达，页面显示 `-`，不落库该展示值。
- 合并决定要写入冲突/采用口径段。

## 2. Mermaid 全量校验（P0）

```bash
uv run scripts/check-mermaid.py --md $md --work-dir $work
python scripts/check-mermaid.py --md $md --work-dir $work
```

行为与通过标准：
- 配置了 `MMDC_PATH`（或 PATH 中存在 mmdc）时：逐块真实渲染，通过标准 `failures=0`；全部渲染失败视为渲染环境问题（检查 `CHROME_PATH`），自动回退 lint 结果并提示 `WARN RENDER_ENV_BROKEN`。
- 未配置时：执行内置结构化 lint（图类型、空块、未闭合、引号不配对、未加引号的 ASCII 括号/竖线/冒号、erDiagram/stateDiagram/sequenceDiagram 常见语法错误），输出 `mode=lint`；通过标准 `failures=0`，并在最终答复说明“未做真实渲染校验，仅本地结构化 lint”。

常见失败原因与修法：
- 节点标签含未加引号的 ASCII `(` `)` `|` `:` → 改为全角标点，或把整个标签写成 `A["文本(含括号)"]`
- `stateDiagram-v2` 中把状态名与描述写反、状态名含空格，或使用了 Mermaid 保留字
- `flowchart` 连线引用了未定义的节点编号（例如改图时漏改中间节点）
- `erDiagram` 实体块 `{`/`}` 不配对、属性行/关系行语法错误

## 3. 脚本未覆盖的必做人工核对（P0，人工）

对本次会话新增的每条口径变更，逐项确认六处已同步：
1. ER 字段（新增/删除/改名）
2. SQL 字段注释与取值枚举
3. 状态机节点与图后说明
4. 数据流转图节点
5. 接口备注与前置校验、错误码
6. 增量字典的字段行与字典项

并确认冲突/采用口径段记录了该裁决与依据。任一处缺失即回到文档补齐后重跑第 1、2 步。

## 4. 真实库表核对（可选，替代 dbhub MCP）

```bash
# 核对指定表（推荐：传入增量 SQL 中涉及的表名，逗号分隔）；uv 自动隔离安装 pymysql
uv run scripts/db-schema-check.py --tables "t_a,t_b" --work-dir $work
# 仅列出库中全部表；无 uv/无 pymysql 时自动降级本机 mysql 客户端
python scripts/db-schema-check.py --work-dir $work
```

- 需要 `.agents/.env` 配置 `DB_*`；优先 pymysql（uv 依赖隔离），降级本机 `mysql` 客户端；两者都缺失时脚本退出码 2 并给出 `MISSING_ENV` / `MISSING_TOOL` 提示——此时提示用户输入配置或确认跳过，并在“待确认与需求冲突”段注明“未连接真实库核对 schema，建表/迁移前需以目标库实际结构为准”。
- 通过标准：文档中每个“新增/变更”表都能在真实库中得到预期结果（新表不存在、变更表结构与文档一致）。
- 口令经环境变量（pymysql 参数 / `MYSQL_PWD`）传递，不出现在命令行。

## 5. 自检结果输出模板

交付答复中按以下格式给出数字：

```text
- 结构自检（check-doc.py）：h1=6 order=OK forbidden=0；状态机 count=N bad_headings=0 bad_notes=0；字典 missing=0 orphan=0 duplicate=0；悬空引用 0；非 MySQL 方言 0；ER/SQL 对应缺失 0
- Mermaid（check-mermaid.py）：mode=render|lint blocks=N failures=0
- 真实库核对（db-schema-check.py）：done(pymysql|mysql cli)|skipped（原因）
- 重复状态字段：N（应为 0，人工确认）
- 关键写接口缺失权限/状态/幂等或最小测试依据：0
```
