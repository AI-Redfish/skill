# git-flow 排查手册（troubleshooting）

按 `worktree_create.py` 的 error_code / 场景查表。原则：**不凭记忆猜测，
先取证（跑诊断命令）再行动；任何删除动作必须先获得用户确认。**

## 0. 通用诊断命令

```bash
git worktree list                      # 当前所有 worktree 与分支占用
git worktree list --porcelain          # 机器可读版（脚本守卫同款数据源）
git branch --list "<分支名>"            # 本地分支是否存在
git branch -r | grep -i "<关键词>"      # 远程分支核对（注意 origin/ 前缀）
git log <base> -1 --format="%h %ci %s" # 基分支本地引用的新鲜度
```

## 1. WORKTREE_ADD_FAILED / 检出中断恢复

**症状**：`git worktree add` 执行中被杀（工具超时、断电、Ctrl-C），
目录被 git 回滚消失，但分支残留。

**取证**：
```bash
git branch --list "<新分支名>"            # 分支还在？
ls "<父目录>/<目录名>" 2>/dev/null       # 目录已消失？
git worktree list --porcelain            # 无该 worktree 条目？
```
三分支判定（分支在 + 目录无 + 无条目）= 典型中断残留。

**恢复**（不要重新 `-b`）：
```bash
python3 <skill_dir>/scripts/worktree_create.py --repo <主仓库> \
  --base <基分支> --branch <新分支> --reuse-branch
```
若脚本报 `PATH_EXISTS`：目录有残留内容，先向用户展示目录内容，
**经用户确认后**删除目录并执行 `git worktree prune`，再重试。

**预防**：工具超时 ≥900s；不在检出中途打断。

## 2. PATH_EXISTS（目标目录已存在）

1. `ls -la <目录>` 确认内容：空目录/半成品检出 → 建议（需用户确认后）清理：
   `git worktree prune && rm -rf <目录>`（先 prune 再删目录，防止悬空登记）
2. 有真实内容 → 换新分支名，或与用户确认是否应在该目录继续工作

## 3. BRANCH_CHECKED_OUT（分支被其他 worktree 占用）

git 限制：一个本地分支同一时刻只能被一个 worktree 检出。
- `git worktree list` 找到占用方
- 与用户确认：换分支名，或改在现有 worktree 中开发

## 4. BASE_NOT_FOUND（基分支不存在）

1. `git branch -r | grep -i <关键词>` 核对真实名称（大小写、origin/ 前缀）
2. 本地从未 fetch 过该分支 → `git fetch origin` 或加 `--fetch` 重试
3. 远程确无此分支 → 向用户求证基分支名，不自行猜测替代分支

## 5. fetch 超时 / 网络受限

- 症状：`git fetch` 超过 120s 无响应或报 `Could not resolve host / timeout`
- 降级路径（skill 默认）：跳过 fetch，直接使用本地 `origin/*` 引用
- 引用过旧（`git log <base> -1 --format=%ci` 早于 1 天）时告知用户时间差，
  由用户决定：接受本地引用 / 换网络后 `--fetch` 重试 / 手动 fetch
- 可选加速：`git fetch <remote> <单分支>` 比 fetch --all 快得多

## 6. WSL / Windows 路径转换

| 环境 | 用户可见格式 | 命令行格式 |
|---|---|---|
| WSL bash | `D:\develop\...` | `/mnt/d/develop/...` |
| Git Bash | `D:\develop\...` | `/d/develop/...` |
| PowerShell/CMD | `D:\develop\...` | `D:\develop\...` |

- 脚本 JSON 同时输出 `worktree_path`（posix）与 `worktree_path_windows`（如有）
- 手工转换：`/mnt/<盘>/a/b` ↔ `<盘大写>:\a\b`；注意反斜杠方向

## 7. WSL可用但Windows Git / IDEA / Maven无法读取HEAD

`.git` 在linked worktree中是文件，这是正常格式；先读取其 `gitdir:`，再查真实管理目录的 `gitdir` 回指针与 `commondir`。`/mnt/d/...` 是WSL路径，Windows Git不能直接识别；Windows盘符绝对路径也不能直接用于WSL Git。

```bash
python3 <skill_dir>/scripts/worktree_paths.py --repo <worktree>
# 用户已授权修复，且当前端Git能解析该worktree时：
python3 <skill_dir>/scripts/worktree_paths.py --repo <worktree> --repair
```

修复查询真实管理目录而非推算 `.git/worktrees/<目录名>`，两个指针相对化，失败自动恢复原字节。主仓库与worktree位于不同Windows盘时不能用相对路径保证双端访问，选择同盘布局或单一Git运行环境并明确限制。

若当前端完全无法解析指针，切换到能解析的Git环境修复；不要盲目运行另一端 `git worktree repair` 将路径再次写成单端绝对路径。不要删除重建已有工作区。完成后从实际使用的Windows与WSL端分别验证根目录、分支、HEAD及 `git worktree list`；某一端Git不可用则报告未验证。

IDEA还需 Settings → Version Control → Git 的执行路径正确，以及 Directory Mappings 将项目根映射为Git。路径修复后仍有Git插件构建失败，再查插件兼容性，不能把跳过插件当作路径修复。

## 8. 大仓库性能参考

| 场景 | 实测 | 建议 |
|---|---|---|
| 13,437 文件仓库全量检出（WSL /mnt/d） | ≈6 分钟 | 超时 ≥900s |
| 同仓库在原生 ext4（WSL 内） | 显著更快 | 可考虑仓库放 WSL 内置盘 |
| sparse-checkout 需求 | — | 用户明确要求时另行处理，skill 默认全量 |
