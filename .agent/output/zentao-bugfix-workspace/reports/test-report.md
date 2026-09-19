# zentao-bugfix 钉钉监听器 · 测试报告（降级模式：官方 skill-creator 依赖因网络不可达未安装）

## 范围
为既有 skill `zentao-bugfix` 新增纯 Python 钉钉监听器（scripts/dingtalk_listen.py + references + tests + evals#5/#6），
含 round-2 需求变更：基准分支优先级 .env(BUGFIX_BASE_BRANCH) > 对话提供 > 仓库当前分支。

## 门禁轨迹（gate-state.json 可复核）
- 理解闭环：2 轮（12 项问答 + round-2 需求变更#12），置信 95
- 评审：round-1 通过（9 项问题修复）；round-2 变更后纯净分发副本清单 23/23、0 error 0 warn
- 规范豁免记录：配置存 skill 目录 .agent/.env 为用户显式要求；gitignore(.env/.agent) 保证不入库不分发

## 测试结果
| 类别 | 结果 |
|---|---|
| 单元测试（正常/边界/错误三路径） | 26/26 通过 |
| 机器清单（review_checklist，纯净副本） | 23/23 通过 |
| 冒烟：config-status / status / start 缺配置退出码2 | 通过 |
| 真实提取正向（"帮我修一下BUG…"） | ✅ is_bugfix=true, bug_id 提取正确 |
| 真实提取负向（"今天中午吃什么好呢"） | ✅ is_bugfix=false |
| 真实端到端（王青→赵丽阳 消息"74996"） | ✅ 事件→提取→会话→prepare（worktree bugfix/74996_20260919、禅道API真实拉取bug详情+2截图、analysis.md 骨架）|
| 74996 完整修复会话 | 🔄 运行中（编排链已全部实证；会话结束日志由 listener 记录）|

## 未验证项（如实标注）
- dsh/DeepSeek Harness（本机未安装）：custom 适配器为模板实现
- codex/claude 适配器命令为文档级验证（CLI help 核实），未真实跑修复会话

## 95% 信心论证
评审记录 review-round-1.md：P0/P1 全部闭环；负向用例已验证；错误路径已演练（配置缺失/非JSON输出/子进程退出/超时/默认参数）；主链路经真实环境端到端实证。

## round-3 变更（无黑窗）
- 全部 6 处子进程 spawn 点加 CREATE_NO_WINDOW（Agent 会话/dws 查询/dws 监听/tasklist/taskkill），守护保持 DETACHED；Windows 全链路零黑窗
- 单测 27/27；生产守护已平滑重启验证（stop→start，pid 24028→10844）
