# init 模式：创建 / 刷新项目测试工作空间

> 入口：SKILL.md 模式路由。目标：让一个项目从"没有工作空间"到"可执行测试模式"，
> 或对已有空间做增量刷新。**先建骨架再填知识，知识宁可标注 draft 也不编造。**

## 空间模型（先讲清楚再动手）

```
<根目录>/<项目名>/
├── workspace.yaml              # 空间元数据 + repos 多仓库登记表
├── package.json / .gitignore
├── repos/                      # ── 代码仓库层：所有 git 仓库收拢在此 ──
│   ├── <后端仓库>/             #   primary（测试模式默认解析对象）
│   └── <前端仓库>/ ...         #   主应用 / 微应用
├── docs/                       # ── 知识层（≈需求/功能/技术文档）──
│   ├── 01-architecture/        #   全局架构：overview / module-map / data-flow
│   ├── 02-modules/<模块>/      #   模块知识：README / feature / link / tech
│   ├── 03-global-links/        #   全局链路：跨模块/跨仓库端到端
│   ├── 04-env-matrix.md        #   环境信息台账
│   ├── 05-test-data.md         #   测试数据台账
│   └── 06-history.md           #   坑史
├── assets/                     # ── 脚本层 ──
│   ├── common/                 #   公共库 + env.json / env.secret.json
│   └── probes/<模块>/          #   探针按模块分目录（与 02-modules 同名对齐）
└── runs/                       # ── 记录层 ──
```

一个测试空间仅对应一个业务项目；workspace.yaml `project` 只填写一个项目名。
空间根直接放 repos/docs/assets/runs，不增加 projects/ 或其他项目子目录。
一个项目可由多个 Git 仓库和黑盒项目/组件组成：源码统一 clone 到 `repos/` 下
（monorepo 一个仓库可含多应用），黑盒登记到同一 externalComponents；
交付物留原处/部署侧。它们共享本项目知识、环境、脚本和记录，测试内容隔离在仓库外。知识层分**三个粒度**：全局架构（拓扑/模块地图/数据流转，
全局视角的模块关系）→ 模块知识（按模块分目录：功能说明/链路说明/技术文档；
黑盒组件也是模块）→ 全局链路（跨模块端到端）。

## 空间组件模型（init 要先问清楚的三类组件）

| 组件类型 | 判别 | init 动作 |
|---|---|---|
| **source 源码仓库**（含 monorepo） | 有 .git、可 clone；monorepo = 一个仓库内多应用（pnpm-workspace/nx/apps 等） | clone 进 repos/，登记 repos（monorepo 附 apps 应用清单） |
| **binary 第三方交付物** | 无 .git、只有 jar/引擎 + 启动脚本 + 配置（如定位引擎） | **不 clone**；登记 externalComponents；建黑盒模块知识目录（只写外部契约） |
| **external 外部服务** | 纯环境依赖（下游系统/硬件） | 只进环境台账 |

## 前置门禁

1. 对话确认**项目名与组件清单**（一次只问一个主题）：
   - 项目名：唯一业务项目名，用主仓库名作建议值，用户确认或改填；多个仓库和
     黑盒项目/组件归属同一业务项目，不逐仓库新建项目空间。已有空间先核对
     workspace.yaml.project；归属不一致时不覆盖原项目配置、不混入无关仓库
   - 源码仓库清单：每个仓库的 remote url、角色（backend / frontend / micro-app）、
     是否主仓库（primary）；**monorepo 追问应用清单**（如 pnpm/nx 的 apps/* 有哪些
     独立部署的应用、构建命令，登记到 repos.<名>.apps）
   - 第三方组件清单：有无无源码的黑盒交付物（引擎 jar/商业组件）？逐个登记
     externalComponents（类型/当前版本/部署位置/启动方式/配置来源）
2. 建空间目录：
   `python3 <skill_dir>/scripts/resolve_workspace.py --project <项目名> --create`
   （自动创建空间目录与 `repos/` 子目录，幂等）
   - 返回 `need_root`（根目录未配置）→ 把脚本给出的 `recommended_root` 作为默认值
     向用户提问（确认或改填），确认后带 `--root <值> --save-root --create` 重跑，
     持久化到 `<workdir>/.agents/.env`，之后不再询问
3. clone 各源码仓库进 `repos/`：`git clone <remote url> <空间>/repos/<仓库名>/`
   （用户日常开发仓库不动；空间内仓库是测试检出，准备分支后测试执行期间内容只读；
   **binary 第三方交付物不 clone**，文件留在原处/环境侧，只登记）
   - 外部源码目录为worktree时先用 `resolve_workspace.py --repo-dir <目录>` 的只读兼容性检查，不能因 `.git` 为文件误判。clone沿用默认，clone完成后用实际Git验证分支与HEAD。
   - 用户明确要求以worktree提供源码时遵守SKILL.md的跨平台指针规则；Windows/WSL两端分别验证，失败不输出初始化成功，不擅自修复外部业务仓库。
4. 环境信息登记（详见第 4 步）：**先从构建配置考古线索**（pom profiles /
   application*.yml / bootstrap.properties / nacos 配置中的地址与中间件），再对话
   确认落盘；用户暂不提供 → 环境相关项标 `未配置`，不阻塞骨架交付

## 标准流程（首次创建）

### 1. 建骨架 + clone 代码仓库

1. `resolve_workspace.py --project <项目名> --create` 建空间目录与 repos/（幂等）
2. 对话确认过的各源码仓库逐个 clone 到 `<空间>/repos/<仓库名>/`，填写 workspace.yaml
   的 `repos` 登记表（url / kind / primary / baseBranch〔基线主干〕/ branch〔当前被测
   分支，测试模式确认后更新〕；monorepo 加 `apps` 应用清单）；binary 组件填
   `externalComponents`（不 clone）
3. 把 `<skill_dir>/templates/` 复制进工作空间并落位：

| 模板 | 落点 |
|---|---|
| `workspace.yaml.example` | `workspace.yaml`（填 project/repos/baseBranch/modules/mcp/environments） |
| `env.example.json` | `assets/common/env.json`（填地址、队列/交换机名、测试数据引用） |
| `docs/architecture/overview.template.md` | `docs/01-architecture/overview.md` |
| `docs/architecture/module-map.template.md` | `docs/01-architecture/module-map.md` |
| `docs/architecture/data-flow.template.md` | `docs/01-architecture/data-flow.md` |
| `docs/module/README|feature|link|tech.template.md` | `docs/02-modules/<模块名>/`（**每个模块一套四件**；小模块可先合并进 README.md） |
| `docs/global-link.template.md` | `docs/03-global-links/<链路名>.md`（**每条端到端链路一篇**） |
| `docs/env-matrix.template.md` | `docs/04-env-matrix.md` |
| `docs/test-data.template.md` | `docs/05-test-data.md` |
| `docs/history.template.md` | `docs/06-history.md` |
| `assets/common/lib.js`、`report.js`、`lib.py`、`report.py` | 原样落位（Node 与 Python 两套公共库） |
| `assets/package.json` | 工作空间根（Node 探针依赖清单，仅当探针用 Node 时 `npm install`） |
| `assets/probes/README.md` | 原样落位（探针按模块分目录的约定与多语言契约） |

4. **空间版本化（推荐）**：`git init` 并推送到私有备份仓，保护越攒越厚的知识资产；
   把 `templates/gitignore.example` 拷为空间根 `.gitignore`（覆盖凭据/登录态/
   repos/ / node_modules / tmp 产物）

探针脚本仅允许 Python（uv）与 Node.js，优先 Python；契约见 SKILL.md"探针脚本契约"；
两套公共库都落位，之后用哪种语言写探针就用哪套。

凭据文件 `env.secret.json` 只创建空骨架 `{"envs": {}}`，值由用户后续填入（不进对话不进 git）。

### 2. 代码考古 → 填知识层草稿（三个粒度，自顶向下）

**第一层：全局架构（01-architecture/）**

1. `overview.md`：系统拓扑、各仓库职责与技术栈、部署单元、外部依赖
2. `module-map.md`：模块清单（模块 × 定位 × 所属仓库 × 代码路径 × 知识目录链接）
   + 模块依赖关系图——**这是影响分析的查表入口，先建它再逐模块展开**。
   扫各仓库的 Controller / MQ Listener / 定时任务 / 前端路由来确定模块划分；
   Maven 多模块仓库按 application 子目录划分（如 monitor / alarm / workorder 各成
   模块）；monorepo 按应用+共享包划分（如 apps/operation、packages-web/components）；
   **binary 组件也是一行**（类型标 binary，无源码路径）
3. `data-flow.md`：核心实体从产生到落点的流转全景（表/routeKey/缓存键粒度）

**第二层：模块知识（02-modules/<模块>/，按模块分目录）**

对 module-map 中每个模块建目录，考古填四件套（小模块可先只建 README.md 合并写）：

1. `README.md`：模块定位与业务边界 + 文档索引 + 探针索引
2. `feature.md`：**功能说明（需求视角）**——功能点 × 触发方式 × 预期行为 × 业务规则；
   判定被测改动"应该表现成什么样"的第一依据
3. `link.md`：**链路说明（模块视角）**——模块内走向（入口→服务→中间件→副作用→
   可观测点）+ 与其他模块的交互表（方向/载体/契约/全局链路链接）
4. `tech.md`：**技术文档**——数据模型（表/字段）、MQ 与接口契约、缓存、关键配置；
   对账断言的技术依据

**黑盒组件（binary）同样建目录**，但只写外部可见的部分：README 标 `type: binary`，
feature 写外部可观察行为，link 只写与本系统的交互（调用/消息），tech 写接口契约、
配置项与启动方式。**考古方法是反推**：grep 本系统调用它的代码、读它的配置文件与
启动脚本、抓包/管理口实测——而不是读它的源码。

**第三层：全局链路（03-global-links/）**

对跨模块/跨仓库的核心业务链路（例：设备属性上报→多系统扇出→页面推送），
每条一篇：端到端走向（触发源→途经模块@仓库→最终副作用）+ 逐环节副作用表
（环节/模块/表/routeKey/断言要点）——跨仓库契约两端都写清。

所有文档头部标 `status: draft`；人审后改 `reviewed`。考古追不动的环节标 `未知`，
**不猜测编造**。draft 文档在测试模式可用，但报告需标注"基于草稿知识，置信度受限"。

### 3. 测试数据挖掘策略（05-test-data.md + env.json fixtures）

**业务数据是变化的：样本 ID/SN 一律不写死，只沉淀"怎么找到合格样本"的策略**；
测试脚本执行时按挖掘 SQL 从目标环境 DB 现查现用。

1. 为关键链路确定"如何找到合格样本"：连目标环境 DB 探索，把**挖掘 SQL / 筛选条件**
   记入 `docs/05-test-data.md`（例："系统数>=2 且在线的设备 LIMIT 1"、
   "有点位且已发布的图纸 LIMIT 1"、"有分组的对象 ORDER BY 更新时间 DESC LIMIT 1"）
2. 每条 SQL 对应的引用键写入 `env.json` 的 `fixtures` 节（**存筛选条件，不存具体 ID**），
   探针经 `lib.py` 的 fixtures + openDb 运行时现查
3. 可附一份"示例快照"（当前查到的样本 + 日期）仅供人工参考，标注"以运行时现查为准"
4. 长整型 ID 一律按字符串处理（JS 精度坑）
5. 连不上 DB → 记录 SQL 草稿标"待验证"，不阻塞骨架交付

### 4. 环境信息登记（构建配置考古 + 对话确认 → 落盘台账）

0. **先考古后提问**（减少问答轮次）：扫各仓库构建配置中的环境线索——
   Maven `pom.xml` 的 profiles（注册中心/中间件地址）、`application*.yml`、
   `bootstrap*.properties`、nacos 配置文件、前端 `.env*`——把发现的地址/中间件/环境名
   整理成**建议清单**，再与用户逐项确认（一次只问一个主题，多环境逐个登记）：
   - 环境名与用途、是否默认环境（workspace.yaml `environments`，全空间仅一个 `default: true`）
   - 运行方式：本地编译启动（local）或现成已启动服务（existing）；登记到
     environments[].executionMode，未知填 null，测试前必明确（不阻塞初始化骨架）。
     local 登记本轮链路所需后端、前端、Nginx、RabbitMQ 等依赖图及构建/启动/配置/
     start-reuse/就绪检查/停止方式，填 runtime.components；详见 [runtime.md](runtime.md)
   - 各服务地址与部署版本指纹获取方式（workspace.yaml `services`，跨仓库部署单元注明来源仓库）
   - 中间件清单：DB / MQ / MQTT / Redis / 注册中心的地址与访问方式
     （env.json `envs.<环境名>`；台账明细 04-env-matrix.md）
   - 前端访问方式（有前端仓库时）：各应用地址、SSO 登录 URL 与方式
     （env.json `envs.<环境>.front`）；测试账号引导用户填入 env.secret.json 的
     `envs.<环境>.front.{username,password}`（值不进对话）
   - MCP 工具：**默认登记 AgentR 本地网关**（`mcp.agentr`：四端点 rust/go/node/python
     + 用途映射），init 时逐端点调 `tools/list` 核对可用工具并更新登记，调
     `*_list_connections` 确认目标环境的连接已在 AgentR 侧登记（缺了提示用户在
     AgentR 中添加）；仅当 AgentR 之外另有专用 MCP server 时才另登记
2. 登记落盘三处保持一致：`workspace.yaml`（索引）+ `assets/common/env.json`（地址/名称）+
   `docs/04-env-matrix.md`（台账明细；凭据只写变量名）
3. 引导用户把凭据填入 `assets/common/env.secret.json`（给出文件路径与键名示例，
   值不进对话）；暂不填不影响骨架交付
4. 连通性校验**可选**：用户明确要求"校验连通性"、或后续探针连接异常时才逐项实测
   （用 lib.js / lib.py 的客户端各连一次），结果更新台账"最近校验"列；
   init 默认不探测，台账如实记录"未校验"不算失败；测试 local 模式下编译启动后
   必做所需服务就绪检查，属于运行准备，不能沿用“未校验”跳过

### 5. 自检与就绪报告

```bash
python3 <skill_dir>/scripts/workspace_check.py --workspace <空间路径>
```

- error 项必须修复（结构缺失 / 明文密钥）；W6 警告（repos/ 下仓库未登记）需处理
- 输出就绪报告：组件登记（源码仓库 N 个〔含 monorepo 应用 M 个〕、binary 组件 K 个，
  primary 是谁）、知识层覆盖（模块 X 个〔source Y + binary Z〕，知识目录 W 套，
  全局链路 V 条，draft/reviewed 各多少）、测试数据样本数、
  环境台账登记情况（环境/中间件/MCP/凭据）、可执行的测试模式建议
- 按最终输出要求汇报：复述需求 → 交付内容 → 关键假设与不确定性

## 增量刷新（已有空间）

1. 新增内容必须归属当前唯一项目；同项目新增 Git 仓库或黑盒组件复用当前空间，
   分别更新 repos/externalComponents，黑盒补模块知识。独立业务项目另建空间。
   只处理 delta：新增模块 → module-map 加行 + 建 `02-modules/<模块>/` 目录（四件套）；
   模块功能已删 → 该模块目录标 `deprecated` 不直接删（历史测试报告还引用它）；
   monorepo 新增应用 → repos.apps 补登记
2. **仓库清单变更**：新增仓库 → clone 进 `repos/` + 登记 + 补考古；
   移除仓库 → repos 标 `deprecated`（目录保留）
3. `workspace.yaml` 的 modules / repos.baseBranch 过期 → 更新
4. 测试数据失效（SQL 查不到合格样本）→ 更新挖掘 SQL 并标注变更原因；
   用户要求时做连通性校验，更新"最近校验"列
5. 环境信息变更（换地址/中间件/MCP）→ 对话确认后同步更新台账三文件
   （workspace.yaml / env.json / 04-env-matrix.md）
6. 运行方式/启动命令/依赖变化时，同步更新 environments[].executionMode/runtime、
   环境台账和 env.json 实际地址；本轮计划与报告记录所用方式
7. 刷新后同样跑 `workspace_check.py` 并简报变更摘要

## 硬性规则

- 遵守 SKILL.md 的“仓库只读约束”：分支检出限准备阶段；测试执行期间不修改任何
  业务仓库内容，包括配置、依赖/锁文件、自带测试、构建产物与缓存。需要本地运行
  使用仓库外副本；有本地修改时保留原样，不 stash/reset/clean。
  不在任何业务 Git 仓库新增或修改单元/集成/E2E 测试，脚本仅用 Python（uv）或 Node.js
- 尽量使用 E2E：知识层登记真实业务入口、完整链路与最终结果，前端优先 Playwright；
  无法跑完整链路时登记降级原因和覆盖缺口
- 测试脚本优先 Python（uv run）；测试输入样本与预期值一律运行时从目标环境 DB 现查，
  禁止把 ID/SN 写死在脚本或 fixtures 里
- 知识/脚本/记录层只存在于 `repos/` 之外，**永不写进任何代码仓库目录**
- `assets/probes/<模块>/` 与 `docs/02-modules/<模块>/` 同名对齐；探针变更同步更新
  模块 README 的"已沉淀探针"
- 凭据不写进任何文档；docs 里只记"脱敏目标 + 变量名"
- 知识层内容来自代码考古、对话登记与环境实测，禁止凭记忆/猜测填写；
  不确定就标 `未知`
- 每次刷新在 `docs/06-history.md` 追加一行（日期 + 变更摘要）
