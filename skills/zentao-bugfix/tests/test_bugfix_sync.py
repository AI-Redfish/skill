#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bugfix.py 远端基准分支同步（sync_base_branch / setup_worktree）单元测试。

用临时 bare 仓库模拟远端，验证正常/边界/错误三路径：
- 远端领先 → fetch+merge（fast-forward）成功，SYNCED=yes，基线提交更新
- 本地已最新 → Already up to date，SYNCED=yes
- 仓库无远程 / fetch 失败 → 降级本地快照，SYNCED=no + 原因
- 合并冲突 → 自动 git merge --abort，SystemExit(5)，worktree 保持干净
- --reuse 复用路径不触发同步；meta.json 记录同步状态

运行：python -m unittest discover -s tests -p "test_bugfix_sync.py" -v
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bugfix.py"
spec = importlib.util.spec_from_file_location("bugfix", SCRIPT)
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)


def git(*args, cwd=None):
    r = subprocess.run(["git"] + list(args), cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("git %s 失败: %s" % (args, r.stderr.strip()))
    return r.stdout


def _cfg(repo):
    git("config", "user.email", "t@t.local", cwd=repo)
    git("config", "user.name", "tester", cwd=repo)


def _commit(repo, fname, content, msg):
    (Path(repo) / fname).write_text(content, encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", msg, cwd=repo)


def make_fixtures(td, mode):
    """搭建 bare 远端 + 本地克隆。mode: sync（远端领先）/ conflict（双方分叉）/ fresh（无分叉）。"""
    td = Path(td)
    remote = td / "origin.git"
    git("init", "--bare", "-b", "main", str(remote))
    seed = td / "seed"
    git("clone", str(remote), str(seed))
    _cfg(seed)
    _commit(seed, "f.txt", "line1\n", "init")
    git("push", "origin", "main", cwd=seed)

    local = td / "proj"
    git("clone", str(remote), str(local))
    _cfg(local)
    if mode == "sync":                       # 远端领先：seed 新增提交并推送
        _commit(seed, "g.txt", "from remote\n", "remote ahead")
        git("push", "origin", "main", cwd=seed)
    elif mode == "conflict":                 # 双方分叉：同一行各自修改
        _commit(seed, "f.txt", "remote line\n", "remote change")
        git("push", "origin", "main", cwd=seed)
        _commit(local, "f.txt", "local line\n", "local change")
    return remote, local, seed


def make_lone_repo(td):
    """无远程的本地仓库。"""
    td = Path(td)
    repo = td / "solo"
    git("init", "-b", "main", str(repo))
    _cfg(repo)
    _commit(repo, "a.txt", "a\n", "init")
    return repo


class TestSyncNewWorktree(unittest.TestCase):
    def test_remote_ahead_fast_forward(self):
        with tempfile.TemporaryDirectory() as td:
            remote, local, seed = make_fixtures(td, "sync")
            info = bf.setup_worktree(str(local), "111", "main")
            self.assertTrue(info["synced"])
            self.assertEqual(info["sync_remote_branch"], "origin/main")
            tip_full = git("rev-parse", "HEAD", cwd=seed).strip()   # 远端真实 tip（全 hash）
            wt_full = git("rev-parse", "HEAD", cwd=info["wt_path"]).strip()
            self.assertEqual(wt_full, tip_full)                    # 基线更新为远端最新
            self.assertTrue(tip_full.startswith(info["head_short"]))
            self.assertTrue((Path(info["wt_path"]) / "g.txt").exists())  # 远端新文件已合并
            # 本地基准分支引用未被改动、主工作空间无 g.txt
            self.assertFalse((Path(local) / "g.txt").exists())
            # meta.json 记录同步状态
            meta = json.loads(Path(info["report_dir"], "meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["synced"])
            self.assertEqual(meta["sync_remote_branch"], "origin/main")

    def test_already_up_to_date(self):
        with tempfile.TemporaryDirectory() as td:
            _, local, _seed = make_fixtures(td, "fresh")
            info = bf.setup_worktree(str(local), "112", "main")
            self.assertTrue(info["synced"])
            self.assertIn("无新提交", info["sync_reason"])

    def test_degrade_no_remote(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_lone_repo(td)
            info = bf.setup_worktree(str(repo), "113", "main")
            self.assertFalse(info["synced"])
            self.assertIn("未配置远程", info["sync_reason"])
            meta = json.loads(Path(info["report_dir"], "meta.json").read_text(encoding="utf-8"))
            self.assertFalse(meta["synced"])

    def test_degrade_fetch_failure(self):
        with tempfile.TemporaryDirectory() as td:
            remote, local, _seed = make_fixtures(td, "fresh")
            git("remote", "set-url", "origin", str(Path(td) / "not-exist.git"), cwd=local)
            info = bf.setup_worktree(str(local), "114", "main")
            self.assertFalse(info["synced"])
            self.assertIn("fetch", info["sync_reason"])
            # 降级后 worktree 仍基于本地快照可用（仅 .agents 报告目录为未跟踪新增）
            tracked = [l for l in git("status", "--porcelain",
                                      cwd=info["wt_path"]).splitlines()
                       if not l.startswith("?? .agents")]
            self.assertEqual(tracked, [])

    def test_degrade_detached_base(self):
        with tempfile.TemporaryDirectory() as td:
            _, local, _seed = make_fixtures(td, "fresh")
            with mock.patch.object(bf, "worktree_info") as wi:   # 直接构造 base=HEAD 的 info
                wi.return_value = {
                    "repo_root": str(local), "parent_dir": str(td),
                    "base_branch": "HEAD", "cur_branch": "", "head_short": "abc1234",
                    "date": "20260101", "branch": "bugfix/115_20260101",
                    "dir_name": "bugfix_115_20260101",
                    "wt_path": str(Path(td) / "bugfix_115_20260101"),
                    "report_dir": str(Path(td) / "bugfix_115_20260101" / ".agents" / "bugfix" / "115"),
                }
                info = bf.setup_worktree(str(local), "115")
            self.assertFalse(info["synced"])
            self.assertIn("基准不是分支", info["sync_reason"])


class TestSyncConflict(unittest.TestCase):
    def test_conflict_aborts_and_exits_5(self):
        with tempfile.TemporaryDirectory() as td:
            remote, local, _seed = make_fixtures(td, "conflict")
            pre = bf.worktree_info(str(local), "333", "main")
            buf = io.StringIO()
            with self.assertRaises(SystemExit) as cm, \
                    contextlib.redirect_stdout(buf):
                bf.setup_worktree(str(local), "333", "main")
            self.assertEqual(cm.exception.code, 5)
            out = buf.getvalue()
            self.assertIn("SYNC_CONFLICT", out)
            self.assertIn("REMOTE_BRANCH=origin/main", out)
            self.assertIn("MERGE_ABORTED=yes", out)
            # worktree 保留且干净：无冲突标记、无 MERGE_HEAD、状态为空
            wt = Path(pre["wt_path"])
            self.assertTrue(wt.is_dir())
            self.assertEqual(git("status", "--porcelain", cwd=wt), "")
            self.assertEqual((wt / "f.txt").read_text(encoding="utf-8"), "local line\n")
            # 本地基准分支未被改动
            self.assertEqual((Path(local) / "f.txt").read_text(encoding="utf-8"),
                             "local line\n")


class TestReuseNoSync(unittest.TestCase):
    def test_reuse_does_not_sync(self):
        with tempfile.TemporaryDirectory() as td:
            remote, local, _seed = make_fixtures(td, "sync")
            first = bf.setup_worktree(str(local), "444", "main")
            with mock.patch.object(bf, "sync_base_branch",
                                   side_effect=AssertionError("reuse 不应同步")) as s:
                bf.setup_worktree(str(local), "444",
                                  reuse_target=(first["wt_path"], first["branch"]))
            s.assert_not_called()
            info2 = bf.setup_worktree(str(local), "444",
                                      reuse_target=(first["wt_path"], first["branch"]))
            self.assertTrue(info2["reused"])
            # print_kv 在复用时不输出 SYNCED（避免误读为“刚同步过”；历史状态仅进报告）
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                bf.print_kv(info2)
            self.assertIn("REUSED=yes", buf.getvalue())
            self.assertNotIn("SYNCED=", buf.getvalue())


class TestSyncStatusText(unittest.TestCase):
    def test_render(self):
        self.assertIn("已同步远端 `origin/main`", bf.sync_status_text(
            {"synced": True, "sync_remote_branch": "origin/main", "head_short": "abc1234"}))
        self.assertIn("未同步远端", bf.sync_status_text(
            {"synced": False, "sync_reason": "仓库未配置远程"}))
        self.assertIn("未记录", bf.sync_status_text({}))


if __name__ == "__main__":
    unittest.main()
