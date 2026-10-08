# init 模式：创建 / 刷新项目测试工作空间

> 入口：SKILL.md 模式路由。目标：让一个项目从"没有工作空间"到"可执行测试模式"，
> 或对已有空间做增量刷新。**先建骨架再填知识，知识宁可标注 draft 也不编造。**

## 空间模型（先讲清楚再动手）

```
<根目录>/<项目名>/
├── workspace.yaml      # 空间元数据 + repos 多仓库登记表
├── <仓库1>/            # git clone 的代码仓库（与 docs/assets/runs 平级）
├── <仓库2>/            # 前端主应用 / 微应用等更多仓库
├── docs/               # 知识层（仓库之外，永不被提交进业务仓库）
├── assets/             # 脚本层
└── runs/               # 记录层
```

一个项目一个空间，一个空间可含 1~N 个 git 仓库（前后端分离、微前端）。
代码仓库 clone 进空间与 docs 平级——测试内容物理隔离在仓库外。

## 前置门禁

1. 对话确认**项目名与仓库清单**（一次只问一个主题）：
   - 项目名：用主仓库名作建议值，用户确认或改填（多仓库项目常用业务名）
   - 仓库清单：每个仓库的 remote url、角色（backend / frontend / micro-app）、
     是否主仓库（primary）
2. 建空间目录：
   `python3 <skill_dir>/scripts/resolve_workspace.py --project <项目名> --create`
   - 返回 `need_root`（根目录未配置）→ 把脚本给出的 `recommended_root` 作为默认值
     向用户提问（确认或改填），确认后带 `--root <值> --save-root --create` 重跑，
     持久化到 `<workdir>/.agents/.env`，之后不再询问
3. clone 各仓库进空间：`git clone <remote url> <空间>/<仓库名>/`
   （用户日常开发仓库不动；空间内仓库是测试检出，只读为主）
4. 环境信息通过**对话登记**（详见第 4 步）：首次创建必须逐项问清目标环境并落盘台账；
   用户暂不提供 → 只建骨架和 docs 草稿，环境相关项标 `未配置`，不阻塞骨架交付

## 标准流程（首次创建）

### 1. 建骨架 + clone 代码仓库

1. `resolve_workspace.py --project <项目名> --create` 建空间目录（幂等）
2. 对话确认过的各仓库逐个 clone 到空间根下（目录名=仓库名），
   并填写 workspace.yaml 的 `repos` 登记表（url / kind / primary / baseBranch）
3. 把 `<skill_dir>/templates/` 复制进工作空间并改名：

| 模板 | 落点 |
|---|---|
| `workspace.yaml.example` | `workspace.yaml`（填 project/repos/baseBranch/modules/mcp/environments） |
| `env.example.json` | `assets/common/env.json`（填地址、队列/交换机名、测试数据引用） |
| `docs/*.template.md` | `docs/02-feature-map.md`、`docs/03-links/`、`docs/04-env-matrix.md`、`docs/05-test-data.md`、`docs/06-history.md` |
| `assets/common/lib.js`、`report.js` | 原样落位（Node 公共库） |
| `assets/common/lib.py`、`report.py` | 原样落位（Python 公共库，配合 uv 使用） |
| `assets/package.json` | 工作空间根（Node 探针依赖清单，仅当探针用 Node 时 `npm install`） |
| `assets/probes/README.md` | 原样落位（探针目录约定与多语言契约） |

4. 空间根建 `.gitignore`（若空间要版本化）：`env.secret.json`、`node_modules/`、
   各代码仓库目录

探针脚本语言不限（Node / Python(uv) / Shell…），契约见 SKILL.md"探针脚本契约"；
两套公共库都落位，之后用哪种语言写探针就用哪套。

凭据文件 `env.secret.json` 只创建空骨架 `{"envs": {}}`，值由用户后续填入（不进对话不进 git）。

### 2. 代码考古 → 填 docs 草稿

1. **功能索引（02-feature-map.md）**：扫各仓库的模块结构、Controller、MQ Listener、
   定时任务 → 每个功能域一行：功能域 | 所属仓库 | 入口（API/topic/定时） | 涉及模块 | 链路文档链接
2. **链路地图（03-links/）**：沿每个入口追调用链（入口→服务→中间件交互→
   DB/缓存/MQ 副作用→可观测点→已沉淀探针），每个功能域 1~N 篇；
   **跨仓库链路**（后端 API/消息 ↔ 前端页面/订阅）在一篇内写清两端仓库、
   接口 URL/topic 契约与版本约定；追不动的部分标 `未知`，**不猜测编造**
3. **架构（01-architecture.md，可选）**：从应用配置/Nacos 读中间件依赖、topic/队列全景；
   含各仓库职责与相互调用关系（服务拓扑）
4. 所有生成文档头部标 `status: draft`；人审后改 `reviewed`。
   draft 文档在测试模式可用，但报告需标注"基于草稿知识，置信度受限"

### 3. 挖测试数据（05-test-data.md + env.json fixtures）

1. 连目标环境 DB，为关键链路找"配置齐全的真实样本"（例：有多系统扇出的设备、
   有点位的图纸、有分组的对象），记录 ID/SN/关键外键
2. 样本写入 `docs/05-test-data.md`（表格：用途 | 标识 | 关键关联 | 挖掘日期），
   引用键写入 `env.json` 的 `fixtures` 节
3. 长整型 ID 一律按字符串记录（JS 精度坑）
4. 连不上 DB → 本步跳过，标注"待补"，不阻塞骨架交付

### 4. 环境信息登记（对话收集 → 落盘台账）

1. 与用户对话逐项确认（一次只问一个主题，多环境逐个登记）：
   - 环境名与用途、是否默认环境（workspace.yaml `environments`，全空间仅一个 `default: true`）
   - 各服务地址与部署版本指纹获取方式（workspace.yaml `services`，跨仓库部署单元注明来源仓库）
   - 中间件清单：DB / MQ / MQTT / Redis / 注册中心的地址与访问方式
     （env.json `envs.<环境名>`；台账明细 04-env-matrix.md）
   - 可用的 MCP server 清单（workspace.yaml `mcp` 登记表；没有 MCP 就登记为脚本直连）
2. 登记落盘三处保持一致：`workspace.yaml`（索引）+ `assets/common/env.json`（地址/名称）+
   `docs/04-env-matrix.md`（台账明细；凭据只写变量名）
3. 引导用户把凭据填入 `assets/common/env.secret.json`（给出文件路径与键名示例，
   值不进对话）；暂不填不影响骨架交付
4. 连通性校验**可选**：用户明确要求"校验连通性"、或后续探针连接异常时才逐项实测
   （用 lib.js / lib.py 的客户端各连一次），结果更新台账"最近校验"列；
   init 默认不探测，台账如实记录"未校验"不算失败

### 5. 自检与就绪报告

```bash
python3 <skill_dir>/scripts/workspace_check.py --workspace <空间路径>
```

- error 项必须修复（结构缺失 / 明文密钥）；W6 警告（空间内仓库未登记）需处理
- 输出就绪报告：代码仓库登记情况（N 个仓库，primary 是谁）、文档覆盖率
  （功能域 X 个，链路 Y 条，draft/reviewed 各多少）、测试数据样本数、
  环境台账登记情况（环境 X 个、中间件 Y 项、MCP Z 个、凭据是否已配）、
  可执行的测试模式建议
- 按最终输出要求汇报：复述需求 → 交付内容 → 关键假设与不确定性

## 增量刷新（已有空间）

1. 只处理 delta：新增模块/入口 → 补 feature-map 行 + 新链路文档；
   已删功能 → 标记 `deprecated` 不直接删（历史测试报告还引用它）
2. **仓库清单变更**：新增仓库 → clone 进空间 + repos 登记 + 补考古；
   移除仓库 → repos 标 `deprecated`（目录保留，历史报告还引用）
3. `workspace.yaml` 的 modules / repos.baseBranch 过期 → 更新
4. 测试数据失效（样本被环境清理）→ 重挖并更新台账与 fixtures
5. 环境信息变更（换地址/中间件/MCP）→ 对话确认后同步更新台账三文件
   （workspace.yaml / env.json / 04-env-matrix.md）；用户要求时做连通性校验，
   更新"最近校验"列
6. 刷新后同样跑 `workspace_check.py` 并简报变更摘要

## 硬性规则

- 不修改任何业务仓库的文件；空间内代码仓库除"检出/更新被测分支"外只读
- docs/assets/runs 只存在于仓库之外（与仓库平级），**永不写进任何代码仓库目录**
- 凭据不写进任何文档；docs 里只记"脱敏目标 + 变量名"
- docs 与台账内容来自代码考古、对话登记与环境实测，禁止凭记忆/猜测填写；
  不确定就标 `未知`
- 每次刷新在 `docs/06-history.md` 追加一行（日期 + 变更摘要）
