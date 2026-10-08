#!/usr/bin/env python3
"""test_worktree_create.py — worktree_create.py 单元/集成测试（unittest，纯标准库）。

通过在临时目录搭建 bare 远程 + clone 主仓库，端到端验证脚本三路径：
正常（创建/dry-run/复用分支）、边界（命名转换）、错误（前置守卫）。

用法: python3 -m unittest discover -s tests -v   （在 skill 目录下执行）
依赖: git ≥2.20；Python 3.9+。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "worktree_create.py"


def sh(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


class WorktreeTestBase(unittest.TestCase):
    """搭建 bare 远程 + 主仓库 clone（含 origin/dev/v6.0.8.1 引用）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        self.repo = root / "main"
        sh(["git", "init", "--bare", "-b", "main", str(self.origin)])
        sh(["git", "clone", str(self.origin), str(self.repo)])
        cfg = [["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"]]
        for c in cfg:
            sh(c, cwd=str(self.repo))
        (self.repo / "f.txt").write_text("hello")
        sh(["git", "add", "."], cwd=str(self.repo))
        sh(["git", "commit", "-m", "init"], cwd=str(self.repo))
        sh(["git", "push", "origin", "main:dev/v6.0.8.1"], cwd=str(self.repo))
        sh(["git", "fetch", "origin"], cwd=str(self.repo))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, *extra: str) -> tuple[int, dict | None]:
        """执行脚本，返回 (退出码, stdout 解析出的 JSON 或 None)。"""
        proc = sh([sys.executable, str(SCRIPT), *extra], cwd=str(self.repo))
        try:
            return proc.returncode, json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.returncode, None

    def create_ok(self) -> dict:
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/zly-demo-20261008")
        self.assertEqual(rc, 0, proc_out(out))
        self.assertEqual(out["status"], "ok")
        return out["data"]["plan"]


def proc_out(out) -> str:
    return json.dumps(out, ensure_ascii=False) if out else ""


class TestHappyPath(WorktreeTestBase):
    def test_create_success_and_naming(self):
        """正常路径：创建成功，目录在同级且 '/' 已换 '_'。"""
        plan = self.create_ok()
        expected = self.repo.parent / "v6.0.8.1_feature_zly-demo-20261008"
        self.assertEqual(Path(plan["worktree_path"]), expected)
        self.assertTrue(expected.is_dir())
        self.assertTrue((expected / "f.txt").exists())  # 检出了基分支内容
        listing = sh(["git", "worktree", "list"], cwd=str(self.repo)).stdout
        self.assertIn("v6.0.8.1_feature_zly-demo-20261008", listing)

    def test_dry_run_creates_nothing(self):
        """dry-run：只输出计划，不建目录不建分支。"""
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/x-1",
                                  "--dry-run")
        self.assertEqual(rc, 0)
        self.assertTrue(out["data"]["dry_run"])
        self.assertFalse((self.repo.parent / "v6.0.8.1_feature_x-1").exists())
        branches = sh(["git", "branch", "--list", "v6.0.8.1/feature/x-1"],
                      cwd=str(self.repo)).stdout
        self.assertEqual(branches.strip(), "")

    def test_reuse_branch_after_interrupt(self):
        """中断恢复：分支残留 + 目录回滚 → --reuse-branch 复用成功。"""
        sh(["git", "branch", "v6.0.8.1/feature/r-1", "origin/dev/v6.0.8.1"],
           cwd=str(self.repo))  # 模拟中断残留分支
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/r-1",
                                  "--reuse-branch")
        self.assertEqual(rc, 0, proc_out(out))
        self.assertEqual(out["data"]["plan"]["mode"], "reuse-branch")
        self.assertTrue((self.repo.parent / "v6.0.8.1_feature_r-1").is_dir())


class TestGuards(WorktreeTestBase):
    def test_base_not_found(self):
        rc, out = self.run_script("--base", "origin/no-such", "--branch", "a/b")
        self.assertEqual(rc, 2)
        self.assertEqual(out["error"]["error_code"], "BASE_NOT_FOUND")

    def test_path_exists(self):
        target = self.repo.parent / "v6.0.8.1_feature_e-1"
        target.mkdir()
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/e-1")
        self.assertEqual(rc, 2)
        self.assertEqual(out["error"]["error_code"], "PATH_EXISTS")

    def test_branch_exists_without_reuse(self):
        sh(["git", "branch", "v6.0.8.1/feature/b-1", "origin/dev/v6.0.8.1"],
           cwd=str(self.repo))
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/b-1")
        self.assertEqual(rc, 2)
        self.assertEqual(out["error"]["error_code"], "BRANCH_EXISTS")

    def test_branch_checked_out_elsewhere(self):
        self.create_ok()
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/zly-demo-20261008")
        self.assertEqual(rc, 2)  # 目录已存在优先触发 PATH_EXISTS 或分支占用
        self.assertIn(out["error"]["error_code"],
                      ("PATH_EXISTS", "BRANCH_CHECKED_OUT"))

    def test_invalid_branch_names(self):
        # 等号传参避免 argparse 把 "-lead" 误认为选项
        for bad_name in ("", "a..b", "-lead", "a b", "a//b", "a*b", "a~b", "a^b", "a[b", "a.lock", "trailing/"):
            rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                      f"--branch={bad_name}")
            self.assertEqual(rc, 2, bad_name)
            self.assertEqual(out["error"]["error_code"], "INVALID_BRANCH_NAME", bad_name)

    def test_not_a_git_repo(self):
        rc, out = self.run_script("--repo", self.tmp.name, "--base", "origin/x",
                                  "--branch", "a/b")
        self.assertEqual(rc, 2)
        self.assertEqual(out["error"]["error_code"], "NOT_A_GIT_REPO")

    def test_reuse_branch_missing(self):
        rc, out = self.run_script("--base", "origin/dev/v6.0.8.1",
                                  "--branch", "v6.0.8.1/feature/none-1",
                                  "--reuse-branch")
        self.assertEqual(rc, 2)
        self.assertEqual(out["error"]["error_code"], "BRANCH_NOT_FOUND")


class TestUtils(unittest.TestCase):
    """纯函数单测：路径转换与分支名校验。"""

    @classmethod
    def setUpClass(cls):
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location("wtc", SCRIPT)
        cls.mod = module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_to_windows_path(self):
        self.assertEqual(self.mod.to_windows_path("/mnt/d/a/b"), "D:\\a\\b")
        self.assertEqual(self.mod.to_windows_path("/mnt/c/x"), "C:\\x")
        self.assertIsNone(self.mod.to_windows_path("/home/u/x"))  # 非 WSL 挂载
        self.assertIsNone(self.mod.to_windows_path("D:\\already"))

    def test_validate_branch_name(self):
        # 合法名（含 / 分隔的多级）返回 None
        for ok in ("v6.0.8.1/feature/zly-sharelease-20261008",
                   "bugfix/75339_20261008", "main", "中文分支/主题"):
            self.assertIsNone(self.mod.validate_branch_name(ok), ok)
        # 非法名返回原因字符串
        for bad in ("", "a..b", "-lead", ".hidden", "a b", "a//b", "a*b",
                    "a?b", "a:b", "a[b", "a]b", "a~b", "a^b", "a\\b",
                    "a.lock", "trailing/", "end."):
            self.assertIsInstance(self.mod.validate_branch_name(bad), str, bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
