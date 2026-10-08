# 理解闭环澄清记录 — git-flow

## 来源
用户在当前对话中直接下达任务，信息完整，未追加提问。

## 问答记录

### Q1：skill 要沉淀什么操作？
- 用户原话：「将如上创建worktree的操作沉淀成一个skill:git-flow」
- 结论：沉淀"基于远程分支创建 worktree"的完整流程。

### Q2：核心流程参数是什么？（来自用户任务示范）
- 基分支：origin/dev/v6.0.8.1（远程已有分支）
- 新分支名：v6.0.8.1/feature/zly-sharelease-20261008
- worktree 位置：与当前工作空间**同级**（../）
- worktree 目录名 = 分支名，其中 "/" 替换为 "_"
- 结论：基分支与新分支名是**交互参数**；位置与命名规则是**内嵌规则**。

### Q3：输出位置与创建工具？
- 用户指定：输出到 D:\develop\GitNote\AI-Redfish\skill\skills
- 使用 skill-creator-plus 创建（走其门禁流程）
- 结论：target = /mnt/d/develop/GitNote/AI-Redfish/skill/skills/git-flow

## 十要素核对
| 要素 | 结论 |
|---|---|
| 真实目标 | worktree 创建流程可复用化，AI 下次直接按 skill 执行 |
| 背景 | 团队多用 worktree 并行开发（仓库已有 3 个 worktree） |
| 使用场景 | 用户说"帮我新建一个 worktree / 基于 xx 分支拉个 worktree" |
| 输出对象 | AI coding agent（pi 等） |
| 关键约束 | 同级目录、"/"→"_"命名、skill-creator-plus 规范 |
| 优先级 | 正确性 > 容错 > 速度 |
| 成功标准 | 参数化复现本次操作；大仓库慢检出不中断；网络受限可降级 |
| 禁止事项 | 不删除已有 worktree/分支；不做 force 操作 |
| 已有信息 | 完整示范一次（含两个实战坑：fetch 超时、检出超时） |
| 可接受偏差 | 命名规则可用参数覆盖 |

## 关键假设（用户未纠正即视为确认）
1. 范围 = worktree **创建**；删除/清理不在范围（写进"不适用场景"）
2. 实战坑沉淀：检出慢需大超时、fetch 网络受限降级本地引用、WSL/Windows 路径转换、中断恢复
3. 缺基分支或新分支名时，进入理解闭环一次一问
4. 本 skill 无需账号类环境信息（无 .agents/.env 键）
