# git-flow

Git 与代码托管平台的统一操作 skill。覆盖仓库同步、检索、分支、提交、合并/rebase、标签、worktree、子模块与迁移，以及 GitHub/GitLab/Gitee 的 PR/MR、Issue、CI、Release 操作。

GitHub 文档、README、schema 与 Release 资产获取已并入本 skill。按需读取 [抓取与校验流程](references/github-docs-assets.md)，不再使用独立的 `github-docs-asset-fetch`。

所有操作先确认对象与授权范围；查询/下载不隐含提交、推送或发布授权。以下保留 worktree 脚本的原有用法。

## worktree 核心规则

1. worktree 目录 = 主仓库**同级**（父目录下）
2. 目录名 = 新分支名，`/` 全部替换为 `_`
   （`v6.0.8.1/feature/zly-sharelease-20261008` → `v6.0.8.1_feature_zly-sharelease-20261008`）
3. 新分支基于用户指定基分支（通常 `origin/dev/vx.x.x`）

## 快速使用

```bash
# 预览
python3 scripts/worktree_create.py --repo /path/to/repo \
  --base origin/dev/v6.0.8.1 --branch v6.0.8.1/feature/zly-xxx-20261008 --dry-run

# 正式创建（大仓库请给足超时，≥900s）
python3 scripts/worktree_create.py --repo /path/to/repo \
  --base origin/dev/v6.0.8.1 --branch v6.0.8.1/feature/zly-xxx-20261008
```

| 参数 | 说明 |
|---|---|
| `--base` | 基分支（必填），如 `origin/dev/v6.0.8.1` |
| `--branch` | 新分支名（必填） |
| `--repo` | 主仓库路径，默认当前目录 |
| `--fetch` | 创建前 fetch 基分支（默认跳过，网络受限时用本地引用） |
| `--reuse-branch` | 复用已存在的本地分支（中断恢复场景） |
| `--dry-run` | 只输出计划不执行 |

退出码：`0` 成功 / `1` git 执行失败 / `2` 前置校验失败（JSON 含 error_code 与 hint）。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 文档

- 统一任务入口与安全规则：[SKILL.md](SKILL.md)
- GitHub 文档与 Release 资产获取：[references/github-docs-assets.md](references/github-docs-assets.md)
- 排查手册（中断恢复/残留清理/fetch 超时/WSL 路径）：[references/troubleshooting.md](references/troubleshooting.md)
