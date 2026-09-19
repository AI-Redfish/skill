# skill-creator-plus

基于 [anthropics skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)
的增强版 Skill 创建器（元技能）：在官方能力（骨架/打包/校验/触发评估/基准/评审页）之上，
叠加**强制质量门禁**与**产出规范**。

## 与官方 skill-creator 的差异

| 维度 | 官方 | skill-creator-plus |
|---|---|---|
| 双闭环 | 无 | **理解闭环**（先提问/每次只问一个/十要素/95% 信心把门）+ **输出审查闭环**（审查-修正-再审查到 95%），并作为强制章节内嵌到生成的 skill |
| 流程 | 建议性循环，可跳步 | `gate.py` 状态机强制：**评审不过不测试，测试不过回评审** |
| 评审 | 人工 + 可选子代理 | 机器清单（`review_checklist.py`）+ AI 双评审 + **95% 置信度放行** |
| 测试 | 交互式 eval 循环 | 统一 workspace 落盘（官方 schema），失败自动退回评审 |
| 报告 | 手工调多个脚本 | `gen_test_report.py` 一键调官方脚本出 benchmark + HTML 评审页 + 汇总 |
| 产出规范 | 通用建议 | 硬规范：Python 优先、uv (PEP 723)、重复操作脚本化、环境信息集中 `.agents/.env` |
| 依赖 | 手工安装 | 每次触发自动检查/安装；副本 ≥14 天自动静默更新（可 `--update` 强制 / `--no-auto-update` 跳过；外部副本不动） |

## 使用

把本目录放入 agent 的 skills 目录（或项目 `.agents/skills/`），对 AI 说：

> 帮我写一个 skill：……（描述需求）

流程：依赖自检 → **理解闭环（一次一问到 95% 信心）** → 编写 → 评审门（机器+双评审+95%）→ 测试门（环境收取+测试）
→ 官方脚本测试报告 → 按最终输出要求交付（复述需求+方案+假设/不确定性+95% 论证）。
详见 [SKILL.md](SKILL.md)。

## 脚本（纯标准库，Python 3.9+，python/uv run 均可）

| 脚本 | 用途 |
|---|---|
| `scripts/ensure_dependency.py` | 检查/安装官方 skill-creator，输出能力表（兼容新旧版本） |
| `scripts/gate.py` | 门禁状态机（评审/测试/报告的流转与强制校验） |
| `scripts/review_checklist.py` | 机器评审：结构/frontmatter/触发描述/PEP 723/密钥扫描/.env 卫生 |
| `scripts/env_utils.py` | `<workdir>/.agents/.env` 的 list/get/set/missing/ensure-gitignore |
| `scripts/gen_test_report.py` | 调官方 aggregate_benchmark + generate_review 生成测试报告 |

## 目录

```
skill-creator-plus/
├── SKILL.md                  # 主流程
├── scripts/                  # 上述 5 个脚本
└── references/
    ├── dependency.md         # 依赖安装策略、版本差异与降级
    ├── authoring-standards.md# 被创建 skill 的编写规范（模板/PEP 723/.env/脚本化判定）
    ├── review-guide.md       # 评审清单与 95% 置信判据
    └── testing-guide.md      # 测试层次、workspace 布局、grading.json 格式
```
