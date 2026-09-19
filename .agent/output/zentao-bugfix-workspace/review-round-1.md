# zentao-bugfix 钉钉监听器 · 评审记录 round-1（设计评审 + 实现评审）

## 一、设计评审（触发/边界/渐进式披露）
- 触发面：SKILL.md frontmatter description 补充监听入口描述，正文新增「钉钉消息自动触发」章节（165 行，远低于 500 上限），细节全部外置 references/dingtalk-listener.md ✓
- 不适用边界：保留原有 4 条负向场景，新增 evals #5/#6 覆盖监听启动/停止 ✓
- 配置模式与 bugfix.py 完全一致（config-status/save-config/退出码2），AI 双闭环索配置路径可复用 ✓
- 与用户需求逐条对照（clarify-qa.md 11 项）：全部落实 ✓

## 二、实现评审（正确性/容错/安全）——审查-修正-再审查全程记录
本轮评审共发现并修复 9 个问题（按发现顺序）：
1. 【真bug】load_env 默认参数在定义期绑定 ENV_FILE 常量，运行期 monkeypatch 失效 → 改函数体内动态解析（单测捕获）
2. 【真bug】pi 会话目录名映射公式不可靠（前导双横线规律存疑）→ 弃用公式，改读会话文件首行 cwd 字段精确匹配
3. 【真bug】WSL 启动时 cwd=/mnt/... 与 pi 会话记录的 D:\... 永不匹配 → 增加 _wsl_to_win_path 桥接
4. 【风险】后台守护进程可能卡死在 input()（无终端）→ 脚本全非交互化，缺配置退出码2，由 AI 索取后 save-config（同时消掉机器清单 input 告警）
5. 【真bug】npm 垫片 pi/codex 在 Windows 无 .exe，subprocess 调不到 → resolve_exe 解析 .cmd/.exe/.bat
6. 【真bug·实测复现】.cmd 垫片破坏含引号/换行的长 argv，模型收到的消息内容被截断 → 提示词改 @file（pi，官方文档支持）与 stdin（codex/claude）；真实 pi 调用验证修复生效
7. 【实测复现】模型自造字段名 is_bug_fix_request → 提示词加严格字段契约+示例，解析端容忍别名（真实调用双向验证：正/负用例均正确）
8. 【健壮性】test-extract 的 stdin 跨编码边界（WSL UTF-8 → Win GBK 控制台）→ stdin.buffer 多编码探测
9. 【规范】测试运行产物 .agent/logs 污染 skill 目录（机器清单 error）→ 清理；运行时状态目录属用户显式要求（见豁免记录）

## 三、安全评审
- 禅道密钥仅存 .agent/.env（gitignore 已覆盖 .env/.agent 双规则）；config-status 输出脱敏 ✓
- 目标仓库同步 .env 时自动防入库（检查+追加 .gitignore）✓
- codex 修复需 danger-full-access（worktree 在仓库同级，沙箱必然越界）：SKILL.md/references 已明示风险与替代建议 ✓
- custom 模板提示词中引号中和，防命令注入 ✓

## 四、验证证据
- 单元测试 23/23（含 3 路径：正常/边界/错误）
- 机器清单 review_checklist 23/23（0 error 0 warn）
- 真实端到端（Windows anaconda python + pi zai-coding-cn/glm-5.3）：
  正向「帮我修一下BUG 74882，紧急」→ {"is_bugfix":true,"bug_id":"74882"} ✓
  负向「今天中午吃什么好呢」→ {"is_bugfix":false} ✓
  冒烟：config-status/status/start缺配置退出码2 ✓（本会话早前已验证 dws 监听链路真实可用）

## 五、规范豁免记录（用户显式要求优先）
- authoring-standards 默认 .env 于 <workdir>/.agent；用户明确要求配置存 skill 目录 .agent/.env（clarify-qa #9）。
  风险控制：skill/.gitignore 已忽略 .agent/ 与 .env（不随 git 分发）；分发包内不含运行时状态。
- 未验证项：完整自动修复会话（需真实禅道凭据+目标仓库，待用户 save-config 后由真实 bug 消息触发首次验证）；
  dsh/DeepSeek Harness 本机未安装，custom 适配器为模板实现，未实测。

## 六、置信度自评
P0/P1 问题：无遗留（9 项全部修复并复测）。负向用例已验证（闲聊拒绝）。错误路径已演练
（配置缺失/输出非JSON/子进程退出码非0/超时）。对照 review-guide 判据 → 95%。
