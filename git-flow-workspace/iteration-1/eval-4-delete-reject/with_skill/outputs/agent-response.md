删除 worktree 不在 git-flow 的适用范围内（本 skill 只负责创建，且禁止执行任何删除类操作）。
如确认删除，请自行执行：
  git worktree remove <目录路径>        # 已确认无未提交改动时
  git worktree remove --force <目录>    # 有未提交改动时需 --force
删除后可用 `git worktree prune` 清理登记。请先确认 worktree 内没有未提交/未合并的工作成果。