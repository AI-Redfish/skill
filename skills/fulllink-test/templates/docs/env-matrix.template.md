# 环境矩阵（04-env-matrix.md）

> status: draft | reviewed
> 用途：环境信息台账。init 时经对话逐项登记，后续可修改、可按需维护校验；测试时明确 local/existing，local 必需服务的启动就绪检查不可省略。
> 凭据只写变量名/脱敏目标；AgentR 连接在 AgentR 侧管理，本表只记 connectionId/连接名。

## 环境一览

| 环境名 | default | 用途 | 部署版本指纹获取方式 | 登记日期 | 最近校验（按需） |
|---|---|---|---|---|---|
| 147 | ✅ | 联调 | /actuator/git-commit-id | <日期> | 未校验 |

## 运行方式与服务准备台账（逐环境）

| 环境 | 运行方式 local/existing | 本轮确认来源 | 业务入口 | 构建 commit/副本路径 | 登记日期 |
|---|---|---|---|---|---|
| <环境> | <未知填未确认，测试前明确> | <用户指令/确认> | <实际入口> | <local 非 Git 副本；existing 不适用> | <日期> |

| 环境 | 组件/仓库/应用 | start/reuse 与来源 | 依赖 | 构建/启动/外置配置 | 地址/端口 | 就绪检查/超时 | 日志/停止方式 |
|---|---|---|---|---|---|---|---|
| <环境> | <实际需要的后端/Nginx/RabbitMQ等> | <本轮启动/复用已启动实例> | <依赖图> | <实际命令> | <地址> | <协议/健康/路由检查> | <路径与方法> |

本地启动细节见 skill 的 runtime.md；准备结果另写本轮报告。实际地址同步 env.json，
凭据仅 env.secret.json。复用实例不擅自重启，收尾只停止本轮启动的服务。

## 中间件访问矩阵

| 环境 | 中间件 | 地址（脱敏） | 访问方式（AgentR MCP 工具） | connectionId（AgentR） | 直连脚本（备选） | 最近校验（按需） |
|---|---|---|---|---|---|---|
| 147 | MySQL | 192.168.0.147:3306 | `mysql_query` / `mysql_table_ddl`（rust） | <连接名> | lib.open_db() | <日期> 通 |
| 147 | Redis | 192.168.0.147:6379 | `redis_scan_keys` / `redis_get_key`（rust） | <连接名> | — | 未校验 |
| 147 | RabbitMQ | 192.168.0.147:5672 | `rabbitmq_list_queues` / `rabbitmq_publish` / `rabbitmq_consumer_*`（go） | <连接名> | — | <日期> 通 |
| 147 | MQTT | <broker>:1883 | `mqtt_subscribe`+`mqtt_read` / `mqtt_publish`（rust） | <连接名> | — | 未校验 |
| 147 | TDEngine | <host>:6041 | `tdengine_query`（node） | <连接名> | — | 未校验 |
| 147 | 服务器 | 192.168.0.147 | `ssh_exec` / `ssh_files_preview`（node） | <SSH 连接名> | — | <日期> 通 |

<!-- 填写规则：
1. 本表信息来自 init 对话登记与后续修改（换地址/中间件/MCP 时同步更新本表与 workspace.yaml、env.json）
2. init 默认不探测；按需维护校验更新“最近校验”；local 测试前必须逐项核实必需服务就绪
3. 检查脚本仅 Python（uv）/Node.js，优先脚本，AgentR MCP 辅助取证；
   连接用 connectionId（先 *_list_connections 查）；AgentR 没有的能力（协议细节/压测）走探针脚本直连
4. 新增环境先在此登记再在 workspace.yaml.environments 挂索引 -->
