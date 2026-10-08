# fulllink-test

git 变更驱动的全链路测试引擎 + 项目测试工作空间管理器（skill）。

## 是什么

对任意前后端项目（含前后端分离、前端微应用等**多仓库**项目）：基于 git diff 定位
受影响链路，按"业务结果对账"标准执行全链路测试，并把每次测试产出的知识/脚本/数据
沉淀回工作空间，越用越厚。

- **测试模式**（五步）：解析 diff（各仓库当前分支自分叉点以来的全部修改）→
  影响分析（含跨仓库影响）→ 测试计划 → 执行对账 → 报告与资产沉淀；
  不设环境校验门禁，环境信息直接用台账
- **init 模式**：创建/刷新项目测试工作空间（代码仓库层 + docs 知识层 + assets 脚本层
  + runs 记录层）；环境信息通过对话逐项登记入台账，后续可修改、可按需校验连通性

## 空间模型

一个项目一个空间；一个空间可含 1~N 个 git 仓库（前后端分离/微前端）。
代码仓库 clone 在空间内、与 docs/assets/runs **平级**——测试内容物理隔离在仓库外，
永不被提交进业务仓库。

## 关键约定

- 工作空间根目录：首次使用时询问用户确认（AI 按系统目录推荐默认值，如
  `D:/develop/testspaces`、`~/develop/testspaces`），确认后持久化到
  `<workdir>/.agents/.env` 的 `FULLLINK_TESTSPACES_ROOT`
- 项目名 init 时经用户确认（多仓库项目常用业务名而非仓库名）；仓库清单登记在
  workspace.yaml 的 `repos`（url / kind / primary / baseBranch）
- 探针脚本语言不限（Node.js / Python(uv) / Shell 等，见 SKILL.md"探针脚本契约"），
  公共库模板自带 Node 与 Python 两套；探针依赖一律装在工作空间侧，不进 skill 包
- 凭据只存 `<workspace>/assets/common/env.secret.json`（gitignore），永不进 skill 包与报告
- 对账标准与报告格式见 [contracts/report-contract.md](contracts/report-contract.md)
- init 流程详见 [init.md](init.md)

## 脚本

| 脚本 | 用途 | 运行 |
|---|---|---|
| `scripts/resolve_workspace.py` | 代码目录 → 所属空间定位（向上找 workspace.yaml）；空间外 git 仓库识别（mode: external）；创建项目空间 | `python3 scripts/resolve_workspace.py --repo-dir <代码目录>` 或 `--project <项目名> [--root <根>] [--save-root] [--create]` |
| `scripts/workspace_check.py` | 工作空间结构完整性、密钥卫生与仓库登记一致性校验 | `python3 scripts/workspace_check.py --workspace <空间>` |

均为 Python 3.9+ 纯标准库，JSON 输出。单测：`python3 -m unittest discover -s tests -v`

## 模板

`templates/` 为工作空间脚手架源：workspace.yaml（含 repos 多仓库登记表）/ env.json /
docs 模板 / 公共库两套（Node：lib.js + report.js；Python：lib.py + report.py，配合 uv
内联依赖使用）/ 探针目录约定（assets/probes/README.md）。Node 依赖
（amqplib/mysql2/mqtt）安装在工作空间侧。
