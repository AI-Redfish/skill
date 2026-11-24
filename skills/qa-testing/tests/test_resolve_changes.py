#!/usr/bin/env python3
"""test_resolve_changes.py — resolve_changes.py 单元测试（unittest，纯标准库）。

运行: python -m unittest discover -s tests -v   （在 skill 目录或任意目录均可）
覆盖: 正常解析 / 无差异 / 显式基线 / 不存在分支 / 非 git 目录 / 二进制文件。
测试自建临时 git 仓库，不依赖外部环境，只读被测脚本输出做断言。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resolve_changes.py"


def sh(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def run_script(*args: str) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        payload = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        payload = {}
    return r.returncode, payload


def make_repo(base: Path) -> Path:
    """建一个带 master+feature 的临时仓库：base 提交 1 个文件，feature 追加 1 次提交改 1 文件+增 1 文件。"""
    repo = base / "repo"
    repo.mkdir()
    sh("git", "init", "-b", "master", cwd=repo)
    sh("git", "config", "user.email", "t@example.com", cwd=repo)
    sh("git", "config", "user.name", "tester", cwd=repo)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-m", "base commit", cwd=repo)
    sh("git", "push", "--quiet", cwd=repo) if False else None  # 无 remote；基线探测用显式 --base
    sh("git", "checkout", "-b", "feature", cwd=repo)
    (repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    (repo / "b.txt").write_text("new file\n", encoding="utf-8")
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-m", "feature change", cwd=repo)
    return repo


class TestResolveChanges(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="qa-testing-test-")
        self.repo = make_repo(Path(self.tmp))

    def test_ok_basic_explicit_base(self) -> None:
        """正常路径：显式基线 master，解析 feature 变更。"""
        code, payload = run_script("--repo", str(self.repo), "--branch", "feature", "--base", "master")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "ok")
        data = payload["data"]
        self.assertEqual(data["branch"], "feature")
        self.assertEqual(data["base"], "master")
        self.assertEqual(data["summary"]["commit_count"], 1)
        self.assertEqual(data["summary"]["file_count"], 2)
        self.assertEqual(data["summary"]["insertions"], 2)
        self.assertEqual(data["commits"][0]["subject"], "feature change")
        paths = {f["path"] for f in data["files"]}
        self.assertEqual(paths, {"a.txt", "b.txt"})

    def test_ok_no_diff(self) -> None:
        """边界：被测分支与基线无差异 → 0 commits 0 files，仍为 ok。"""
        code, payload = run_script("--repo", str(self.repo), "--branch", "master", "--base", "master")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["data"]["summary"]["commit_count"], 0)
        self.assertEqual(payload["data"]["summary"]["file_count"], 0)

    def test_ok_binary_file(self) -> None:
        """边界：二进制变更文件 → binary=true，行数不计入统计。"""
        (self.repo / "logo.bin").write_bytes(b"\x00\x01\x02")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-m", "add binary", cwd=self.repo)
        code, payload = run_script("--repo", str(self.repo), "--branch", "feature", "--base", "master")
        self.assertEqual(code, 0, payload)
        bin_files = [f for f in payload["data"]["files"] if f["binary"]]
        self.assertEqual(len(bin_files), 1)
        self.assertEqual(bin_files[0]["path"], "logo.bin")

    def test_err_branch_not_exist(self) -> None:
        """错误路径：分支不存在 → 退出码 2 + error 结构含 hint。"""
        code, payload = run_script("--repo", str(self.repo), "--branch", "no-such-branch", "--base", "master")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "error")
        self.assertTrue(payload["error"]["hint"])

    def test_err_not_git_dir(self) -> None:
        """错误路径：非 git 目录 → 退出码 2。"""
        plain = Path(self.tmp) / "plain"
        plain.mkdir()
        code, payload = run_script("--repo", str(plain), "--branch", "feature")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "error")

    def test_err_base_unresolvable(self) -> None:
        """错误路径：显式基线不存在 → 退出码 3。"""
        code, payload = run_script("--repo", str(self.repo), "--branch", "feature", "--base", "origin/nope")
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "error")

    def test_readonly_no_checkout(self) -> None:
        """只读守卫：解析后当前分支不变（仍在 feature），无未提交改动引入。"""
        before = sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo).stdout.strip()
        run_script("--repo", str(self.repo), "--branch", "feature", "--base", "master")
        after = sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo).stdout.strip()
        status = sh("git", "status", "--porcelain", cwd=self.repo).stdout.strip()
        self.assertEqual(before, after)
        self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
