# 环境矩阵（04-env-matrix.md）

> status: draft | reviewed
> 用途：环境信息台账。init 时经对话逐项登记，后续可修改、可按需校验连通性（无强制校验门禁）。
> 凭据只写变量名/脱敏目标，值在 env.secret.json。

## 环境一览

| 环境名 | default | 用途 | 部署版本指纹获取方式 | 登记日期 | 最近校验（按需） |
|---|---|---|---|---|---|
| 147 | ✅ | 联调 | /actuator/git-commit-id | <日期> | 未校验 |

## 中间件访问矩阵

| 环境 | 中间件 | 地址（脱敏） | 访问方式 | MCP server（workspace.yaml 登记） | 直连脚本 | 最近校验（按需） |
|---|---|---|---|---|---|---|
| 147 | MySQL | 192.168.0.147:3306 | MCP + 脚本 | mysql | lib.openDb() | <日期> 通 |
| 147 | RabbitMQ | 192.168.0.147:5672（管理口 15672） | MCP + 脚本 | rabbitmq | lib.connectAmqp() | <日期> 通 |
| 147 | MQTT | <broker>:1883 | 脚本 | （未登记） | lib.connectMqtt() | 未校验 |

<!-- 填写规则：
1. 本表信息来自 init 对话登记与后续修改（换地址/中间件/MCP 时同步更新本表与 workspace.yaml、env.json）
2. 默认不做连通性校验；用户要求"校验环境"或探针连接异常时才逐项实测，更新"最近校验"列
3. 未登记 MCP 的中间件只能走脚本通道，报告需标注
4. 新增环境先在此登记再在 workspace.yaml.environments 挂索引 -->
