# 依赖：anthropics skill-creator

本 skill 的运行依赖。每次触发先跑 `scripts/ensure_dependency.py`（SKILL.md §0）。

## 安装位置与搜索顺序

固定安装到**项目级**：`<workdir>/.agents/skills/skill-creator`。搜索时按顺序探测，
找到即用（因此用户级已有的副本也不会重复安装）：

1. 环境变量 `SKILL_CREATOR_PLUS_DEP_PATH`（离线/自备副本）
2. `<workdir>/.agents/skills/skill-creator`（本 skill 的安装点，亦为 `npx skills add` 的 universal 位置）
3. `<workdir>/.claude/skills/skill-creator`
4. `~/.claude/skills/skill-creator`、`~/.agents/skills/skill-creator`

有效性判定：目录含 `SKILL.md` 且 frontmatter `name: skill-creator`。

## 安装策略（自动降级）

| 顺序 | 方式 | 说明 |
|---|---|---|
| 1 | `git clone --depth 1 https://github.com/anthropics/skills` | 首选；可精确控制安装位置 |
| 2 | stdlib 下载 GitHub tarball（codeload） | 无 git 环境 |
| 3 | `npx -y skills add ... --skill skill-creator` | 最后手段；CLI 直装 `.agents/`（即安装点，目标不同才复制） |

三种都失败 → 提示用户：检查网络/代理，或手动放置副本后设
`SKILL_CREATOR_PLUS_DEP_PATH=<副本路径>` 重跑。**依赖未就绪不得进入编写。**

受限网络提示：git 可配镜像/代理；tarball 走 HTTPS（可设 `HTTPS_PROXY`）。
仓库地址可用 `--repo` 或环境变量 `SKILL_CREATOR_PLUS_REPO_URL` 指定镜像（如企业内
gitee/gitlab 镜像），便于无法直连 GitHub 的环境。

## 版本与更新策略

安装时在副本根写入管理标记 `.scp-install.json`（`managed_by/repo/ref/method/commit/
installed_at`）。`ensure_dependency.py` 据此决定是否更新：

| 场景 | 行为 |
|---|---|
| 副本龄期 ≥ `--max-age-days`（默认 14 天） | 自动静默更新（重新拉取并替换，重探能力表）；失败/离线**不阻断**，沿用旧版并输出 `update_failed` |
| `--update` | 立即强制更新（不论龄期） |
| `--no-auto-update` | 本次跳过自动更新，仍在 `version.stale` 报告过期 |
| 副本无管理标记（env 变量指向、~/.claude 等外部副本） | **一律不更新**，只报告 `version.managed=false`；需接管时删除该副本重跑 |

注意：更新 = 整体替换并重探能力表，官方上游若有 breaking change，
`missing_capabilities` 变化会自动反映在输出里，按上表降级方案处理即可。

## 版本差异与能力表

官方 skill-creator 的脚本随版本变化（旧版有 `init_skill.py` / `check_artifacts.py`，
新版改为 `quick_validate.py` 等）。**按能力而非文件名调用**，`ensure_dependency.py`
输出的 `capabilities` 即能力表：

| 能力 | 新版文件 | 旧版文件 | 本流程用途 | 缺失时降级 |
|---|---|---|---|---|
| validate | scripts/quick_validate.py | — | 辅助校验 | 用本 skill 的 `review_checklist.py`（更强） |
| init | — | scripts/init_skill.py | 骨架生成 | 按 authoring-standards.md 模板手工创建 |
| package | scripts/package_skill.py | 同名 | 打包 zip | `python -m zipfile -c` 手工打包（排除 evals/、__pycache__） |
| check_artifacts | — | scripts/check_artifacts.py | 产物校验 | 检查 zip <500KB、无超大文件 |
| eval | scripts/run_eval.py | — | 触发率评估 | 人工模拟正负向用例触发判断 |
| improve | scripts/improve_description.py | — | 描述优化 | 人工按 review-guide 触发词清单改写 |
| loop | scripts/run_loop.py | — | eval+improve 循环 | 跳过（可选步骤） |
| loop_report | scripts/generate_report.py | — | loop 结果转 HTML | 跳过 |
| benchmark | scripts/aggregate_benchmark.py | — | 汇总 grading.json | gen_test_report 标注降级 |
| viewer | eval-viewer/generate_review.py | 同名 | HTML 评审页 | gen_test_report 标注降级 |
| agents | agents/{grader,analyzer,comparator}.md | agents/ | AI 评审参考 | 仅用本 skill 的 review-guide.md |

## 调用方式备忘

官方脚本以 `scripts.` 包内互导（如 `from scripts.utils import ...`），因此**以模块方式
运行且 cwd 必须在 skill-creator 根目录**：

```bash
cd <dep> && python -m scripts.aggregate_benchmark <dir> --skill-name <name>
cd <dep> && python -m scripts.run_eval --eval-set <json> --skill-path <path>   # 需 claude CLI
python <dep>/eval-viewer/generate_review.py <workspace> --static out.html      # 独立入口，任意 cwd
```

- `run_eval.py` / `improve_description.py` / `run_loop.py` 依赖 `claude -p`（Claude Code CLI
  登录态），无 CLI 环境直接走降级，不要反复重试
- `quick_validate.py` 依赖 PyYAML：无该包时用 `uv run --with pyyaml python -m scripts.quick_validate ...`
- `generate_review.py` 交互模式会起本地服务并开浏览器；Agent 环境一律加 `--static`

`gen_test_report.py` 已内置以上调用约定，正常情况直接用它，不必手工拼命令。
