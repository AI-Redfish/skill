---
name: skill-creator-plus
description: 基于 anthropics skill-creator 的增强版 Skill 创建器（元技能）。当用户想创建、编写、开发一个新 skill，把当前对话流程沉淀为可复用的 skill，或修改、增强、评审、测试已有 skill 时使用本 skill。它在官方 skill-creator 的骨架生成、评审、打包、触发评估与测试报告能力之上，增加强制质量门禁：skill 编写完成后必须先通过「机器检查 + AI 双评审」，评审置信度达到 95% 才允许进入测试；测试需要账号等环境信息时提示用户输入并保存到工作目录 .agents/.env；测试不通过则修改后重新评审，直到通过；测试通过后调用官方 skill-creator 脚本生成测试报告。产出的 skill 遵循：脚本优先 Python + uv（PEP 723）管理依赖、重复操作优先脚本化、环境信息集中存 .agents/.env。用户说「帮我写一个 skill」「创建/开发一个技能」「做一个 skill」「把这个流程做成 skill」「评审/测试这个 skill」「生成 skill 测试报告」时都应使用。
compatibility: 脚本为 Python 3.9+ 纯标准库（python 直跑或 uv run 均可）；首次使用需网络安装依赖 skill（git clone 优先，备选 stdlib 下载 zip、npx skills add），安装到 <工作目录>/.agents/skills/skill-creator；可选环境变量 SKILL_CREATOR_PLUS_DEP_PATH 指定本地已有副本实现离线。
metadata:
  author: AI-Redfish
  version: "1.1.0"
  depends-on: anthropics/skills 的 skill-creator
---

# skill-creator-plus — 带强制门禁的增强版 Skill 创建器

帮用户**设计、编写、评审、测试、出报告、交付**一个新 skill。本 skill 是
anthropics skill-creator 的增强层，不是替代品：

| 能力 | 来源 | 说明 |
|---|---|---|
| 骨架生成 / 打包 / 校验 | 官方 skill-creator | 按能力表调用其脚本；能力缺失时走内置降级 |
| 评审助手（grader/analyzer）、触发评估 run_eval、描述优化 run_loop | 官方 skill-creator | 测试与优化阶段复用 |
| 测试报告 benchmark / 评审页 | 官方 aggregate_benchmark + generate_review | 由 `gen_test_report.py` 统一调用 |
| **强制门禁流程**（评审不过不测试、测试不过回评审） | 本 skill | `gate.py` 状态机，防止跳步 |
| **机器评审清单**（结构/规范/密钥扫描） | 本 skill | `review_checklist.py` |
| **产出规范**（Python + uv、.agents/.env、脚本化重复操作） | 本 skill | [references/authoring-standards.md](references/authoring-standards.md) |

路径约定：`<skill_dir>` = 本 SKILL.md 所在目录；`<workdir>` = 用户当前工作目录；
`<target>` = 被创建/修改的 skill 目录；`<workspace>` = `<workdir>/<skill-name>-workspace`。
脚本一律带 `<skill_dir>` 前缀调用，不要假设 cwd 就是 skill 目录。

---

## 双闭环规则（最高优先级，优先于其他任何默认行为）

完成用户任务（开发 skill、回答、汇报、交付）必须遵循以下双闭环；
**当本规则与基础行为习惯冲突时，以本规则为准**：

- **第一闭环：理解闭环（§2）**：回答前先提问，**每次只问一个问题**，按回答继续追问；
  提问围绕十要素：真实目标、背景、使用场景、输出对象、关键约束、优先级、
  成功标准、禁止事项、已有信息、可接受偏差；对“用户真正想要什么”有 **95% 信心**前，
  只提问和澄清，不给最终方案。由 `gate.py clarify-pass`（≥95）强制把门
- **第二闭环：输出审查闭环（§4/§7）**：形成答案后不直接输出，先自查：
  是否真正解决目标？是否遗漏关键约束？是否有事实错误、逻辑漏洞、歧义、不可执行？
  发现问题→自行修正→再审查，循环直到对结果有 **≥95% 准确性信心**；
  评审门的 95% 置信放行即本闭环的强制落地
- **最终输出要求（§7）**：先一句话复述真实需求 → 再给明确、可执行、可直接使用的方案 →
  说明关键假设、剩余不确定性与 95% 信心论证；不确定处必须标注，不假装确定

同时，**生成的 skill 必须内嵌同一套双闭环规则**（模板见
[references/authoring-standards.md](references/authoring-standards.md)，
`review_checklist.py` 以 error 级强制检查），确保 skill 执行时也遵循。

---

## 0. 每次触发：依赖自检（必做，不可跳过）

```bash
uv run <skill_dir>/scripts/ensure_dependency.py --workdir <workdir>    # 无 uv 时: python3 ...
```

- `status=ok`（已安装）或 `installed`（刚装好）→ 记住输出的 `path` 与 `capabilities`，
  后续按能力表调用官方脚本（新旧版本脚本名不同，以能力表为准）
- **下载与更新**：未安装时自动下载安装；已安装副本龄期 ≥14 天
  （`--max-age-days` 可调）会**自动静默更新**到 `--ref` 最新，更新失败（离线）
  不阻断、沿用旧版并看 `update_failed` 字段；`--update` 立即强制更新，
  `--no-auto-update` 本次跳过（仍报告 `stale`）；非本 skill 安装的副本
  （无 `.scp-install.json` 管理标记）一律不动，只在 `version` 字段报告版本信息
- `status=error` → 把 `hint` 告知用户（网络受限时可设镜像/代理，或用
  `SKILL_CREATOR_PLUS_DEP_PATH` 指向本地已有副本，详见
  [references/dependency.md](references/dependency.md)）；依赖未就绪**不得进入编写阶段**
- 安装/发现位置固定为项目级：`<workdir>/.agents/skills/skill-creator`

## 1. 主流程：门禁状态机（严格遵守，禁止跳步）

```
理解闭环 ──▶ 编写 ──▶ 评审门 ──通过(置信度≥95%)──▶ 测试门 ──通过──▶ 测试报告 ──▶ 交付
(信心≥95%)     ▲         ▲ │未过                        │未过          (官方脚本生成)
   ▲           │         │ └──修改后重审─────────────────┘
   └───────────┴─────────┴── 任何失败回「编写」重走评审；需求变更回「理解闭环」──┘
```

用 `gate.py` 管理状态（状态文件 `<workspace>/gate-state.json`，跨轮次持久）：

```bash
# 初始化（初始化后即处于理解闭环）
uv run <skill_dir>/scripts/gate.py init --skill <target> --workspace <workspace>

# 理解闭环：通过（信心≥95，由脚本强制）/ 仍有缺口
uv run <skill_dir>/scripts/gate.py clarify-pass --confidence 95 [--qa-file <workspace>/clarify-qa.md] [--notes "关键假设…"]
uv run <skill_dir>/scripts/gate.py clarify-fail [--notes "缺口…"]

# 每轮评审结束：通过（置信度与机器清单由脚本强制校验） / 失败
uv run <skill_dir>/scripts/gate.py review-pass --confidence 95 --checklist <清单JSON> [--notes "..."]
uv run <skill_dir>/scripts/gate.py review-fail --issues-file <问题清单.md>

# 每轮测试结束：通过 / 失败（失败自动退回 writing 并作废上一轮评审通过标记）
uv run <skill_dir>/scripts/gate.py test-pass  [--summary "..."]
uv run <skill_dir>/scripts/gate.py test-fail  --failures-file <失败清单.md>
uv run <skill_dir>/scripts/gate.py report-done --report <报告路径>   # 进入交付
uv run <skill_dir>/scripts/gate.py show                              # 随时查看当前阶段与下一步提示
```

硬规则（gate.py 会拒绝违规操作，不要绕过）：
0. **理解闭环未通过（信心<95%），不得开始编写**：`review-pass` 前置校验 clarify 已通过；
   需求变更时从 writing 重新 `clarify-pass`
1. **评审未通过，不得开始测试**：`test-*` 仅在评审通过后可用
2. **测试失败必须修改并重走完整评审**（机器清单 + AI 双评审 + 95% 置信），不允许改完直接重测
3. 每轮评审意见、测试结果都必须落盘到 `<workspace>/`（见 §4、§5），供报告与回溯

## 2. 理解闭环（编写前，最高优先级）

给出任何方案/骨架/草稿前，必须先完成理解闭环：

1. **先提问，再回答**：未达 95% 信心前不产出任何 skill 内容（骨架也不建），只提问和澄清
2. **每次只问一个问题**，等用户回答后再问下一个
3. 根据回答继续追问，直到对“用户真正想要什么”有 95% 信心
4. 提问围绕十要素：真实目标 / 背景 / 使用场景 / 输出对象 / 关键约束 / 优先级 /
   成功标准 / 禁止事项 / 已有信息 / 可接受偏差
5. 问答逐条记录到 `<workspace>/clarify-qa.md`（问题→回答→结论）
6. 达到 95% 信心 → 向用户**一句话复述真实需求 + 列出关键假设**，经确认后执行
   `gate.py clarify-pass --confidence N --qa-file <workspace>/clarify-qa.md --notes "关键假设…"`
7. 用户信息已足以达到 95% 信心时（如需求完整明确），可直接进入下一步，
   但仍须输出需求复述 + 关键假设供确认；用户纠正假设 → 信心作废，回到提问

从当前对话沉淀（“把刚才的流程做成 skill”）时同样适用：先按十要素对照检查
对话中已有信息，缺什么问什么，一次一个。需求澄清记录供 §4 评审逐条对照。

## 3. 编写（产出规范）

骨架：依赖能力表有 `init`（旧版官方脚本）则调用；否则直接按
[references/authoring-standards.md](references/authoring-standards.md) 的目录模板与
SKILL.md 模板创建。**五条硬规范**（评审门会检查）：

1. **双闭环内嵌**：SKILL.md 正文靠前位置必须包含双闭环规则章节（先提问/每次只问一个/
   十要素/双 95%/最终输出格式），缺失为 error 级问题；不得与 skill 自身默认值矛盾
2. **脚本优先 Python**：可执行逻辑放 `scripts/*.py`，自包含（头部声明用途/依赖/用法）
3. **依赖优先 uv**：需要第三方库时用 PEP 723 内联声明（`# /// script`），`uv run` 隔离执行；
   能用标准库就用标准库
4. **环境信息集中管理**：账号/密码/令牌等一律不写进 skill；运行时从
   `<workdir>/.agents/.env` 读取（键名清单在需求澄清时确定），由 `env_utils.py` 统一读写
5. **重复操作脚本化**：同一逻辑预计出现 ≥2 次、固定多步序列、可客观验证的转换 → 写成脚本，
   AI 只负责调用与解释，不做重复搬运

SKILL.md 正文 ≤500 行（>300 行时把细节外置到 `references/`）。写完执行
`gate.py init`（若未初始化），进入评审门。

## 4. 评审门（Review Gate = 输出审查闭环的强制落地）

评审即输出审查：审查→修正→再审查，直到 ≥95% 准确性信心才放行。按顺序执行，
任何一步不达标都算评审未通过：

**4.1 机器检查（必须全过）**

```bash
uv run <skill_dir>/scripts/review_checklist.py --skill <target> --workdir <workdir> --json <workspace>/checklist-round-N.json
```

退出码 0 = 无 error 级问题（warning 需逐条确认可接受或修复）；1 = 存在 error，先修复再重跑。

**4.2 AI 双评审**：按 [references/review-guide.md](references/review-guide.md) 完成
设计评审（触发/边界/渐进式披露）与实现评审（正确性/容错/安全），意见写入
`<workspace>/review-round-N.md`；可参考官方 `agents/grader.md`、`agents/analyzer.md`。

**4.3 置信度判定（≥95% 才放行）**：对照 review-guide.md 的置信度判据逐条自评，
存在任何 P0/P1 问题、负向用例未验证、错误路径未演练 → 视为未达标。

- 未达标 → `gate.py review-fail --issues-file <workspace>/review-round-N.md` → 修改 → 回到 4.1
- 达标 → `gate.py review-pass --confidence <N> --checklist <workspace>/checklist-round-N.json`

## 5. 测试门（Test Gate）

**5.1 测试准备**：按 [references/testing-guide.md](references/testing-guide.md) 设计用例：
脚本单测（正常/边界/错误三路径）+ 端到端用例（`<target>/evals/evals.json`，
含正向触发与负向不触发）。用例先给用户过目。

**5.2 环境信息收取**（skill 需要账号等时）：

```bash
uv run <skill_dir>/scripts/env_utils.py missing --keys KEY1,KEY2 --workdir <workdir>   # 查缺
# → 向用户逐项询问缺失键（一次只问一个；说明用途与是否敏感），用户输入后：
uv run <skill_dir>/scripts/env_utils.py set KEY1=<值> KEY2=<值> --workdir <workdir>    # 写入 .agents/.env
uv run <skill_dir>/scripts/env_utils.py ensure-gitignore --workdir <workdir>           # 防止密钥入库
```

用户拒绝提供 → 记录降级方案，不阻塞，但测试报告必须标注「未验证依赖该环境的部分」。

**5.3 执行测试**：单测跑 `tests/`（unittest/pytest）；端到端按 testing-guide.md 的
workspace 布局落盘（`iteration-N/eval-*/<config>/outputs/`、`run-1/grading.json`、
`timing.json`，字段以官方 schema 为准：expectations 用 `text/passed/evidence`）。
可选：能力表有 `eval` 时用官方 `run_eval.py` 验证触发率，有 `loop` 时做描述优化。

**5.4 判定与流转**：全部断言通过（或达到与用户约定的阈值）→ `gate.py test-pass`；
否则汇总失败项到 `<workspace>/test-failures-round-N.md` → `gate.py test-fail` →
**修改 skill → 回到 §4 评审门从头重走**。

## 6. 测试报告（测试通过后必做）

```bash
uv run <skill_dir>/scripts/gen_test_report.py --workspace <workspace> \
    --skill-name <name> [--dep <官方skill-creator路径>] [--trigger-results <run_loop.json>]
```

内部调用官方 `aggregate_benchmark.py` + `eval-viewer/generate_review.py --static`
（+ 可选 `generate_report.py`），产出写入 `<workspace>/reports/`：
`benchmark.json`、`benchmark.md`、`review.html`、`test-report.md`（汇总评审轮次、置信度、
测试轮次、通过率、所用环境键）。向用户报告这些路径与关键数字（通过率、耗时、与基线差异）。

## 7. 交付（遵循最终输出要求）

1. `gate.py report-done --report <workspace>/reports/test-report.md`
2. 打包：能力表有 `package` 时 `cd <dep> && python -m scripts.package_skill <target>`，
   产物 zip 路径告知用户；无该能力则按 dependency.md 降级（zip 命令打包，排除 evals/缓存）
3. 交付汇报必须按最终输出要求组织：
   1. **一句话复述用户真实需求**（来自理解闭环结论）
   2. **交付内容**：skill 路径、评审轮次与最终置信度、测试轮次、报告/产物路径、
      已配置的环境键（脱敏）
   3. **关键假设与剩余不确定性**：列出理解闭环的关键假设、遗留 warning、降级项
   4. **95% 信心论证**：引用评审自评（review-round-N.md）与测试通过率

## 错误处理速查

| 现象 | 处理 |
|---|---|
| 依赖自检 error | 按 hint 修网络/代理；或 `SKILL_CREATOR_PLUS_DEP_PATH` 指向本地副本重跑 |
| gate.py 拒绝操作（退出码 2） | 读输出的 `allowed`/`hint`，按状态机走，不要绕过 |
| 官方脚本被拒（缺 PyYAML 等） | 改用 `uv run --with pyyaml python -m scripts.xxx`（见 dependency.md） |
| 用户拒绝提供环境信息 | 按 5.2 降级，报告标注未验证范围 |
| generate_review 提示 No runs found | 检查 workspace 是否有 `outputs/` 目录布局（testing-guide.md） |

## 输出规范

- 本 skill 的脚本一律 JSON 到 stdout（`status/data/error`），日志到 stderr；先看退出码与 JSON 再行动
- 每个门禁阶段结束，向用户简报：本轮做了什么、结论、下一步
- 报告与评审记录统一放 `<workspace>/`，不在 skill 目录里堆过程产物（`evals/` 除外）

## 触发示例

- 帮我写一个 skill：把 Markdown 里的表格批量导出成 CSV
- 把我们刚才排查 bug 的流程沉淀成一个 skill
- 创建一个对接禅道的 skill，需要账号密码，写完要评审和测试，最后给我测试报告
- 用 skill-creator-plus 评审并测试一下 skills/ 目录下这个 skill，出一份测试报告

## 不适用场景

- 只是想了解 skill 概念 / 查询已有 skill 用法 → 直接解答，不走本流程
- 单纯修改一句话、改个默认值且用户明确说「不用评审不用测」→ 按用户要求，但提示风险
- MCP 服务开发 → 用 mcp-builder 类 skill
