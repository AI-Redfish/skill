# weekly-report

基于 Git 提交记录的个人周报整理 skill。

## 功能

- 扫描仓库**所有 worktree** 的 HEAD 分支与关键远程分支（`origin/release*`、`origin/dev*`）
- 按**工作日窗口**（默认最近 5 个工作日，跳过周六日）与作者（默认当前 `user.email`）
  收集提交，按哈希去重
- 收集各 worktree **未提交修改**，在周报中单列"进行中的修改"
- 按 `references/report-format.md` 模板生成中文 Markdown 周报：
  数据来源 → 模块分组的工作总结（含 Bug 编号）→ 进行中 → 下周计划（拟定）

## 使用

对 AI 说："帮我整理这周的工作，生成周报"、"整理最近 10 个工作日的提交"。

脚本可直接调用：

```bash
python3 scripts/collect_commits.py --repo <仓库路径> [--workdays 5] \
    [--since YYYY-MM-DD] [--author <email>] [--json-out <文件>]
```

## 目录

```
weekly-report/
├── SKILL.md                     # 主流程（五段式 + 双闭环）
├── scripts/collect_commits.py   # 收集脚本（Python 3.9+ 纯标准库）
├── references/report-format.md  # 周报模板与整理规则
├── tests/                       # 单元测试（unittest）
└── evals/evals.json             # 端到端用例
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```
