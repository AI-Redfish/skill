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

## 需求变更记录（round-3：worktree 同步远端最新代码）
| # | 问题 | 用户回答 | 结论 |
|---|------|---------|------|
| 14 | 合并来源？ | A | 远程最新：git fetch <remote> <基准分支> 后将 <remote>/<基准分支> 合并进 bugfix 分支 |
| 15 | 合并冲突处理？ | A | 安全中止：git merge --abort 保持 worktree 干净，报错停止（新返回码），人工决策后续 |
| 16 | --reuse 复用时是否同步？ | B | 仅新建 worktree 时同步；--reuse 复用不动代码 |
| 17 | fetch 失败（网络/无远程）？ | B | 警告降级：基于本地快照继续，输出标注「未同步远端」 |

关键假设（已获用户「确认无误」）：
1. 仓库无远程或远程无该基准分支，均按 fetch 失败降级处理（警告+本地快照）
2. 只在新 worktree 分支上合并远端基准，不更新本地基准分支引用、不碰主工作空间
3. 冲突时 git merge --abort 后保留 worktree（干净状态），新增返回码 5，报错说明人工选项
4. prepare/worktree 输出新增同步状态字段（SYNCED/SYNC_REASON 等）；analysis.md 骨架与 meta.json 记录同步结果；fix-report 注明基线同步状态
5. 新建即同步为默认行为，无 --no-sync 开关（失败自动降级）
6. SKILL.md/evals/单测同步更新；--reuse 路径完全不变

## 需求变更记录（round-4：.env 路径修复）
| # | 问题 | 用户回答 | 结论 |
|---|------|---------|------|
| 18 | .env 生成位置错误（嵌套到 skill 目录） | 用户报告：应生成到 当前工作空间/.agents/.env | 修复所有 skill：.env 与运行时产物锚定工作空间，不写 skill 目录 |

关键假设（已在回复中列明，用户需求明确未再追问）：
1. 监听器日志/状态文件（LOG_DIR 同源问题）一并迁到 <启动工作空间>/.agents/logs/
2. 旧版 skill 目录 .env 保留只读兜底，首次 save-config 自动整体迁移（旧文件保留）
3. start/status/stop 需在同一工作空间目录执行（pid/state 锚定启动目录）
4. 其余 5 个 skill（photos2mp4/prd-review/prd-techdoc/skill-creator-plus/wedding-invitation）核查无此问题，不动
