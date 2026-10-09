# fulllink-test

git 变更驱动的全链路测试引擎 + 项目测试工作空间管理器（skill）。

## 是什么

对任意前后端项目（含前后端分离、前端微应用等**多仓库**项目）：基于 git diff 定位
受影响链路，按"业务结果对账"标准执行全链路测试，并把每次测试产出的知识/脚本/数据
沉淀回工作空间，越用越厚。

- **测试模式**（五步）：对话确认被测仓库与各仓库被测分支（未提供分支则拒绝）→
  解析变更（各仓库指定分支自分叉点以来的全部修改，monorepo 按应用分组；含
  binary 组件版本变更）→ 影响分析（含跨仓库/跨组件影响）→ 测试计划 → 执行对账
  （**脚本优先**：后端/中间件用 Python/uv，前端页面（Vue 等）优先 skill 生成的
  playwright 脚本；不值得写脚本的一次性查询/取证辅以 AgentR MCP（四端点约 90
  工具）；人工兑底；测试输入与预期值均运行时从 DB 现查）→ 报告与资产沉淀；
  每轮明确 local/existing；local 必须编译启动并核实所需服务就绪，环境信息从台账读取
- **init 模式**：创建/刷新项目测试工作空间；环境信息**先从构建配置考古线索**
  （pom profiles / yml / bootstrap.properties）再对话确认，登记入台账，后续可修改、
  可按需校验连通性

## 空间模型

**一个测试空间只放一个业务项目，一个业务项目可以包含多个 Git 仓库和黑盒项目/组件。**
空间根直接包含 workspace.yaml、repos/、docs/、assets/、runs/，不增加 projects/ 层级。
workspace.yaml.project 是唯一项目名；同项目新增仓库或黑盒组件复用该空间。
`<测试空间根目录>/<项目名>/` 是具体项目空间，前面的根目录仅是存放位置。

组件可位于测试空间内或用户提供的外部路径，不强制 clone/搬迁。
**source 源码仓库**（含 monorepo）登记 repos.<名>.path；
**binary 黑盒项目/组件**登记 externalComponents.<名>.path 或服务入口与契约
（版本变化触发回归）；**external 外部服务**
只进环境台账。知识/脚本/记录层与 repos/ 平级——测试内容永不被提交进业务仓库。

知识层三粒度：全局架构（overview / module-map 模块地图 / data-flow 数据流转）→
模块知识（`02-modules/<模块>/` 四件套：README / feature 功能说明 / link 链路 /
tech 技术文档，相当于需求+功能+技术文档）→ 全局链路（`03-global-links/` 跨模块
端到端）。探针按模块分目录（`assets/probes/<模块>/`）与知识层同名对齐。

## 关键约定

- **明确运行方式**：local（本地编译启动）或 existing（现成已启动服务），未说明先询问。
  local 从指定 commit 的仓库外非 Git 副本构建，准备并检查链路所需后端、前端、
  Nginx、RabbitMQ 等依赖后执行 E2E；缺服务或启动失败阻断相关测试并生成报告。
  复用服务明确来源，收尾只停止本轮启动实例。详见 [runtime.md](runtime.md)

- **空间内外 Git 与黑盒组件始终只读**：不切分支/fetch/修 worktree，不改源码、
  配置、锁文件、自带测试，不在原目录安装/构建/输出产物。只读解析指定分支 commit，
  本地运行用隔离副本。启动或服务异常立即对话提示用户并记录阻断，不自动修复。
  脚本、录像及报告放组件目录外，执行前后记录 Git 与黑盒路径只读检查
- **UI 自动化全程录屏，放慢操作供人工核对**：Playwright 等工具均适用，默认
  slowMo 500ms、结果展示后停留 1000ms。视频保存在 runs/<主题>/videos/，失败及
  重试也保留；报告提供视频链接与人工核对状态。详见 [ui-recording.md](ui-recording.md)
- **尽量使用 E2E（端到端）测试**：前端优先 Playwright 用户流程，后端通过真实
  API/消息/任务入口贯穿链路并核对最终业务结果；单点检查作为补充，E2E 受阻时
  报告说明原因及未覆盖环节

- 工作空间根目录：首次使用时询问用户确认（AI 按系统目录推荐默认值，如
  `D:/develop/testspaces`、`~/develop/testspaces`），确认后持久化到
  `<workdir>/.agents/.env` 的 `FULLLINK_TESTSPACES_ROOT`
- 项目名 init 时经用户确认（多仓库项目常用业务名而非仓库名）；仓库清单登记在
  workspace.yaml 的 `repos`（url / kind / primary / baseBranch）
- 测试脚本**仅用 Python（uv）与 Node.js**，优先 Python（PEP 723 内联依赖）；
  不在任何业务 Git 仓库新增或修改单元/集成/E2E 测试，所有测试脚本在工作空间侧生成；
  公共库模板自带两套，依赖也安装在工作空间侧
- 测试样本不写死：只沉淀挖掘 SQL/筛选条件（05-test-data.md + env.json fixtures），
  脚本执行时从目标环境 DB 现查现用
- 交互式工具辅以 **AgentR 本地网关 MCP**（127.0.0.1:8319 四端点约 90 个工具：
  MySQL/Kingbase/SQLite/Redis/MQTT/WebSocket/HTTP（rust）、RabbitMQ/RocketMQ（go）、
  SSH/TDEngine（node）、schedule（python）），用于一次性查询与取证；
  可复跑的验证一律沉淀为脚本
- 凭据只存 `<workspace>/assets/common/env.secret.json`（gitignore），永不进 skill 包与报告
- 对账标准与报告格式见 [contracts/report-contract.md](contracts/report-contract.md)
- init 流程详见 [init.md](init.md)

## 脚本

| 脚本 | 用途 | 运行 |
|---|---|---|
| `scripts/resolve_workspace.py` | 代码目录 → 所属空间定位（向上找 workspace.yaml）；空间外 git 仓库识别（mode: external）；创建项目空间 | `python3 scripts/resolve_workspace.py --repo-dir <代码目录>` 或 `--project <项目名> [--root <根>] [--save-root] [--create]` |
| `scripts/workspace_check.py` | 工作空间结构完整性、密钥卫生与仓库登记一致性校验 | `python3 scripts/workspace_check.py --workspace <空间>` |
| `scripts/report_html.py` | 测试报告 Markdown → 自包含 HTML（状态标色），默认自动打开 | `python3 scripts/report_html.py <report.md> [--no-open]` |

均为 Python 3.9+ 纯标准库，JSON 输出。单测：`python3 -m unittest discover -s tests -v`

## 模板

`templates/` 为工作空间脚手架源：workspace.yaml（含 repos 多仓库登记表）/ env.json /
知识层模板（architecture/ 三件 + module/ 四件套 + global-link / env-matrix /
test-data / history）/ 公共库两套（Node：lib.js + report.js；Python：lib.py +
report.py，配合 uv 内联依赖使用）/ 探针目录约定（assets/probes/README.md，
按模块分目录）。Node 依赖（amqplib/mysql2/mqtt）安装在工作空间侧。
