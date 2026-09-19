# 测试指南：单测 + 端到端 + 环境收取 + 结果落盘

测试门（SKILL.md §5）的完整标准。测试结果按官方 skill-creator 的 workspace 布局落盘，
这样测试通过后 `gen_test_report.py` 能直接调用官方脚本出报告。

## 1. 测试层次

| 层次 | 对象 | 方式 | 必需性 |
|---|---|---|---|
| 脚本单测 | scripts/*.py | `tests/test_*.py`（unittest 即可，纯标准库；`python -m unittest discover -s tests`） | 有脚本就必须有 |
| 端到端 | 完整 skill 流程 | 模拟用户 prompt 走完整工作流，产物存 `outputs/` | 必须（≥2 例） |
| 触发测试 | description | 正向应触发 + 负向不应触发用例；有官方 `eval` 能力且环境有 claude CLI 时用 `run_eval.py`，否则人工模拟 | 必须（≥4 例：2 正 2 负） |
| 基准对比 | 有无 skill 差异 | with_skill vs without_skill 双跑 | 推荐（报告更有说服力） |

用例来源：需求澄清阶段收集的用户说法 + review-guide 的负向/边界清单。
端到端用例存 `<target>/evals/evals.json`（官方 schema）：

```json
{
  "skill_name": "xxx",
  "evals": [
    {"id": 1, "prompt": "用户真实任务说法（信息完整）…",
     "expected_output": "期望结果的客观描述",
     "files": [],
     "expectations": ["可客观验证的断言，如：生成 table-1.csv 且行数=3",
                      "最终输出开头一句话复述了需求",
                      "输出列出关键假设与剩余不确定性"]},
    {"id": 2, "prompt": "信息不全的说法（如未给输入路径/关键参数）…",
     "expected_output": "skill 进入理解闭环：只提出一个问题，不产出最终结果",
     "expectations": ["仅提出一个问题（不是多个）", "未输出最终方案/产物"]}
  ]
}
```

**双闭环行为验证（必须覆盖，两类各至少 1 例）**：
- 信息缺失用例：skill 只问一个问题、不给最终方案（理解闭环生效）
- 完整信息用例：最终输出含需求复述 + 关键假设 + 不确定性标注（最终输出要求生效）

## 2. 环境信息收取（需要账号等时）

```bash
# a. 查缺（键名来自需求澄清阶段的清单）
uv run <skill_dir>/scripts/env_utils.py missing --keys ZENTAO_URL,ZENTAO_USER,ZENTAO_PASS --workdir <workdir>
# b. 向用户逐项询问缺失键（一次只问一个；说明用途、是否敏感、将保存到 <workdir>/.agents/.env）
#    用户输入后写入并防泄漏：
uv run <skill_dir>/scripts/env_utils.py set ZENTAO_URL=https://... ZENTAO_USER=... --workdir <workdir>
uv run <skill_dir>/scripts/env_utils.py ensure-gitignore --workdir <workdir>
```

- 用户拒绝提供 → 按 skill 声明的降级行为执行，测试报告标注"未验证依赖该环境的部分"
- 敏感值只在收取瞬间出现在对话里，之后的日志/报告一律脱敏（`env_utils.py list` 默认脱敏）
- 伪造/占位凭据只允许用于"连通性必然失败"的负向测试，结论须注明

## 3. workspace 布局（与官方工具对齐）

```
<workspace>/                          # <workdir>/<skill-name>-workspace/
├── gate-state.json                   # 门禁状态（gate.py 维护）
├── checklist-round-N.json            # 机器检查输出
├── review-round-N.md                 # AI 评审记录
├── test-failures-round-N.md          # 失败汇总（test-fail 时）
└── iteration-N/                      # 第 N 轮测试（每轮测试 +1）
    ├── eval-<id>-<短名>/             # 每个端到端用例一个目录
    │   ├── eval_metadata.json        # {"eval_id","eval_name","prompt","assertions":[]}
    │   ├── with_skill/
    │   │   ├── outputs/              # 执行产物（评审页据此展示）
    │   │   └── run-1/
    │   │       ├── grading.json      # 断言判定（格式见下）
    │   │       └── timing.json       # {"total_tokens","duration_ms","total_duration_seconds"}
    │   └── without_skill/            # 基线（可选但推荐；同样布局）
    └── benchmark.json|.md            # gen_test_report 调官方脚本生成
```

`grading.json`（官方 aggregate_benchmark/viewer 依赖的精确字段名）：

```json
{
  "summary": {"pass_rate": 1.0, "passed": 3, "failed": 0, "total": 3},
  "expectations": [
    {"text": "断言描述", "passed": true, "evidence": "证据：文件/输出片段/行为"}
  ]
}
```

- 判定每条断言要给**真实证据**（产物存在且内容正确），不接受"看起来对"（参考官方 grader.md）
- 可程序化验证的断言优先写一次性校验脚本跑，而不是肉眼判断

## 4. 触发测试（description 质量）

- 生成 ≥8 条 query：一半应触发（覆盖不同说法/口语/未点名场景），一半不应触发
  （**近邻负例**：关键词相近但该 skill 不该接的场景，不要用明显无关的凑数）
- 有官方 `eval` 能力且有 claude CLI：`cd <dep> && python -m scripts.run_eval --eval-set <json> --skill-path <target>`
- 结果并入 workspace；触发率不达标 → 属于评审问题：`test-fail` 退回，
  按 review-guide 清单 A 改 description 后重走评审

## 5. 判定与流转

- 通过标准：单测全过 + 端到端断言全部 passed（pass_rate=1.0）+ 触发测试达标
  （正向 ≥85% 触发、负向 100% 不触发；用户另有约定从其约定）
- 通过 → `gate.py test-pass --summary "..."`
- 不过 → 失败项（用例、断言、证据、初步归因）写入 `<workspace>/test-failures-round-N.md`
  → `gate.py test-fail --failures-file <该文件>` → 修改 skill → **重走评审门**（SKILL.md §4）

## 6. 测试报告

测试通过后（SKILL.md §6）：

```bash
uv run <skill_dir>/scripts/gen_test_report.py --workspace <workspace> --skill-name <name> \
    [--trigger-results <run_loop.json>]     # 做过官方 loop 优化时附上
```

产物在 `<workspace>/reports/`：`benchmark.json/md`（官方 aggregate_benchmark）、
`review.html`（官方评审页静态版）、`trigger-report.html`（可选）、`test-report.md`（汇总）。
向用户汇报：通过率、各配置对比、门禁轮次与置信度、降级项（如有）。
