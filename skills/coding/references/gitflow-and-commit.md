# v6 GitFlow 与提交纪律（吸收 bps-v6-gitflow + 会话单 commit 实践）

## 1. 核心链路与分支

```text
最新 tag -> feature/bugfix/hotfix -> dev 验证 -> release 提测/回归 -> 新 tag -> 同步 main
```

| 类型 | 命名 | 示例 |
|------|------|------|
| feature | `v版本号/feature/姓名-功能描述-日期` | `v6.0.8.1/feature/zly-sharelease-20261008` |
| bugfix | `bugfix/姓名-描述-bugid-日期` | `bugfix/王五-导出失败-67890-20260516` |
| hotfix | `hotfix/姓名-描述-bugid-日期` | `hotfix/李五-登录异常-12345-20260516` |
| release | `release/v版本号` | `release/v6.0.3.2` |

- 从最新稳定 tag（或发布基线）切分支，禁止从 `dev` 直接切。
- bugid 不加 `BUG-`/`H-` 前缀；`main` 仅生产基线，普通员工不 push。

## 2. merge / rebase

- 多人共享分支或 release 领先很多：`git merge release/vX`（冲突一次性处理）。
- 个人私有分支：可 `rebase`（线性历史）；共享分支禁止随意 rebase。

## 3. 提交信息（Conventional Commits）

```text
<type>(<scope>): <description>

[body 分点说明]
```

type：`feat/fix/refactor/docs/test/chore/perf/ci`；scope 用模块或边界（如 `租赁台账`、`print`、`upms`）。禁止无信息描述（`fix: fix bug`）。破坏性变更用 `!` 或 `BREAKING CHANGE:`。

## 4. 会话实战：单 commit 合并纪律

用户要求"将分支创建至今的修改合并成一个 commit"时：

```bash
git add -A
git reset --soft <分支基点>          # 基点 = git rev-parse <首个提交>^
git commit -m "<type>(<scope>): <标题>

- 分点正文"
```

- 或对唯一提交直接 `git commit --amend`（需同步更新正文时用 `-m` 重写）。
- 先 `git config user.name/user.email` 确认身份（WSL 侧常未配置，按历史提交作者对齐到 repo 级）。
- 旧提交被替换后如已推送远端，提示用户需 `git push --force-with-lease`；仅本地则无需处理。
- 合并后验证：`git log --oneline <基点>..HEAD` 只有一条、`git status --porcelain` 为空、`git show --stat HEAD` 文件数与预期一致。

## 5. 执行前检查

- 工作区是否干净、是否有用户未提交改动（不得混入）。
- 是否改写历史（rebase/amend/force push）——仅在用户要求时执行。
- 合入前是否已本地解冲突并通过编译/最小验证。

## 6. 禁止事项

禁止从 dev 直接切 feature/bugfix/hotfix；禁止绕过 dev 直接进 release；禁止 push main；禁止覆盖/复用已发布 tag；禁止占位分支名与缺 bugid 的生产修复分支名。
