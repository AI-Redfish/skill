#!/usr/bin/env python3
"""worktree_create.py — 基于指定基分支创建同级目录 worktree 并新建分支。

规则（内嵌，与 SKILL.md 一致）：
  1. worktree 目录 = 主仓库目录的**同级**（父目录下）
  2. worktree 目录名 = 新分支名，其中 "/" 替换为 "_"（Windows 安全字符）
  3. 新分支基于 --base 指定的基分支（通常为 origin/<dev 分支>）创建

用法:
  python3 worktree_create.py --base origin/dev/v6.0.8.1 \
      --branch v6.0.8.1/feature/zly-xxx-20261008 \
      [--repo /path/to/main-repo] [--fetch] [--reuse-branch] [--dry-run]

依赖: Python 3.9+ 纯标准库；需要 git 命令。
退出码: 0=成功  1=git 执行失败  2=参数/前置条件校验失败
输出: JSON 到 stdout（status/data/error），进度日志到 stderr。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PureWindowsPath

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[worktree_create] {msg}", file=sys.stderr)


def run_git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """执行 git 命令，返回 (退出码, stdout, stderr)。"""
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def to_windows_path(posix_path: str) -> str | None:
    """/mnt/<盘>/... → <盘>:\\...（仅 WSL 挂载路径需要转换，其余返回 None）。"""
    m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", posix_path)
    if not m:
        return None
    drive, rest = m.group(1).upper(), m.group(2)
    return str(PureWindowsPath(f"{drive}:\\", *rest.split("/")))


def fail(error_code: str, message: str, hint: str = "", extra: dict | None = None) -> int:
    """输出错误 JSON 并返回退出码 2（前置校验失败）。"""
    err: dict = {"error_code": error_code, "message": message, "hint": hint}
    if extra:
        err.update(extra)
    print(json.dumps({"status": "error", "error": err}, ensure_ascii=False, indent=2))
    return 2


# ---------------------------------------------------------------------------
# 校验逻辑
# ---------------------------------------------------------------------------

INVALID_BRANCH_PATTERNS = [
    (re.compile(r"\s"), "分支名含空白字符"),
    (re.compile(r"\.\."), "分支名含连续两个点（..）"),
    (re.compile(r"//"), "分支名含连续斜杠"),
    (re.compile(r"[*?:\[\]\\~^]"), "分支名含非法字符 * ? : [ ] \\ ~ ^"),
    (re.compile(r"\.lock$"), "分支名不能以 .lock 结尾"),
]

def validate_branch_name(name: str) -> str | None:
    """返回非法原因；合法返回 None。规则对齐 git check-ref-format 要点。"""
    if not name:
        return "分支名为空"
    if name.startswith(("/", "-", ".")) or name.endswith("/"):
        return "分支名不能以 / - . 开头或以 / 结尾"
    if "\\" in name:
        return "分支名含反斜杠（Windows 路径分隔符，git 不允许）"
    for pattern, reason in INVALID_BRANCH_PATTERNS:
        if pattern.search(name):
            return reason
    if name.endswith("."):
        return "分支名不能以点结尾"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="基于基分支创建同级目录 worktree（目录名 = 分支名中 / 替换为 _）"
    )
    parser.add_argument("--base", required=True, help="基分支，如 origin/dev/v6.0.8.1")
    parser.add_argument("--branch", required=True, help="新分支名，如 v6.0.8.1/feature/zly-xxx-20261008")
    parser.add_argument("--repo", default=None, help="主仓库路径（默认当前目录所在仓库）")
    parser.add_argument("--fetch", action="store_true",
                        help="创建前先 fetch 基分支（网络受限场景默认跳过，用本地 origin/* 引用）")
    parser.add_argument("--reuse-branch", action="store_true",
                        help="本地分支已存在时复用它（用于上次创建被中断的恢复场景），不再新建分支")
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不实际创建")
    args = parser.parse_args()

    # --- 1. 定位主仓库 ---
    repo = args.repo or os.getcwd()
    rc, toplevel, err = run_git(["rev-parse", "--show-toplevel"], cwd=repo)
    if rc != 0:
        return fail(
            "NOT_A_GIT_REPO",
            f"路径不是 git 仓库：{repo}",
            "确认 --repo 指向主仓库（含 .git 的目录），或先 cd 到仓库内再执行",
        )
    toplevel = toplevel.splitlines()[0]
    log(f"主仓库: {toplevel}")

    # --- 2. 校验新分支名 ---
    bad = validate_branch_name(args.branch)
    if bad:
        return fail("INVALID_BRANCH_NAME", f"分支名不合法：{args.branch}（{bad}）",
                    "参考格式 <版本>/feature/<缩写>-<主题>-<yyyymmdd>，如 v6.0.8.1/feature/zly-sharelease-20261008")

    # --- 3. 计算 worktree 路径（同级 + / → _） ---
    worktree_name = args.branch.replace("/", "_")
    parent_dir = str(Path(toplevel).parent)
    worktree_path = str(Path(parent_dir) / worktree_name)
    win_path = to_windows_path(worktree_path)

    # --- 4. 前置守卫 ---
    if Path(worktree_path).exists():
        return fail(
            "PATH_EXISTS",
            f"目标目录已存在：{worktree_path}",
            "若为上次中断残留：确认目录内容无用后删除该目录，并执行 `git worktree prune` 后重试；"
            "若是误建目录请更换分支名或移动该目录",
        )

    rc, existing_wt, _ = run_git(["worktree", "list", "--porcelain"], cwd=toplevel)
    occupied = any(
        line.startswith("branch ") and line.split(" ", 1)[1] in (f"refs/heads/{args.branch}", args.branch)
        for line in existing_wt.splitlines()
    )
    if occupied:
        return fail("BRANCH_CHECKED_OUT",
                    f"分支 {args.branch} 已被其他 worktree 检出",
                    "一个分支只能被一个 worktree 检出；如需在新目录开发请换分支名")

    rc, branch_sha, _ = run_git(["rev-parse", "--verify", f"refs/heads/{args.branch}"], cwd=toplevel)
    branch_exists = rc == 0
    if branch_exists and not args.reuse_branch:
        return fail(
            "BRANCH_EXISTS",
            f"本地分支 {args.branch} 已存在（commit {branch_sha[:12]}）",
            "若为上次创建中断的残留（目录已被回滚）：加 --reuse-branch 复用该分支继续创建 worktree；"
            "若想全新开始：先 `git branch -D` 删除后重试",
        )
    if not branch_exists and args.reuse_branch:
        return fail("BRANCH_NOT_FOUND",
                    f"--reuse-branch 指定但本地分支 {args.branch} 不存在",
                    "去掉 --reuse-branch 直接新建，或检查分支名拼写")

    # --- 5. 可选 fetch（失败仅告警，降级本地引用） ---
    fetch_note = "skipped（默认用本地引用；需要最新代码时加 --fetch）"
    if args.fetch:
        if args.base.startswith("refs/remotes/") or "/" in args.base:
            remote, _, ref = args.base.partition("/")
            if remote and ref:
                log(f"fetch {remote} {ref}（网络受限时可能较慢）…")
                rc, _, err = run_git(["fetch", remote, ref], cwd=toplevel)
                fetch_note = "ok" if rc == 0 else f"failed（降级使用本地引用：{err.splitlines()[0] if err else '未知错误'}）"
                if rc != 0:
                    log(f"警告: fetch 失败，将使用本地已有引用 {args.base}")
        else:
            fetch_note = "skipped（base 不是远程跟踪分支）"

    # --- 6. 解析基分支 ---
    rc, base_commit, err = run_git(["rev-parse", "--verify", f"{args.base}^{{commit}}"], cwd=toplevel)
    if rc != 0:
        return fail("BASE_NOT_FOUND", f"基分支不存在或无法解析：{args.base}",
                    "用 `git branch -r` 查看可用远程分支；注意前缀 origin/")
    log(f"基分支 {args.base} → {base_commit[:12]}")

    # --- 7. dry-run 输出计划 ---
    plan = {
        "repo": toplevel,
        "worktree_path": worktree_path,
        "worktree_path_windows": win_path,
        "worktree_name": worktree_name,
        "branch": args.branch,
        "base": args.base,
        "base_commit": base_commit,
        "mode": "reuse-branch" if (branch_exists and args.reuse_branch) else "new-branch",
        "fetch": fetch_note,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps({"status": "ok", "data": {"dry_run": True, "plan": plan}},
                         ensure_ascii=False, indent=2))
        return 0

    # --- 8. 执行创建 ---
    if branch_exists and args.reuse_branch:
        cmd = ["worktree", "add", worktree_path, args.branch]
    else:
        cmd = ["worktree", "add", worktree_path, "-b", args.branch, args.base]
    log(f"执行: git {' '.join(cmd)}")
    rc, out, err = run_git(cmd, cwd=toplevel)
    if rc != 0:
        return fail("WORKTREE_ADD_FAILED", f"git worktree add 失败：{err or out}",
                    "常见原因：检出被中断（重跑本命令，分支残留时加 --reuse-branch）、磁盘空间不足、路径权限")

    plan["dry_run"] = False
    print(json.dumps({"status": "ok", "data": {"created": True, "plan": plan,
                                               "git_output_last_line": out.splitlines()[-1] if out else ""}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
