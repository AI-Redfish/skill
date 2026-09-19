# Superpowers：开发流程技能包

> 来源：[runoob Superpowers](https://www.runoob.com/skills/superpowers-skill.html)
> GitHub：https://github.com/obra/superpowers（MIT）

## 一、解决什么问题

AI 编程工具拿到需求后的默认行为是**直接写代码**。复杂需求下"直接写"会跳过关键步骤：把需求搞清楚。需求里有多少模糊的地方，最终都会变成代码里的问题。

Superpowers 把软件开发的关键环节——**需求梳理、实现规划、测试驱动开发、代码审查、分支管理**——整理成技能文件，AI 会在合适时机自动触发对应工作流。

> 一句话：给 AI 装上一套开发方法论，让它按流程干活，不是拿到需求就动手写。

## 二、工作流程四阶段

| 阶段 | 名称 | 做什么 | 产出 |
|---|---|---|---|
| 1 | 需求梳理 | AI 反过来问问题，把模糊处搞清楚，分段展示设计方案供确认 | 确认的需求文档 |
| 2 | 实现规划 | 拆成 2-5 分钟的具体任务（文件、代码、验证方式） | 可执行的任务清单 |
| 3 | 执行任务 | 逐一执行，每个任务完成后双轮检查（规格+质量） | 经过验证的代码 |
| 4 | 交付代码 | 确认所有任务完成、质量合格 | 可交付的代码 |

任务粒度细到"一个初级工程师拿到描述就能执行"——这是为了让 subagent 可靠执行每一步。

## 三、安装

```bash
# Claude Code（推荐）
/plugin install superpowers@claude-plugins-official
# 或
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace

# Cursor：Agent 对话框输入 /add-plugin superpowers
# Codex CLI：/plugins 搜索安装
# Gemini CLI：gemini extensions install https://github.com/obra/superpowers
```

> 每个工具需单独安装，在 Claude Code 装了不等于 Cursor 里也有。

验证：输入"设计一个好看的手机产品宣传页"，看到 `superpowers:brainstorming` 即安装成功。

## 四、三个核心工作流

### TDD（test-driven-development）
强制按 **RED → GREEN → REFACTOR**：先写失败的测试，看着它失败，再写最少代码通过，最后重构。写测试前就写了代码？要求删掉重来。

### Git Worktree 隔离（using-git-worktrees）
设计确认后自动建隔离工作分支，AI 修改不污染主分支，多任务并行或回滚时有用。

### 系统性调试（systematic-debugging）
遇错走 4 步：**复现问题 → 定位根因 → 实施修复 → 验证修复**，而不是靠猜着改。

## 五、使用前须知

| 注意点 | 说明 |
|---|---|
| 流程变长 | 简单需求也会先梳理再动手；小 bug/一行配置不需要套全流程 |
| 需要参与讨论 | brainstorming 阶段需要你回答问题、确认方案；定位是人机协作而非全自动 |
| 体验差异 | 不同工具、项目、任务复杂度表现不同 |

---

⬆️ [返回总索引](../../README.md)
