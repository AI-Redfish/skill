# 钉钉消息监听器（dingtalk_listen.py）使用指南

全自动链路：**钉钉消息 → Agent 提取 bugId → bugfix.py prepare → 同一 Agent 无头修复 → 报告**。
本文是 `scripts/dingtalk_listen.py` 的完整参考；速览见 SKILL.md「钉钉消息自动触发」。

## 架构

```
DWS_LISTEN_USERS / DWS_LISTEN_BOTS（.env 名单）
        │ stream: 每目标一个 dws 子进程(+listen-im, stdin 常开, stderr 落盘 dws-<名>.log)
        │ poll:   每目标一个拉取线程(每 20s 拉 dws chat +chat-messages, 水印增量)
        │ auto 模式下两通道并行, message_id 去重(DedupStore)天然防重
        ▼
dingtalk_listen.py 主控（纯标准库 Python）
  ├─ reader/poll 线程 × N：事件归一化 → 去重 → 事件队列(串行)
  ├─ worker：Agent 无头提取意图(JSON) → 命中 → 同步禅道配置到仓库 → Agent 无头修复会话
  └─ 守护管理：start(后台)/status/stop；日志与状态全在 skill 目录 .agents/logs/
```

## 配置（skill 目录 `.agents/.env`）

| 键 | 必填 | 说明 |
|---|---|---|
| `DWS_LISTEN_USERS` | ✅ | 监听人员姓名，逗号分隔（须能在通讯录精确唯一匹配） |
| `DWS_LISTEN_BOTS` | 可选 | 监听机器人名，逗号分隔（`dws chat bot find` 可查） |
| `ZENTAO_BASE_URL` / `ZENTAO_ACCOUNT` / `ZENTAO_PASSWORD` | ✅ | 禅道配置（自动同步到目标仓库，不入 git） |
| `LISTEN_MODE` | 可选 | 监听模式：`auto`（默认，stream 推送 + poll 拉取**双通道并行**，message_id 去重防重，推送故障时拉取自动兑底、恢复后自动回到毫秒级推送）/ `stream`（仅推送）/ `poll`（仅拉取，间隔 `POLL_INTERVAL=20s`） |
| `BUGFIX_BASE_BRANCH` | 可选 | worktree 基准分支；**优先级：.env > 对话询问 > 仓库当前分支**（手动使用与监听自动触发一致） |
| `TARGET_PROJECT_PATH` | 可选 | 目标仓库；**优先级高于启动目录** |
| `AGENT_TYPE` | 可选 | `pi` / `codex` / `claude` / `custom` |
| `AGENT_MODEL` | 可选 | pi 用 `provider/model`（如 `provider-x/model-y`）；codex/claude 用各自模型名 |
| `AGENT_CUSTOM_CMD` | custom 必填 | 命令模板，占位符 `{model}` `{prompt}`，如 `dsh -p --model {model} {prompt}` |

**Agent 解析优先级**：命令行 `--agent/--model` > `.env` > 自动探测当前 pi 会话（读
`~/.pi/agent/sessions/<启动目录映射>/最新.jsonl` 的 provider/modelId）> 交互询问。
**目标仓库优先级**：`.env TARGET_PROJECT_PATH` > 启动时所在目录（须为 git 仓库）。

## 子命令

| 命令 | 说明 |
|---|---|
| `config-status` | JSON：缺失必需键、现有配置（密码脱敏）、可选项说明 |
| `save-config KEY=VALUE...` | 保存/合并写入 .env，回显仍缺项（AI 逐项向用户索取后写入） |
| `start [--foreground] [--agent T] [--model M]` | 启动；默认后台守护（DETACHED，不阻塞当前会话），`--foreground` 前台调试；配置缺失退出码 2 |
| `status` | JSON：pid、目标存活、最近事件时间、队列长度、修复统计 |
| `stop` | 写 stop 标志 → 守护进程优雅退出（dws 子进程经 stdin EOF 自动退订清理）；超时 30s 强杀 |
| `test-extract <文本>` | 不监听，直接跑一遍「Agent 意图提取」，验证 Agent 配置 |

脚本全非交互（无 input()，适配无终端环境）；缺配置时报错退出，由 AI 逐项问用户后
save-config，再重新 start。

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

## 日志（skill 目录 `.agents/logs/`）

| 文件 | 内容 |
|---|---|
| `daemon.out` | 后台守护进程 stdout/stderr |
| `events.log` | 每条监听到的消息事件（原始 JSON） |
| `listener.log` | 运行日志（启动/命中/忽略/错误） |
| `fix-<bugId>.log` | 每次自动修复会话的命令、耗时与输出末尾 40 行 |
| `state.json` | status 数据源（5s 刷新） |
| `processed-ids.json` | message_id 去重（环形，最近 1000 条） |
| `listener.pid` / `stop.flag` | 守护进程管理 |

## Windows 无黑窗说明

全链路子进程（pi/codex/claude/custom、dws 监听与查询、tasklist/taskkill）均带
`CREATE_NO_WINDOW` 标志在后台静默执行；守护进程本身以 `DETACHED_PROCESS` 拉起。
任何阶段都不会弹出控制台黑窗口。

## 前置条件与已知限制

- `dws` 已安装（PATH 或 `DWS_PATH` 环境变量指定路径）且 `dws auth login` 已登录；
  token 过期时监听子进程会异常退出并按 5/15/60/300s 退避重启，连续失败 4 次放弃该目标。
- 所选 Agent CLI（pi/codex/claude/custom）已安装并登录对应模型服务。
- **dws 登录账号自己发出的消息不会进入事件流**（钉钉官方 self-loop 过滤）——测试必须
  用名单内其他账号/机器人发消息。
- codex 修复使用 `danger-full-access` 沙箱（worktree 需写仓库同级目录），介意者请用
  pi/claude。
- 监听会话与钉钉推送依赖本机在线；电脑休眠即停止，唤醒后守护仍在但 dws 子进程按退避自愈。

## 排障速查

| 现象 | 处理 |
|---|---|
| `status` 显示 running=false | 看 `daemon.out`；多为配置缺失（交互补齐）或 dws 未登录 |
| 消息收到了但没触发修复 | 看 `events.log`（有无事件）→ `listener.log`（提取结果/失败原因）→ `test-extract` 复现 |
| 提取总失败 | Agent CLI 未登录或模型名错误；`test-extract` 验证 |
| 目标解析失败（重名/不存在） | `dws contact user search --query 名字` / `dws chat bot find --query 名字` 人工核对唯一性，改用精确姓名 |
| 想立即停掉一切 | `stop` 后确认 `status` running=false；残留 dws 进程可 `taskkill /IM dws.exe /F`（Windows） |
