# dws 发送命令参考

dws（DingTalk Workspace CLI）在 Windows 上应已加入 PATH；未找到时直接用完整路径调用 `%USERPROFILE%\.local\bin\dws.exe`。版本用 `dws version` 查看。

参考实现（outbox + 幂等键 + 投递状态核验）：`AI-Redfish/skill/skills/zentao-bugfix/scripts/dingtalk_listen.py` 的 `ResultNotifier`。

## 命令速查

| 目的 | 命令 |
|---|---|
| 登录状态 | `dws auth status --format json` |
| 扫码登录 | `dws auth login` |
| 姓名查完整资料（只读） | `dws contact +lookup --name <姓名>` |
| 关键词搜索通讯录（只读） | `dws contact +search-user --query <关键词>` |
| 单人单聊 | `dws chat +dm --to <姓名> --content "<内容>" --yes --format json` |
| 多人逐一群发同一消息 | `dws chat +broadcast --to "A,B,C" --content "<内容>" --yes --format json` |

`+dm`/`+broadcast` 内部先按姓名搜通讯录解析唯一 openDingTalkId 再发送；`--content` 支持 Markdown。

## 输出核验

- 所有命令默认输出 JSON（`--format json` 为默认值）。判定成功看字段，不看是否有报错文本。
- `+dm` 成功：响应 `success` 为 true，`sendReceipt.openTaskId` 为接受回执。
- CLI 已接受（有 openTaskId）不等于对方已读；需投递状态时：
  `dws chat +messages-query-send-status --open-task-id <openTaskId> --format json`，`sendStatus` 为 `SUCCESS` 才算送达。
- `+broadcast`：返回逐人结果；零命中/多候选的人被跳过并在结尾报出，其余人正常收到。
- `contact +lookup` 多候选时返回候选列表（含部门/职位），用它向用户确认后再发。

## 全局参数

| 参数 | 作用 |
|---|---|
| `--yes` | 跳过交互确认（AI Agent 模式）。仅在用户已明确要求发送时使用 |
| `--format json` | 输出 JSON（默认即 json） |
| `--dry-run` | 预览操作内容，不实际执行 |
| `--ai-tag` | 消息带 AI 发送角标（默认 true） |
| `--profile <corpId:userId>` | 多组织/多账号时指定发送身份；推荐 `corpId:userId` |
| `--timeout <秒>` | HTTP 请求超时（默认 30） |
| `--fields` / `--jq` | 投影或过滤输出字段 |

## 故障排查

| 现象 | 处理 |
|---|---|
| 未找到 dws 命令 | 用完整路径调用 `%USERPROFILE%\.local\bin\dws.exe`，或将其加入 PATH |
| `authenticated` 非 true | 指引用户 `dws auth login` 扫码；多组织用 `dws auth status --profile <corpId>` 核对 |
| 姓名零命中 | 确认姓名/花名写法，用 `contact +search-user` 或 `contact +lookup` 换关键词重试 |
| 姓名多候选 | 列出候选（部门/职位）请用户选择；不猜选 |
| 发送失败 | 报告原因，不自动重试（防重复发送）；参数存疑时先 `--dry-run` 预览 |
| 多组织发错对象 | 加 `--profile` 明确组织与账号；先 `dws auth status` 确认当前 profile |

## 相关命令（非本 skill 目标，备用）

- 群聊发送：`dws chat +send-to-group --group <群名> --content "<内容>" --yes`
- 统一发送：`dws chat +messages-send --as user --user <userId> --text <内容> --idempotency-key <key> --yes`
- 消息监听：`dws event`（DingTalk Stream 长连接），由 AgentR「工作流」承担
