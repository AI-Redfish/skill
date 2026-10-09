# 钉钉消息监听器（dingtalk_listen.py）使用指南

全自动链路：**钉钉消息 → Agent 提取 bugId → 监听器确定性执行 prepare（查询禅道并分流）→ Agent 补全分析/方案 → 绑定模式 ready → 修复 → report/补全 → 绑定模式 finish 验证并单 Bug 提交**。未匹配或规则冲突时仍创建独立 worktree，默认不提交。
本文是 `scripts/dingtalk_listen.py` 的完整参考；速览见 SKILL.md「钉钉消息自动触发」。

## 架构

```
DWS_LISTEN_USERS / DWS_LISTEN_BOTS（routes.json config 名单）
        │ stream: 每目标一个 dws 子进程(+listen-im, stdin 常开, stderr 落盘 dws-<名>.log)
        │ poll:   每目标一个拉取线程(每 POLL_INTERVAL_SECONDS 秒(默认20)重扫
        │         「过去 POLL_LOOKBACK_MINUTES 分钟(默认10)」窗口, dws +chat-messages
        │         --start 服务端过滤, message_id 去重(DedupStore)防重)
        │ auto 模式下两通道并行, 推送丢的消息由轮询窗口自愈补拉
        ▼
dingtalk_listen.py 主控（纯标准库 Python）
  ├─ reader/poll 线程 × N：事件归一化 → 去重 → 事件队列(串行)
  ├─ worker：Agent 提取意图 → 同步配置 → prepare 查询禅道/匹配 routes.json
  │    → 绑定已有工作区或新 worktree → Agent 分析/修复/报告 → 绑定分支 finish 提交
  │    → 验证本次 run_id、完整报告、绑定模式 commit；占用任务持久排队
  └─ 守护管理：start(后台)/status/stop；日志与状态全在启动工作空间 .agents/logs/
```

## 修复位置、顺序提交与异常报告

目标项目的 `.agents/zentao-bugfix/routes.json` 只支持 `bug_id` 精确匹配与 `title_contains` 普通子串匹配（英文忽略大小写），ID 优先。示例及完整约定见 [routing.md](routing.md)。无文件、无命中或同优先级规则冲突时默认创建独立 worktree。

唯一匹配后使用配置的已有工作区和分支，不自动切分支或同步远端。同一仓库/分支及同一工作区使用跨进程持久锁；前一个 Bug 验证并通过 finish 独立提交后才释放锁并处理下一个。禁止夹带已有开发改动，不自动 push。失败锁保留，后续等待任务存 `.agents/logs/pending-bugs.json`，监听重启后继续等待；其他可用工作区仍可处理。

指定目录不存在、不是 Git 根目录或当前分支不符时不开始修复、不回退 worktree。生成 `<启动工作区>/.agents/zentao-bugfix/<bugId>/errors/<运行标识>/report.html` 并自动打开默认浏览器；WSL 优先 Windows 浏览器。浏览器打开失败仍保留报告，status.last_fix 显示 html_report/browser_error。修复路径后执行 `retry <bugId>` 或发送新的 Bug 通知，不受旧消息去重影响。

`TARGET_PROJECT_PATH` 不同于启动目录时，规则从目标项目读取；异常报告仍写启动目录。运行记录存目标项目 `.agents/zentao-bugfix/runs/<bugId>.json`。

## 拉取兜底（poll）工作原理

每 POLL_INTERVAL_SECONDS 秒（默认 20）对每个监听目标执行一轮：

1. 计算窗口下界 = `min(持久化水位, now - POLL_LOOKBACK_MINUTES)`，再被
   `now - POLL_MAX_CATCHUP_MINUTES` 托底（水位正常时窗口就是过去 X 分钟；
   停机后前探到水位补漏；首次部署/长期停机最多回看 60 分钟防远古重放）；
2. `dws chat +chat-messages --open-dingtalk-id <目标> --start <下界> --order asc`
   服务端时间窗过滤（旧版 dws 不支持 `--start` 时自动降级为 limit 拉取）；
3. 窗口内消息经「目标发送者过滤 → message_id 去重（DedupStore）」后进同一处理队列。

关键设计是**窗口重扫而非水位增量**：窗口内消息每轮都会被重新捞到，水位损坏、
进程重启、单轮拉取失败都不会永久漏消息（最多延迟一个轮询间隔）；重复处理由
message_id 去重拦截。水位（`poll-state.json`，多目标读-改-写合并）只用于停机后
把窗口向前延伸。推送流（stream）稳定运行 10 分钟后重置重启退避计数，避免长稳
后偶发抖动累计到放弃。

## 配置（启动工作空间 `.agents/zentao-bugfix/routes.json`）

配置键放在 `config` 对象中，所有值为字符串；`rules` 数组保存分流规则，可为空。配置和日志均锚定启动工作区，不读取旧 `.env` 或 skill 安装目录中的配置。将旧 `.env` 的 KEY=VALUE 转成 config 中的字符串键值，或调用 `save-config KEY=VALUE...` 保存；该命令保留已有 rules。

`config-status` 输出 `config_file` 和脱敏后的 config。禅道配置同步到目标项目同名文件时只合并 ZENTAO_*，不覆盖目标 rules 或其他配置。`start/status/stop` 需在同一工作区执行。完整格式见 [routing.md](routing.md)。

| 键 | 必填 | 说明 |
|---|---|---|
| `DWS_LISTEN_USERS` | 人员/机器人**至少填一项** | 监听人员姓名，逗号分隔（须能在通讯录精确唯一匹配）；只监听机器人时可留空 |
| `DWS_LISTEN_BOTS` | 可选 | 监听机器人名，逗号分隔（`dws chat bot find` 可查） |
| `ZENTAO_BASE_URL` / `ZENTAO_ACCOUNT` / `ZENTAO_PASSWORD` | ✅ | 禅道配置（自动同步到目标仓库，不入 git） |
| `LISTEN_MODE` | 可选 | 监听模式：`auto`（默认，stream 推送 + poll 拉取**双通道并行**，message_id 去重防重，推送故障时拉取自动兜底）/ `stream`（仅推送）/ `poll`（仅拉取） |
| `POLL_INTERVAL_SECONDS` | 可选 | 拉取兜底轮询间隔秒数（默认 20） |
| `POLL_LOOKBACK_MINUTES` | 可选 | 兜底每轮重扫的「过去 X 分钟」窗口（默认 10；调大更抗丢消息，代价是每轮拉取量略增） |
| `POLL_MAX_CATCHUP_MINUTES` | 可选 | 停机/水位过旧时兜底最多回看的分钟数（默认 60，防远古消息重放） |
| `LISTEN_AUTOSTART` | 可选 | 系统级开机自启 on/off（默认 on：首次 `start` 成功后自动创建；off 关闭自动创建。彻底卸载用 `autostart remove`） |
| `BUGFIX_BASE_BRANCH` | 可选 | worktree 基准分支；**优先级：显式参数 > routes.json config > 仓库当前分支**（只用于默认 worktree 模式）；prepare 新建 worktree 时会自动 fetch 并合并该分支的远端最新代码（无远程/fetch 失败降级本地快照；冲突返回码 5 人工决策） |
| `TARGET_PROJECT_PATH` | 可选 | 目标仓库；**优先级高于启动目录** |
| `AGENT_TYPE` | 可选 | `pi` / `codex` / `claude` / `custom` |
| `AGENT_MODEL` | 可选 | pi 用 `provider/model`（如 `provider-x/model-y`）；codex/claude 用各自模型名 |
| `AGENT_CUSTOM_CMD` | custom 必填 | 命令模板，占位符 `{model}` `{prompt}`，如 `dsh -p --model {model} {prompt}` |

**Agent 解析优先级**：命令行 `--agent/--model` > `routes.json config` > 自动探测当前 pi 会话（读
`~/.pi/agent/sessions/<启动目录映射>/最新.jsonl` 的 provider/modelId）> 交互询问。
**目标仓库优先级**：`routes.json config.TARGET_PROJECT_PATH` > 启动时所在目录（须为 git 仓库）。

## 子命令

| 命令 | 说明 |
|---|---|
| `config-status` | JSON：缺失必需键、现有配置（密码脱敏）、可选项说明 |
| `save-config KEY=VALUE...` | 保存/合并写入 routes.json 的 config，保留 rules，回显仍缺项（AI 逐项向用户索取后写入） |
| `start [--foreground] [--agent T] [--model M]` | 启动；默认后台守护（DETACHED，不阻塞当前会话），`--foreground` 前台调试；配置缺失退出码 2 |
| `status` | JSON：pid、目标存活、最近事件时间、队列长度、修复统计、`last_fix`（最近一次修复结果含失败原因） |
| `stop` | 写 stop 标志 → 守护进程优雅退出（dws 子进程经 stdin EOF 自动退订清理）；超时 30s 强杀。**只停当前进程，开机自启保留** |
| `autostart [install\|remove\|status]` | 管理系统级开机自启（默认 `status` 查询；`install` 创建/覆盖，`remove` 移除。首次 `start` 成功后会自动 install） |
| `test-extract <文本>` | 不监听，直接跑一遍「Agent 意图提取」，验证 Agent 配置 |
| `retry <bugId> [--agent T] [--model M]` | 重新触发路径异常 Bug，或以 --reuse 恢复未完成修复；已完成 Bug 不重复提交 |

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

## 日志（启动工作空间 `.agents/logs/`）

| 文件 | 内容 |
|---|---|
| `daemon.out` | 后台守护进程 stdout/stderr |
| `start.log` | **启动全过程追踪**：配置检查→Agent 解析→仓库/目标解析→守护拉起/前台主循环；任何一步失败（含配置缺失、dws 未登录、目标解析失败）都会在此留下原因 |
| `events.log` | 每条监听到的消息事件（原始 JSON） |
| `listener.log` | 运行主日志（启动/命中/忽略/提取失败/拉取失败/错误，全量带时间戳落盘；即使 stdout 不可见也不丢） |
| `fix-<bugId>.log` | prepare 分流输出、会话耗时和输出末尾 40 行，以及 **[VERIFY]** 本次运行记录/完整报告/绑定模式提交校验 |
| `pending-bugs.json` | 等待分支或工作区释放的 Bug ID；监听重启后继续等待 |
| `state.json` | status 数据源（5s 刷新，含 stats.last_fix） |
| `processed-ids.json` | message_id 去重（环形，最近 1000 条） |
| `poll-state.json` | 拉取兜底各目标水位（停机后窗口前探用） |
| `listener.pid` / `stop.flag` | 守护进程管理 |
| `autostart-listener.bat` / `autostart.out` | 仅 Windows schtasks 兜底路径会生成：启动脚本与其输出 |

## 系统级开机自启（跨平台，首次 start 自动创建）

**行为**：首次 `start` 成功后自动创建系统级自启任务，之后每次开机/登录自动拉起监听
（入口固定为 `<解释器> <脚本> start --foreground`，工作目录=启动时的工作空间）；
重复 `start` 幂等覆盖为最新工作空间。`--no-autostart` 可单次跳过，`routes.json config` 配
`LISTEN_AUTOSTART=off` 可永久关闭自动创建；`stop` 只停当前进程不卸载自启，
`autostart remove` 才彻底移除（remove 不影响正在运行的监听）。

| 平台 | 机制 | 落点 | 说明 |
|---|---|---|---|
| Windows | 任务计划程序（登录触发） | 任务名 `zentao-bugfix-listener` | 优先 `Register-ScheduledTask`（当前用户、无 72h 执行时限、电池供电不中断、pythonw 无黑窗）；PowerShell 不可用时回退 `schtasks /SC ONLOGON` + 启动 bat |
| macOS | LaunchAgent | `~/Library/LaunchAgents/com.ai-redfish.zentao-bugfix-listener.plist` | `RunAtLoad=true`、`KeepAlive=false`（stop 后不被拉起）；bootstrap 失败自动回退 `launchctl load -w` |
| Linux | systemd 用户服务 | `~/.config/systemd/user/zentao-bugfix-listener.service` | `enable`（+尽力 `loginctl enable-linger` 免登录自启）；无 systemd（部分 WSL/容器）自动回退 **cron `@reboot`**（托管块成对标记包裹，remove 只删自己的块） |

- 解释器选择：Windows 优先 `pythonw.exe`；uv/venv 环境回退基础解释器（脚本零第三方依赖，避免缓存 venv 被清理后自启失效）。
- Linux 可用环境变量 `AUTOSTART_MECHANISM=cron` 强制走 cron（默认自动探测 systemd 可用性）。
- 开机时若配置缺失（`routes.json` 不在/config 缺键），自启拉起的监听会以退出码 2 结束并留日志
 `start.log`，补齐配置后下次登录/重启即恢复正常。
- 手动验证：`autostart status` 看 `installed/mechanism/entry/config_ok`；
 `listener.status` 的 JSON 也带 `autostart` 字段。

## Windows 无黑窗说明

全链路子进程（pi/codex/claude/custom、dws 监听与查询、tasklist/taskkill）均带
`CREATE_NO_WINDOW` 标志在后台静默执行；守护进程本身以 `DETACHED_PROCESS` 拉起。
任何阶段都不会弹出控制台黑窗口。

## 前置条件与已知限制

- `dws` 已安装（PATH 或 `DWS_PATH` 环境变量指定路径）且 `dws auth login` 已登录；
  token 过期时监听子进程会异常退出并按 5/15/60/300s 退避重启，连续失败 4 次放弃该目标
  （稳定运行 10 分钟后计数重置；auto/poll 模式下拉取通道仍持续兜底）。拉取通道对
  旧版 dws 不支持 `--start` 时自动降级为 limit 拉取 + 客户端窗口过滤。
- 所选 Agent CLI（pi/codex/claude/custom）已安装并登录对应模型服务。
- **dws 登录账号自己发出的消息不会进入事件流**（钉钉官方 self-loop 过滤）——测试必须
  用名单内其他账号/机器人发消息。
- codex 修复使用 `danger-full-access` 沙箱（worktree 需写仓库同级目录），介意者请用
  pi/claude。
- 监听会话与钉钉推送依赖本机在线；电脑休眠即停止，唤醒后守护仍在但 dws 子进程按退避自愈。

## 排障速查

| 现象 | 处理 |
|---|---|
| `status` 显示 running=false | 看 `start.log`（启动卡在哪一步、失败原因）与 `daemon.out`；多为配置缺失（交互补齐）或 dws 未登录 |
| 消息收到了但没触发修复 | 看 `events.log`（有无事件）→ `listener.log`（提取结果/失败原因，轮询命中会有「拉取兜底命中消息」行）→ `test-extract` 复现 |
| 推送流总丢消息/停机后漏消息 | 确认 `LISTEN_MODE=auto`（默认）；兜底每 20s 重扫过去 10 分钟，可调大 `POLL_LOOKBACK_MINUTES`；停机漏收最多回看 `POLL_MAX_CATCHUP_MINUTES`（默认 60 分钟） |
| 触发后没有新 worktree | 先看 mode：inplace 复用已有工作区属正常。workspace_error 查看 HTML；waiting 表示前一 Bug 未完成。其他失败看 fix 日志中 PREPARE/VERIFY；退出码 0 不能代替完整报告和提交校验，修正原因后 retry |
| 提取总失败 | Agent CLI 未登录或模型名错误；`test-extract` 验证 |
| 目标解析失败（重名/不存在） | `dws contact user search --query 名字` / `dws chat bot find --query 名字` 人工核对唯一性，改用精确姓名 |
| 想立即停掉一切 | `stop` 后确认 `status` running=false；残留 dws 进程可 `taskkill /IM dws.exe /F`（Windows） |
| 不想重启后监听自动运行 | `autostart remove` 移除系统级自启（`stop` 只停当前进程）；或 `routes.json config` 配 `"LISTEN_AUTOSTART": "off"` 后重新 start（不再自动创建）；Windows 也可在任务计划程序里禁用 `zentao-bugfix-listener` |
| 自启创建了但重启后没拉起 | `autostart status` 确认 installed 与 entry 路径；查工作空间 `.agents/logs/start.log`（开机拉起失败的原因，如配置缺失/dws 未登录） |
