#!/usr/bin/env python3
"""collect_commits.py — 收集 Git 仓库中当前用户的近期提交与未提交修改，供周报整理使用。

用途:
  扫描仓库所有 worktree 的 HEAD 分支与关键远程分支(origin/release*、origin/dev*)，
  按作者与工作日窗口收集提交(按哈希去重)，并收集各 worktree 的未提交修改，
  输出结构化 JSON 供 AI 整理周报。

依赖: Python 3.9+ 纯标准库；本机需安装 git 并在 PATH 中。
用法:
  python3 collect_commits.py [--repo <仓库路径>] [--workdays 5]
                             [--since YYYY-MM-DD] [--author <email>]
                             [--json-out <文件路径>]
  退出码: 0=成功 1=运行错误 2=参数/前置校验失败
说明:
  - 工作日窗口: 最近 N 个工作日(周一至周五，跳过周六日)，
    窗口 = 其中最早一天 00:00 至当前时刻，中间的日历日(周末)提交也计入
  - 用户显式提供 --since 日期时优先于工作日窗口
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

UNIT = "\x1f"  # 字段分隔符
REC = "\x1e"   # 记录分隔符
SHORTSTAT_RE = re.compile(
    r"(?P<files>\d+) files? changed"
    r"(?:,\s*(?P<ins>\d+) insertions?\(\+\))?"
    r"(?:,\s*(?P<del>\d+) deletions?\(-\))?"
)
BUG_RE = re.compile(r"#(\d+)")


class CollectError(Exception):
    """可预期的收集失败（消息含问题+原因+行动）。"""


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def run_git(repo: Path, args: list[str], check: bool = True,
            timeout: float | None = None) -> str:
    if not shutil.which("git"):
        raise CollectError("git 不可用：PATH 中找不到 git；请安装 git 后重试")
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo)] + args,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CollectError(
            f"git {' '.join(args[:2])}... 超时({timeout}s)；"
            "请稍后重试或加大超时")
    if check and proc.returncode != 0:
        raise CollectError(
            f"git {' '.join(args)} 失败(退出码 {proc.returncode})："
            f"{proc.stderr.strip() or proc.stdout.strip()}；请确认路径是 git 仓库且权限正常"
        )
    return proc.stdout


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="收集周报所需的提交与未提交修改(JSON)")
    ap.add_argument("--repo", default=".", help="仓库路径(默认当前目录)")
    ap.add_argument("--workdays", type=int, default=5,
                    help="工作日窗口大小(默认 5 个工作日，跳过周六日)")
    ap.add_argument("--since", default=None,
                    help="显式开始日期 YYYY-MM-DD；提供时优先于工作日窗口")
    ap.add_argument("--author", default=None,
                    help="作者邮箱(默认取仓库 user.email；传 all 不过滤)")
    ap.add_argument("--json-out", default=None,
                    help="额外将 JSON 写入该文件路径")
    ap.add_argument("--status-timeout", type=float, default=45.0,
                    help="单 worktree 未提交扫描超时秒数(默认 45，超时自动降级)")
    return ap.parse_args()


def workday_window(n: int, today: date | None = None) -> tuple[datetime, datetime, list[date]]:
    """最近 n 个工作日窗口：返回 (起始 00:00, 当前时刻, 工作日列表[新→旧])。"""
    if n <= 0:
        raise CollectError(f"workdays 必须为正整数，收到 {n}；请传 --workdays >=1")
    today = today or date.today()
    days: list[date] = []
    cur = today
    while len(days) < n:
        if cur.weekday() < 5:  # 0=周一 ... 4=周五
            days.append(cur)
        cur -= timedelta(days=1)
    start = datetime.combine(days[-1], time.min)
    return start, datetime.now(), days


def get_worktrees(repo: Path) -> list[dict]:
    out = run_git(repo, ["worktree", "list", "--porcelain"])
    trees: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):].strip(), "branch": None, "head": None}
            trees.append(cur)
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            cur["branch"] = ref.removeprefix("refs/heads/")
    return [t for t in trees if t.get("branch")]  # detached/bare 不作为提交来源 ref


def get_key_remote_branches(repo: Path) -> list[str]:
    out = run_git(repo, ["branch", "-r", "--format=%(refname:short)"])
    names = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return [n for n in names if n.startswith("origin/release") or n.startswith("origin/dev")]


def collect_commits(repo: Path, refs: list[dict], author: str,
                    start: datetime, end: datetime) -> dict[str, dict]:
    """按 ref 收集提交并按哈希去重；refs 元素: {"name", "kind", "worktree_path"?}。"""
    since, until = start.isoformat(), end.isoformat()
    commits: dict[str, dict] = {}
    for ref in refs:
        args = ["log", ref["name"]]
        if author and author != "all":  # all = 不过滤作者
            args.append(f"--author={author}")
        args += [f"--since={since}", f"--until={until}",
                 f"--pretty=format:%H{UNIT}%cI{UNIT}%s{UNIT}%b{UNIT}%P{REC}"]
        out = run_git(repo, args, check=False)
        for record in out.split(REC):
            record = record.strip("\n")
            if not record.strip():
                continue
            parts = record.split(UNIT)
            if len(parts) < 5:
                continue
            h, committed_at, subject, body, parents = (
                parts[0], parts[1], parts[2], parts[3], parts[4])
            if h not in commits:
                commits[h] = {
                    "hash": h, "date": committed_at, "subject": subject,
                    "body": body.strip(), "parents": parents.split() if parents else [],
                    "is_merge": bool(parents.strip()) and len(parents.split()) > 1,
                    "refs": [], "bug_ids": sorted(set(BUG_RE.findall(subject))),
                }
            if ref["name"] not in commits[h]["refs"]:
                commits[h]["refs"].append(ref["name"])
    return commits


def shortstat(repo: Path, h: str) -> tuple[int, int, int]:
    out = run_git(repo, ["show", "-s", "--shortstat", "--pretty=format:", h], check=False)
    m = SHORTSTAT_RE.search(out)
    if not m:
        return 0, 0, 0
    return (int(m.group("files")), int(m.group("ins") or 0), int(m.group("del") or 0))


def branch_window_sets(repo: Path, branches: list[str],
                       start: datetime, end: datetime) -> dict[str, set[str]]:
    """每个远程分支一次 rev-list，得到窗口内可达提交集合（替代逐提交 --contains）。"""
    result: dict[str, set[str]] = {}
    for b in branches:
        out = run_git(repo, ["rev-list", b,
                             f"--since={start.isoformat()}",
                             f"--until={end.isoformat()}"], check=False)
        result[b] = set(out.split())
    return result


def get_uncommitted(wt_path: str, timeout: float = 45.0) -> tuple[list[dict], str]:
    """两段降级：先含未跟踪全量扫描；超时则仅扫跟踪文件；再超时则放弃并标注。"""
    modes = (("--untracked-files=normal", ""),
             ("--untracked-files=no", "未跟踪文件未扫描(全量扫描超时降级)"))
    for uflag, note in modes:
        try:
            out = run_git(Path(wt_path), ["status", "--porcelain=v1", uflag],
                          check=False, timeout=timeout)
        except CollectError:
            continue
        items: list[dict] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            status, path = line[:2], line[3:].strip()
            if "->" in path:  # 重命名取新路径
                path = path.split("->", 1)[1].strip()
            items.append({"status": status.strip() or "?", "path": path})
        return items, note
    return [], "获取超时(两种模式均超时)，本次跳过该 worktree 未提交修改"


def sync_state(repo: Path, branch: str) -> dict:
    local = run_git(repo, ["rev-parse", "--verify", f"refs/heads/{branch}"], check=False).strip()
    remote = run_git(repo, ["rev-parse", "--verify",
                            f"refs/remotes/origin/{branch}"], check=False).strip()
    if not local:
        return {"remote_synced": None, "ahead": None, "behind": None, "note": "本地分支不存在"}
    if not remote:
        return {"remote_synced": None, "ahead": None, "behind": None,
                "note": f"origin/{branch} 不存在(未推送过)"}
    ahead = int(run_git(repo, ["rev-list", "--count", f"origin/{branch}..{branch}"]).strip() or 0)
    behind = int(run_git(repo, ["rev-list", "--count", f"{branch}..origin/{branch}"]).strip() or 0)
    return {"remote_synced": ahead == 0 and behind == 0,
            "ahead": ahead, "behind": behind, "note": ""}


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    try:
        if not repo.exists():
            print(json.dumps({"status": "error", "data": None,
                              "error": f"仓库路径不存在：{repo}；请传 --repo <有效路径>"},
                             ensure_ascii=False))
            return 2
        run_git(repo, ["rev-parse", "--git-dir"])  # 前置校验：是 git 仓库

        author = args.author
        if not author:
            author = run_git(repo, ["config", "user.email"]).strip()
            if not author:
                print(json.dumps({"status": "error", "data": None,
                                  "error": "未配置 user.email；请传 --author <邮箱> 或先 git config"},
                                 ensure_ascii=False))
                return 2

        if args.since:
            start = datetime.combine(date.fromisoformat(args.since), time.min)
            end, workdays = datetime.now(), []
            window_desc = f"显式日期 {args.since} 起"
        else:
            start, end, workdays = workday_window(args.workdays)
            window_desc = f"最近 {args.workdays} 个工作日"

        worktrees = get_worktrees(repo)
        if not worktrees:
            print(json.dumps({"status": "error", "data": None,
                              "error": "未发现带分支的 worktree；请确认仓库状态"},
                             ensure_ascii=False))
            return 2
        key_branches = get_key_remote_branches(repo)

        refs = [{"name": t["branch"], "kind": "worktree_head",
                 "worktree_path": t["path"]} for t in worktrees]
        refs += [{"name": b, "kind": "key_remote_branch"} for b in key_branches]
        commits = collect_commits(repo, refs, author, start, end)
        remote_sets = branch_window_sets(
            repo, key_branches, start, end)

        worktree_branches = {t["branch"]: t["path"] for t in worktrees}
        total_files = total_ins = total_del = 0
        commit_list: list[dict] = []
        for h, c in sorted(commits.items(), key=lambda kv: kv[1]["date"], reverse=True):
            c["pushed"] = False; c["in_dev"] = False; c["in_release"] = False
            c["files"] = c["insertions"] = c["deletions"] = None
            if not c["is_merge"]:
                c["files"], c["insertions"], c["deletions"] = shortstat(repo, h)
                total_files += c["files"]; total_ins += c["insertions"]; total_del += c["deletions"]
            containing = [b for b, s in remote_sets.items() if h in s]
            c["pushed"] = any(x.startswith("origin/") for x in containing)
            c["in_dev"] = any(x.startswith("origin/dev") for x in containing)
            c["in_release"] = any(x.startswith("origin/release") for x in containing)
            c["worktree_hint"] = next(
                (p for b, p in worktree_branches.items() if b in c["refs"]), None)
            commit_list.append(c)

        wt_infos = []
        uncommitted_total = 0
        for t in worktrees:
            uncommitted, unote = get_uncommitted(t["path"],
                                                 timeout=args.status_timeout)
            uncommitted_total += len(uncommitted)
            sync = sync_state(repo, t["branch"])
            wt_infos.append({**t, "uncommitted": uncommitted,
                             "uncommitted_count": len(uncommitted),
                             "uncommitted_note": unote, **sync})

        all_bugs = sorted({b for c in commit_list for b in c["bug_ids"]}, key=int)
        data = {
            "repo": str(repo), "author": author if author != "all" else "(全部作者)",
            "window": {"description": window_desc, "start": start.isoformat(),
                       "end": end.isoformat(),
                       "workdays": [d.isoformat() for d in workdays]},
            "worktrees": wt_infos,
            "key_branches_scanned": key_branches,
            "commits": commit_list,
            "stats": {"commit_total": len(commit_list),
                      "non_merge_total": sum(1 for c in commit_list if not c["is_merge"]),
                      "files_changed": total_files, "insertions": total_ins,
                      "deletions": total_del, "bug_ids": all_bugs,
                      "uncommitted_total": uncommitted_total},
        }
        payload = json.dumps({"status": "ok", "data": data, "error": None},
                             ensure_ascii=False, indent=2)
        print(payload)
        if args.json_out:
            try:
                out_path = Path(args.json_out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(payload, encoding="utf-8")
            except OSError as e:
                raise CollectError(
                    f"JSON 写入失败：{e}；请检查 --json-out 路径权限或更换路径")
            log(f"JSON 已写入 {args.json_out}")
        return 0
    except CollectError as e:
        print(json.dumps({"status": "error", "data": None, "error": str(e)},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
