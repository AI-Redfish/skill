# 测试执行通道与工具依赖（细节分册）

> 由 SKILL.md「执行对账」与「探针脚本契约」导引进入；本文件是执行通道三选一、AgentR MCP 工具源、探针脚本契约的完整细则。

## 执行通道（三选一：每个测试点归入且仅归入一列）

三通道是"用什么手段验证"的**互斥分类**（不是流程步骤）。**总原则：脚本优先**——
能沉淀、能复跑、能进 CI 的验证一律用脚本；MCP 只做不值得写脚本的一次性查询与
取证；人眼确认的才进人工。匹配顺序：

```
① 沉淀库已有探针（assets/probes/<模块>/）→ 直接复用（uv run / playwright）
② 没有 → 本轮生成脚本放 runs/<run-id>/tmp/，测后择优沉淀：
     - 后端/中间件验证 → Python（uv run，PEP 723 内联依赖）
     - 前端页面验证（Vue 等）→ **playwright 脚本（Python + uv）**，不用仓库自带 e2e
③ 不值得写脚本（一次性查询/临时取证/快速冒烟）→ MCP（AgentR）
④ 自动化覆盖不了（视觉效果/人眼确认）→ 人工清单
```

| 通道 | 适用 | 说明 |
|---|---|---|
| **脚本**（主力；沉淀库 `assets/probes/` ↔ 本轮生成 `runs/<run-id>/tmp/`） | 绝大多数验证：DB/MQ/缓存对账、协议细节（retained、prefetch）、定时采样、压测、多步事务、HTTP 接口断言，**以及前端页面 e2e（Vue 等项目优先 playwright 脚本，由本 skill 生成，不用仓库自带 e2e）** | 优先复用沉淀库；没有则本轮生成放 tmp/，测后择优沉淀回 assets/probes/——这是空间的复利循环；断言受对账标准约束 |
| **MCP**（辅助；默认 AgentR，四端点） | 不值得写脚本的一次性验证：快速冒烟（队列状态/服务存活）、交互式查询、临时取证（远程日志/配置）、单发触发消息（见"工具依赖"节场景映射） | 仅用 `workspace.yaml.mcp` 登记过的 server；连接用 connectionId；断言同样受对账标准约束 |
| **人工清单** | 页面视觉效果、Grafana 截图、需要人眼确认的渲染表现等自动化覆盖不了的 | 报告单列"人工验证项"，禁止静默跳过 |

### 前端验证优先 playwright（前后端项目）

- 前端（Vue/React 等）页面级验证**优先生成 playwright 脚本**（Python + uv 内联依赖
  `playwright`），断言页面元素、交互流转与接口副作用，遵守探针契约（退出码/stdout
  断言/测后沉淀到 `assets/probes/<前端模块>/`）
- 目标地址与登录方式从台账取（env.json `envs.<环境>.front`：各应用地址、
  `loginUrl`、`loginNote`）；测试账号从 env.secret.json 的
  `envs.<环境>.front.{username,password}` 读，不写死不进报告
- **登录态复用**：首跑完成登录后保存 storage_state 到
  `assets/common/.auth/<环境名>.json`（gitignore），后续探针复用免重复登录；
  失效则重新登录刷新
- 首次运行需 `uv run playwright install chromium`（浏览器二进制装在用户侧，不进空间）
- **所有 UI 自动化必须录屏并放慢操作**（Playwright 或其他工具均适用）；执行前读
  [ui-recording.md](ui-recording.md)，默认 slowMo 500ms、状态出现后停留 1000ms，
  视频存 `runs/<run-id>/videos/`，失败与重试也保留；报告提供视频链接、关键时间点和
  人工核对状态，自动断言通过不代表录像已人工核对。
- MCP 的 websocket_read / http_send 可作为 playwright 断言的辅助取证（如验证推送
  消息体），不替代页面 e2e 本身

## 工具依赖：AgentR MCP（辅助通道的工具源，四端点约 90 个工具）

执行通道**脚本优先**；AgentR MCP 是脚本之外的一次性查询与取证工具源（Nginx 网关
`http://127.0.0.1:8319`，四个语言后端各一个端点，登记见 workspace.yaml `mcp.agentr`）
——需要什么工具直接调用其 MCP 工具，不要让用户另配零散的 MCP server；
脚本需要长期用到的能力，沉淀为探针而不依赖 MCP。

四端点工具明细（DB/Redis/MQ/MQTT/WebSocket/SSH/TDEngine/定时任务）、
「测试场景 → 工具映射」表与使用规则（连接引用、不臆造工具、对账标准不放松、
不可用降级、周期回归）见 [references/agentr-mcp.md](references/agentr-mcp.md)。

## 探针脚本契约（Python 优先）

测试脚本**优先 Python**：探针头部 PEP 723 内联依赖，`uv run <脚本>` 执行，公共库用
`assets/common/lib.py + report.py`；测试脚本**仅允许 Python（uv）与 Node.js**，
Python 不适合时使用 Node.js（lib.js/report.js）；不生成 Shell 或其他语言测试脚本。
Git/环境查询等工具命令可直接执行，不作为测试脚本。两种语言都必须遵守：

1. 退出码：0 = 全部断言通过；非 0 = 存在失败
2. 输出：断言明细到 stdout（JSON 优先，含 name/ok/evidence），日志到 stderr
3. 凭据只从 `assets/common/env.secret.json` 读取（经公共库合并 env.json），不硬编码
4. **测试输入样本与预期值都在执行时从目标环境 DB 现查**（挖掘 SQL 见 05-test-data.md），
   禁止把 ID/SN 写死在脚本里；长整型 ID 一律按字符串处理；不适合 SQL 直取的数据
   （需走业务流程/状态）可改为调用目标环境查询接口或最小造数接口获取，同样禁止写死
5. 依赖装在工作空间侧：Python → 探针头部 PEP 723 内联依赖（`# /// script` 块），
   `uv run <脚本>` 执行；playwright 探针首次运行前 `uv run playwright install
   chromium`（浏览器装在用户侧）；Node → 空间根 `package.json` + `npm install`；
   **永不装进 skill 目录或任何业务 Git 仓库**
6. 前端页面（Vue 等）验证优先 playwright 脚本（Python + uv），断言页面元素与
   交互，同样沉淀到 `assets/probes/<前端模块>/`（见"前端验证优先 playwright"节）
7. 每个探针头部注释写清：用途、运行方式、依赖（多文件探针配 README，见 assets/probes/README.md）；
   **依赖锁定版本范围**（如 `pymysql>=1.1,<2`），防上游 breaking change
8. **目标测试环境的写操作类验证（造数/发测试消息）须自带清理逻辑**，或在 report 的
   "清理清单"节登记待清理项；测试数据带可识别标记（messageId 前缀 / 备注字段），
   避免污染下一轮样本挖掘；清理按**子对象 → 关联关系 → 主对象**顺序执行，
   且仅清理本轮自建的带标记数据，不碰既有业务数据
9. UI 自动化按 ui-recording.md 全程录屏、设置可读操作节奏，finally 完成录制收尾；
   视频在 runs/ 下保留且报告登记人工核对，不能以截图/trace 代替录像
10. HTTP 类探针失败或 SKIP 时，输出**可复现完整 cURL**（method、URL、headers、body）
    随 evidence 落盘，供人工复核、缺陷单附件与跨环境复现；前置数据缺失导致的 SKIP
    必须结构化记录五要素：依赖接口名称、所需提取字段、缺失原因、HTTP 状态、
    该依赖接口完整 cURL——禁止只写“xxx 未取到/未配置”
11. 请求发起前对合并后的 payload/query **递归剔除值为空字符串的字段**（实测坑：
    `"systemCode": ""` 等空串参数触发校验失败或异常语义）；接口探针的请求字段
    以当前 Controller/DTO/VO 实际代码为准，不沿用旧脚本/旧文档字段（接口可能已变更）

