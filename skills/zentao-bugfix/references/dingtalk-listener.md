# 钉钉触发与轮询修复单次入口（dingtalk_listen.py）使用指南

> v2.7 起本脚本不再包含常驻监听循环与系统级定时（原 `start` / `status` / `stop` / `autostart` 子命令已移除）。
> 定时触发与钉钉消息监听由 **AgentR「工作流」** 承担：cron 调度与 dws 监听运行在 AgentR 服务进程内，
> **AgentR 关闭即全部失效**，不依赖操作系统计划任务。本脚本每次运行只处理一次即退出。

## 定位

| 场景 | 触发方式 | 本脚本入口 |
|---|---|---|
| 定时轮询禅道待处理 Bug | AgentR 工作流「定时触发」节点（cron） | `poll-once` |
| 钉钉联系人/机器人消息触发 | AgentR 工作流「钉钉监听」触发节点 | `fix-from-message` |
| 手动 | 工作流手动触发或直接运行 | `retry` / `fix-from-message` / `poll-once` |
| 外部系统回调 | AgentR 工作流「HTTP 触发」节点 | 同手动 |

在智能体对话中配置自动触发时，先提示用户到 AgentR 工作流画布创建对应触发节点；
工作流节点配置见 AgentR 文档（多触发器：manual / schedule / http / dingtalk 可并存）。

## 子命令

| 命令 | 说明 | 退出码 |
|---|---|---|
| `poll-once [--limit N] [--agent T] [--model M]` | 查询禅道活跃 Bug（v1 API，最多 N 条，默认 100），仅 `resolution` 为空的逐个自动修复；输出 JSON 汇总（checked/pending/triggered/skipped/failed） | 0 全部成功；1 有失败；2 配置错误 |
| `fix-from-message <文本\|-> [--agent T] [--model M]` | Agent 无头提取消息中 bugId；命中则修复，非修复消息输出 `{"triggered": false}`；`-` 从 stdin 读 | 0 成功/非修复；1 修复失败；2 配置错误 |
| `config-status` | JSON：缺失必需键、现有配置（密码脱敏）、可选项说明 | — |
| `save-config KEY=VALUE...` | 保存/合并写入 routes.json 的 config，保留 rules，回显仍缺项 | — |
| `test-extract <文本>` | 只跑意图提取，不修复 | — |
| `retry <bugId> [--agent T] [--model M]` | 重新触发路径异常 Bug，或以 --reuse 恢复未完成修复；已完成 Bug 不重复提交 | 0/1 |

脚本全非交互（无 input()，适配无终端环境）；缺配置时报错退出（码 2），由 AI 逐项问用户后 save-config，再重试。

## 执行链路（与 v2.6 监听器一致）

1. prepare 前只读查询禅道当前 `resolution`：只有为空（`""` / `null`）的 Bug 进入自动修复；有值跳过；字段缺失、类型异常或查询失败时停止并通知。人工强制处理用 `bugfix.py prepare --allow-resolved`。不自动修改禅道状态。
2. 先确定性运行 prepare，再向 Agent 传入结果，Agent 不重复 prepare。
3. Agent 正常退出后再次渲染三份 HTML，校验本次 run_id、完整 MD、与当前正文一致的 HTML，以及绑定模式提交；HTML 缺失或过期不算成功。
4. 工作区异常不启动修复会话。等待分支的 Bug 存 `.agents/logs/pending-bugs.json`，用 `retry` 恢复。
5. 结果经 dws 单聊通知当前登录用户本人（跳过/成功/失败/首次等待）；消息含 Bug ID、结果、报告路径、提交信息；不含 Bug 原文或未脱敏错误输出。发送失败写 `.agents/logs/result-notifications.json`，下次运行入口时补发；消息使用稳定幂等键。
6. 启动目录不同于 `TARGET_PROJECT_PATH` 时，routes.json 从目标项目读取，异常 HTML 仍写启动目录。

## 配置（启动工作空间 `.agents/zentao-bugfix/routes.json`）

配置键放在 `config` 对象中，所有值为字符串；`rules` 数组保存分流规则，可为空。配置和日志均锚定启动工作区，不读取旧 `.env` 或 skill 安装目录中的配置。将旧 `.env` 的 KEY=VALUE 转成 config 中的字符串键值，或调用 `save-config KEY=VALUE...` 保存；该命令保留已有 rules。

`config-status` 输出 `config_file` 和脱敏后的 config。禅道配置同步到目标项目同名文件时只合并 ZENTAO_*，不覆盖目标 rules 或其他配置。完整格式见 [routing.md](routing.md)。

| 键 | 必填 | 说明 |
|---|---|---|
| `ZENTAO_BASE_URL` / `ZENTAO_ACCOUNT` / `ZENTAO_PASSWORD` | ✅ | 禅道配置（自动同步到目标仓库，不入 git） |
| `BUGFIX_BASE_BRANCH` | 可选 | worktree 基准分支；**优先级：显式参数 > routes.json config > 仓库当前分支**（只用于默认 worktree 模式）；prepare 新建 worktree 时会自动 fetch 并合并该分支的远端最新代码（无远程/fetch 失败降级本地快照；冲突返回码 5 人工决策） |
| `TARGET_PROJECT_PATH` | 可选 | 目标仓库；**优先级高于启动目录** |
| `AGENT_TYPE` | 可选 | `pi` / `codex` / `claude` / `custom` |
| `AGENT_MODEL` | 可选 | pi 用 `provider/model`；codex/claude 用各自模型名 |
| `AGENT_CUSTOM_CMD` | custom 必填 | 命令模板，占位符 `{model}` `{prompt}` |

钉钉监听目标（人员/机器人）、监听模式与轮询参数由 AgentR 工作流的钉钉监听触发节点配置，不再通过本 skill 的 routes.json。

**Agent 解析优先级**：命令行 `--agent/--model` > `routes.json config` > 自动探测当前 pi 会话 > 交互询问。
**目标仓库优先级**：`routes.json config.TARGET_PROJECT_PATH` > 启动时所在目录（须为 git 仓库）。

## Agent 适配器命令对照

| Agent | 意图提取 | 修复会话（cwd=目标仓库） |
|---|---|---|
| pi | `pi -p --no-session --no-extensions --no-skills --no-prompt-templates --no-tools --model <m> <提示词>` | `pi -p --model <m> --skill <skill目录> <提示词>` |
| codex | `codex exec -s read-only --skip-git-repo-check -m <m> <提示词>` | `codex exec -s danger-full-access --skip-git-repo-check -m <m> <提示词>`（worktree 在仓库同级，需完全访问） |
| claude | `claude -p --no-session-persistence --model <m> <提示词>` | `claude -p --dangerously-skip-permissions --model <m> <提示词>` |
| custom | `AGENT_CUSTOM_CMD` 模板渲染（`{model}`/`{prompt}`） | 同左 |

提取提示词要求 Agent 只输出
`{"is_bugfix": bool, "bug_id": "数字|null", "reason": "..."}`；解析端容忍 markdown
围栏与前后杂文。超时：提取 300s、修复 7200s。

## 日志（启动工作空间 `.agents/logs/`）

- `fix-<bugId>.log`：修复会话输出末尾与 `[VERIFY]` 产物校验结果（含 analysis_complete 分析先行校验；无头会话退出码 0 不代表流程完成，以本次 run_id、完整报告、绑定模式的 commit 为准）。
- `result-notifications.json`：结果通知发件箱（先落盘再查投递状态；查询失败不重复创建发送任务）。
- 工作区异常 HTML 写启动目录 `.agents/` 下。

## 前置条件与已知限制

- 禅道配置可用；`poll-once` 需要禅道 v1 API（`/api.php/v1/bugs`）可用；结果通知需 dws 已安装并登录；pi/codex/claude 已登录对应服务。
- `fix-from-message` 每次只处理一条消息；批量消息由 AgentR 工作流逐条调用。
- `poll-once` 每轮最多检查 `--limit` 条活跃 Bug；更大的积压由工作流 cron 提高频率或多次运行消化。
- dws 登录账号自己发出的消息不进事件流（钉钉官方过滤）；该限制现由 AgentR 工作流监听触发器承担。

## 排障速查

| 现象 | 处理 |
|---|---|
| `poll-once` 退出码 2 | `config-status` 查缺失键；AI 逐项索取后 `save-config` |
| 查询 Bug 列表失败 | 检查禅道 v1 API 可达性与账号权限；JSON 汇总 `failed` 中含错误摘要 |
| 修复未完成 | `fix-<bugId>.log` 查 `[VERIFY]`；`retry <bugId>` 恢复；不要重复 prepare |
| 未收到钉钉通知 | 检查 dws 登录状态；`result-notifications.json` 查看发送失败的条目 |
