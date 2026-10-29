# fulllink-test — AgentR MCP 工具依赖（按需加载）

执行通道**脚本优先**；AgentR MCP 是脚本之外的一次性查询与取证工具源。本文件是
SKILL.md「工具依赖」的完整版：四端点工具明细、测试场景 → 工具映射与使用规则。

## 工具依赖：AgentR MCP（辅助通道的工具源，四端点约 90 个工具）

执行通道**脚本优先**；AgentR MCP 是脚本之外的一次性查询与取证工具源（Nginx 网关
`http://127.0.0.1:8319`，四个语言后端各一个端点，登记见 workspace.yaml `mcp.agentr`）
——需要什么工具直接调用其 MCP 工具，不要让用户另配零散的 MCP server；
脚本需要长期用到的能力，沉淀为探针而不依赖 MCP：

| 端点 | 工具组 |
|---|---|
| `/api/rust/mcp` | **MySQL / Kingbase / SQLite**（`*_query`、`*_tables`、`*_table_ddl`、`*_databases`）；**Redis**（`scan_keys`、`get_key`、`overview`）；**MQTT**（`subscribe`+`read`、`publish`）；**WebSocket**（`connect`+`read`）；`http_send` |
| `/api/go/mcp` | **RabbitMQ**（`list_queues`、`list_exchanges`、`list_consumers`、`publish`、`consumer_start`+`consumer_messages`）；**RocketMQ**（`send_message`、`subscription_start`+`subscription_messages`） |
| `/api/node/mcp` | **SSH**（`ssh_exec` 万能命令行、`ssh_files_preview` 远程日志取证）；**TDEngine**（`tdengine_query` 等）；`nginx_gateway_status`、`image_to_base64` |
| `/api/python/mcp` | **schedule**（`schedule_run_task` 触发定时型链路、`schedule_list_tasks`、`schedule_list_records`） |

### 测试场景 → 工具映射（优先按此选工具）

| 测试场景 | AgentR MCP 工具 |
|---|---|
| DB 查询对账（改前查改后查，样本现查） | `mysql_query` / `kingbase_query` / `sqlite_query`；表结构 `*_table_ddl` |
| 时序库对账 | `tdengine_query` |
| 缓存断言（键存在/值/扫描） | `redis_scan_keys` / `redis_get_key` / `redis_overview` |
| MQ 队列状态/发消息/消费监听 | `rabbitmq_list_queues` / `rabbitmq_publish` / `rabbitmq_consumer_start`+`consumer_messages`；RocketMQ 同理 |
| MQTT 订阅收推/发布 | `mqtt_subscribe` + `mqtt_read` / `mqtt_publish` |
| WebSocket 推送验证 | `websocket_connect` + `websocket_read` |
| HTTP 接口调用 | `http_send` |
| 定时型链路触发 | `schedule_run_task` |
| 远程命令行/日志取证/服务存活 | `ssh_exec` / `ssh_files_preview`（systemctl/端口/进程检查） |

使用规则：

1. **连接引用**：各工具用已保存连接的 `connectionId`，先 `*_list_connections` 查可用
   连接；连接由 AgentR 侧管理，报告与对话只引连接名，不明文引凭据
2. 调用前先 `tools/list` 确认工具存在与入参，**不臆造 AgentR 没有的工具**；
   需要的能力 AgentR 确实没有（如 prefetch 精细控制、压测、多步事务对账、
   页面 e2e）→ 生成探针脚本（Python/uv / playwright，凭据 env.secret.json）
3. **MCP 一次性查询同样受对账标准约束**：断言到字段/行数，不得因"用 MCP 查的"
   就放松 L0 规则；同一验证预计要复跑 → 写成脚本沉淀，不反复手工调 MCP
4. AgentR MCP 不可用（网关没起/工具缺失）→ 该项降级探针脚本或人工清单，
   报告标注；先调 `nginx_gateway_status` 自检，不因此中断流程
5. **周期回归（进阶）**：稳定沉淀的探针可注册为 AgentR 定时任务
   （`schedule_run_task` 周期执行 `uv run <探针>`），实现夜间自动回归；结果经
   `schedule_list_records` 查看，异常再人工介入——把空间从"人触发"升级为
   "持续回归"

