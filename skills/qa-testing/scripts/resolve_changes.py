#!/usr/bin/env python3
"""resolve_changes.py — 只读解析 Git 仓库被测分支相对基线的变更清单。

用途: qa-testing 工作流 B 第①步。只读查询，不 checkout、不 fetch、不改工作树。
用法:
  uv run scripts/resolve_changes.py --repo <仓库路径> --branch <被测分支> [--base <基线引用>] --json
  python3 scripts/resolve_changes.py ...  (无 uv 时直跑，仅标准库)
参数:
  --repo   被测仓库路径（必需）
  --branch 被测分支名，本地分支或 origin/<name>（必需）
  --base   基线引用（可选）；缺省时依次探测 origin/develop, origin/master, origin/main, origin/release
  --json   输出 JSON（默认开启，保留参数以显式声明）
输出:
  stdout JSON: {"status":"ok","data":{repo,branch,base,merge_base,head,commits[],files[],summary{}}}
  错误时: {"status":"error","error":{"code","message","hint"}}，日志走 stderr
退出码: 0=成功; 2=输入错误(非 git 仓库/分支不存在); 3=基线无法确定
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE_CANDIDATES = ["origin/develop", "origin/master", "origin/main", "origin/release"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """以禁用可选锁的只读方式执行 git 命令。"""
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=check,
    )


def fail(code: int, message: str, hint: str) -> int:
    print(json.dumps({"status": "error", "error": {"code": code, "message": message, "hint": hint}},
                     ensure_ascii=False))
    return code


def resolve_branch(repo: Path, branch: str) -> str | None:
    """把分支名解析到 commit；本地分支优先，其次 origin/<branch>。找不到返回 None。"""
    for ref in (branch, f"origin/{branch}", f"refs/heads/{branch}"):
        r = run_git(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def detect_base(repo: Path, explicit: str | None, head: str) -> tuple[str | None, str | None]:
    """返回 (基线引用, merge_base commit)；无法确定时 (None, None)。"""
    if explicit:
        r = run_git(repo, ["rev-parse", "--verify", "--quiet", f"{explicit}^{{commit}}"], check=False)
        if r.returncode != 0:
            return None, None
        m = run_git(repo, ["merge-base", r.stdout.strip(), head], check=False)
        return (explicit, m.stdout.strip()) if m.returncode == 0 and m.stdout.strip() else (None, None)
    for cand in DEFAULT_BASE_CANDIDATES:
        r = run_git(repo, ["rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}"], check=False)
        if r.returncode == 0:
            m = run_git(repo, ["merge-base", r.stdout.strip(), head], check=False)
            if m.returncode == 0 and m.stdout.strip():
                return cand, m.stdout.strip()
    return None, None


def collect_commits(repo: Path, base_commit: str, head: str) -> list[dict]:
    r = run_git(repo, ["log", "--format=%H\x1f%h\x1f%s\x1f%an\x1f%ad", "--date=short",
                       f"{base_commit}..{head}"])
    commits = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        commits.append({"hash": parts[0], "short": parts[1], "subject": parts[2],
                        "author": parts[3], "date": parts[4] if len(parts) > 4 else ""})
    return commits


def collect_files(repo: Path, base_commit: str, head: str) -> tuple[list[dict], int, int]:
    r = run_git(repo, ["diff", "--numstat", base_commit, head])
    files, ins, del_ = [], 0, 0
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], "\t".join(parts[2:])
        binary = added == "-" and deleted == "-"
        files.append({"path": path, "binary": binary,
                      "insertions": 0 if binary else int(added),
                      "deletions": 0 if binary else int(deleted)})
        if not binary:
            ins += int(added)
            del_ += int(deleted)
    return files, ins, del_


def main() -> int:
    ap = argparse.ArgumentParser(description="只读解析被测分支相对基线的变更清单（JSON 输出）")
    ap.add_argument("--repo", required=True, help="被测仓库路径")
    ap.add_argument("--branch", required=True, help="被测分支名（本地或 origin/<name>）")
    ap.add_argument("--base", default=None, help="基线引用；缺省自动探测 origin 主干")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认行为）")
    args = ap.parse_args()

    repo = Path(args.repo).absolute()
    if not (repo / ".git").exists() and not (repo.is_dir()):
        return fail(2, f"仓库路径不存在或不是 git 仓库: {repo}",
                    "确认 --repo 指向包含 .git 的目录；黑盒目录不适用本脚本")
    v = run_git(repo, ["rev-parse", "--is-inside-work-tree"], check=False)
    if v.returncode != 0 or v.stdout.strip() != "true":
        return fail(2, f"路径不是可用的 git 工作树: {repo}",
                    "确认该目录已 git init/clone；本脚本不支持裸仓库之外的普通目录")

    head = resolve_branch(repo, args.branch)
    if head is None:
        return fail(2, f"被测分支不存在或无法解析: {args.branch}",
                    "确认本地或 origin/<分支> 存在（git branch -a 核对）；脚本只读解析，不 fetch")

    base_ref, base_commit = detect_base(repo, args.base, head)
    if base_commit is None:
        return fail(3, f"基线{' ' + args.base if args.base else ''}无法确定或解析失败",
                    "用 --base 显式指定基线引用；或核对 origin 主干分支是否存在（不 fetch）")

    commits = collect_commits(repo, base_commit, head)
    files, ins, dels = collect_files(repo, base_commit, head)
    data = {
        "repo": str(repo),
        "branch": args.branch,
        "base": base_ref,
        "merge_base": base_commit,
        "head": head,
        "commits": commits,
        "files": files,
        "summary": {"commit_count": len(commits), "file_count": len(files),
                    "insertions": ins, "deletions": dels},
    }
    print(json.dumps({"status": "ok", "data": data}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
