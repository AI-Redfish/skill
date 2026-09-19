# zentao-bugfix 钉钉监听器 · 需求澄清记录（理解闭环）

| # | 问题 | 用户回答 | 结论 |
|---|------|---------|------|
| 1 | 触发方式做到哪一步？ | B 全自动 | 提取 bugId → prepare → 同一 Agent 无头会话自动分析修复出报告，全程无人工 |
| 2 | bugId 格式？ | 交给 LLM 提取 | 不用正则，消息全文交 Agent 判定意图+提取（JSON 输出） |
| 3 | 用什么 LLM？ | 本地 pi | 使用本地 pi（无头 -p） |
| 4(补充) | Agent 怎么选？ | 启动时输入；默认当前会话 Agent；.env 优先；需指定模型 | 优先级：CLI 参数 > .env(AGENT_TYPE/AGENT_MODEL) > 自动探测当前 pi 会话 > 交互询问 |
| 5 | 执行器只支持 pi？ | 还要 codex、claude code、dsh | 适配器：pi/codex/claude 内置 + custom 命令模板（dsh=DeepSeek Harness 本机未装，用模板接入） |
| 6 | 目标仓库怎么定？ | .env 优先级更高 | TARGET_PROJECT_PATH(.env) > 启动时所在对话项目目录 |
| 7 | 监听范围？ | 多人+机器人 | DWS_LISTEN_USERS / DWS_LISTEN_BOTS（CSV），每目标一个 dws 子进程 |
| 8 | 修复完通知方式？ | D | 不发钉钉，只写本地日志 |
| 9 | 配置存放？ | skill 目录 .agent/.env，询问用户后保存 | 首次运行缺啥问啥（一次一个） |
| 10 | 脚本格式约束？ | 全部 Python，禁止 cmd/ps1 | 唯一入口 scripts/dingtalk_listen.py（PEP 723，零三方依赖，后台/前台自管理） |
| 11 | dsh 是什么？ | DeepSeek Harness | custom 适配器模板支持，装好后 .env 配 AGENT_CUSTOM_CMD 即用 |

其余工程假设（串行队列、message_id 去重、.agent/logs 日志、start/status/stop 子命令、自发消息不可监听为 dws 官方限制）已随需求复述清单经用户确认（回复"没问题"）。

## 需求变更记录（round-2）
| # | 问题 | 用户回答 | 结论 |
|---|------|---------|------|
| 12 | worktree 基准分支如何确定？ | 用户通过对话提供；.env 有说明则以 .env 为准 | 新增可选配置 BUGFIX_BASE_BRANCH；优先级：.env > 对话提供（AI 启动监听时询问/手动使用时 prepare 前询问）> 仓库当前分支兜底；两条路径（手动/监听）一致适用 |

| 13 | Agent 修复会话弹黑窗？ | 不要任何黑窗口，后台默认执行 | 全部子进程 spawn 点加 CREATE_NO_WINDOW（Windows）；守护本身 DETACHED；两条路径一致 |
