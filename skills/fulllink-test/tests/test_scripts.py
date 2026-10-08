#!/usr/bin/env python3
"""test_scripts.py — fulllink-test 脚本单测（unittest，纯标准库）。

运行: cd <skill_dir> && python3 -m unittest discover -s tests -v
覆盖: resolve_workspace 的项目名提取/防路径穿越/env 文件解析；
      workspace_check 的结构校验/密钥扫描/降级提示。
"""
from __future__ import annotations
import importlib.util
import json
import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


resolve_ws = load_module("resolve_workspace")
ws_check = load_module("workspace_check")


class TestExtractProjectName(unittest.TestCase):
    def test_https_with_git(self):
        self.assertEqual(resolve_ws.extract_project_name(
            "https://gitlab.example.com/group/basic-platform-service.git"),
            "basic-platform-service")

    def test_ssh_colon_form(self):
        self.assertEqual(resolve_ws.extract_project_name(
            "git@gitlab.example.com:group/bps-web.git"), "bps-web")

    def test_ssh_protocol_form(self):
        self.assertEqual(resolve_ws.extract_project_name(
            "ssh://git@gitlab.example.com:2222/group/svc.git"), "svc")

    def test_trailing_slash(self):
        self.assertEqual(resolve_ws.extract_project_name(
            "https://host/group/repo/"), "repo")

    def test_local_path(self):
        self.assertEqual(resolve_ws.extract_project_name("/d/x/y/repo"), "repo")


class TestSanitizeName(unittest.TestCase):
    def test_rejects_traversal(self):
        with self.assertRaises(RuntimeError):
            resolve_ws.sanitize_name("..")

    def test_rejects_slash(self):
        with self.assertRaises(RuntimeError):
            resolve_ws.sanitize_name("a/b")

    def test_accepts_normal(self):
        self.assertEqual(resolve_ws.sanitize_name("bps-web.v6.1"), "bps-web.v6.1")


class TestEnvFile(unittest.TestCase):
    def test_reads_quoted_value(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".agents"))
            with open(os.path.join(td, ".agents", ".env"), "w", encoding="utf-8") as f:
                f.write("# comment\nFULLLINK_TESTSPACES_ROOT=\"D:/x y\"\nOTHER=1\n")
            self.assertEqual(
                resolve_ws.load_env_file_value(td, "FULLLINK_TESTSPACES_ROOT"), "D:/x y")

    def test_missing_file_returns_none(self):
        self.assertIsNone(resolve_ws.load_env_file_value("/nonexistent", "K"))


class TestResolveRoot(unittest.TestCase):
    def test_arg_root_wins(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".agents"))
            with open(os.path.join(td, ".agents", ".env"), "w", encoding="utf-8") as f:
                f.write('FULLLINK_TESTSPACES_ROOT="D:/old"\n')
            root, source = resolve_ws.resolve_root("D:/new", td)
            self.assertEqual((root, source), (os.path.abspath("D:/new"), "arg"))

    def test_env_file_used_when_no_arg(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".agents"))
            with open(os.path.join(td, ".agents", ".env"), "w", encoding="utf-8") as f:
                f.write('FULLLINK_TESTSPACES_ROOT="D:/old"\n')
            self.assertEqual(resolve_ws.resolve_root(None, td), ("D:/old", "env-file"))

    def test_none_when_unconfigured(self):
        self.assertIsNone(resolve_ws.resolve_root(None, "/nonexistent-dir"))

    def test_recommend_root_returns_abs(self):
        root = resolve_ws.recommend_root()
        self.assertTrue(root and os.path.isabs(root))


class TestSaveEnvFile(unittest.TestCase):
    def test_save_then_reload_and_replace(self):
        with tempfile.TemporaryDirectory() as td:
            path = resolve_ws.save_env_file_value(td, "FULLLINK_TESTSPACES_ROOT", "D:/a b")
            self.assertEqual(
                resolve_ws.load_env_file_value(td, "FULLLINK_TESTSPACES_ROOT"), "D:/a b")
            resolve_ws.save_env_file_value(td, "FULLLINK_TESTSPACES_ROOT", "D:/c")
            self.assertEqual(
                resolve_ws.load_env_file_value(td, "FULLLINK_TESTSPACES_ROOT"), "D:/c")
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content.count("FULLLINK_TESTSPACES_ROOT"), 1)


class TestFindWorkspaceUp(unittest.TestCase):
    def _mk(self, files: dict, dirs: list) -> str:
        td = tempfile.mkdtemp(prefix="findws_")
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        for rel, content in files.items():
            p = os.path.join(td, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        for rel in dirs:
            os.makedirs(os.path.join(td, rel), exist_ok=True)
        return td

    def test_locates_parent_space_from_repo(self):
        td = self._mk({"proj/workspace.yaml": "project: proj\n"},
                      ["proj/svc/sub/deep"])
        ws = resolve_ws.find_workspace_up(os.path.join(td, "proj", "svc"))
        self.assertEqual(ws, os.path.join(td, "proj"))

    def test_locates_from_nested_subdir(self):
        td = self._mk({"proj/workspace.yaml": "project: proj\n"},
                      ["proj/svc/src/main"])
        ws = resolve_ws.find_workspace_up(os.path.join(td, "proj", "svc", "src", "main"))
        self.assertEqual(ws, os.path.join(td, "proj"))

    def test_none_outside(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(resolve_ws.find_workspace_up(td))


class TestWorkspaceCheck(unittest.TestCase):
    def _make_ws(self, files: dict) -> str:
        td = tempfile.mkdtemp(prefix="wscheck_")
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        for rel, content in files.items():
            p = os.path.join(td, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        return td

    def _by_id(self, checks, cid):
        return next(c for c in checks if c["id"] == cid)

    def test_good_workspace(self):
        ws = self._make_ws({
            "workspace.yaml": "project: demo\nkind: backend\nrepo: https://h/g/demo.git\n",
            "docs/02-feature-map.md": "| a | b |\n",
            "docs/04-env-matrix.md": "| e |\n",
            "assets/common/env.json": json.dumps(
                {"activeEnv": "t", "envs": {"t": {"db": {"host": "1"}}}}),
        })
        checks = ws_check.run_checks(ws)
        errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
        self.assertEqual(errors, [], f"不应有 error：{errors}")

    def test_repos_key_satisfies_w1(self):
        ws = self._make_ws({
            "workspace.yaml": "project: demo\nkind: multi\nrepos:\n  svc:\n    url: x\n",
            "assets/common/env.json": json.dumps({"activeEnv": "t", "envs": {"t": {}}})})
        self.assertTrue(self._by_id(ws_check.run_checks(ws), "W1")["ok"])

    def test_w6_unregistered_git_repo_warns(self):
        ws = self._make_ws({
            "workspace.yaml": "project: demo\nkind: multi\nrepos:\n  svc:\n    url: x\n",
            "assets/common/env.json": json.dumps({"activeEnv": "t", "envs": {"t": {}}})})
        os.makedirs(os.path.join(ws, "another-repo", ".git"))
        w6 = self._by_id(ws_check.run_checks(ws), "W6")
        self.assertEqual(w6["level"], "warning")
        self.assertFalse(w6["ok"])

    def test_w6_registered_git_repo_ok(self):
        ws = self._make_ws({
            "workspace.yaml": "project: demo\nkind: multi\nrepos:\n  svc:\n    url: x\n",
            "assets/common/env.json": json.dumps({"activeEnv": "t", "envs": {"t": {}}})})
        os.makedirs(os.path.join(ws, "svc", ".git"))
        self.assertTrue(self._by_id(ws_check.run_checks(ws), "W6")["ok"])

    def test_missing_yaml_is_error(self):
        ws = self._make_ws({
            "assets/common/env.json": json.dumps({"activeEnv": "t", "envs": {"t": {}}})})
        self.assertFalse(self._by_id(ws_check.run_checks(ws), "W1")["ok"])

    def test_bad_env_json_is_error(self):
        ws = self._make_ws({"workspace.yaml": "project: d\nkind: b\nrepo: r\n",
                            "assets/common/env.json": "{not json"})
        self.assertFalse(self._by_id(ws_check.run_checks(ws), "W3")["ok"])

    def test_plaintext_secret_detected(self):
        ws = self._make_ws({
            "workspace.yaml": 'project: d\nkind: b\nrepo: r\ndbpass: password: SuperSecret99\n',
            "assets/common/env.json": json.dumps({"activeEnv": "t", "envs": {"t": {}}})})
        self.assertFalse(self._by_id(ws_check.run_checks(ws), "W4")["ok"])

    def test_secret_in_env_json_detected(self):
        ws = self._make_ws({
            "workspace.yaml": "project: d\nkind: b\nrepo: r\n",
            "assets/common/env.json":
                '{"activeEnv":"t","envs":{"t":{"db":{"password":"Abcd1234efg"}}}}'})
        self.assertFalse(self._by_id(ws_check.run_checks(ws), "W4")["ok"])

    def test_placeholder_secret_allowed(self):
        ws = self._make_ws({
            "workspace.yaml": "project: d\nkind: b\nrepo: r\n",
            "assets/common/env.json":
                '{"activeEnv":"t","envs":{"t":{"db":{"password":"${DB_PASS}"}}}}'})
        self.assertTrue(self._by_id(ws_check.run_checks(ws), "W4")["ok"])

    def test_secret_file_without_gitignore_warns(self):
        ws = self._make_ws({
            "workspace.yaml": "project: d\nkind: b\nrepo: r\n",
            "assets/common/env.json": json.dumps({"activeEnv": "t", "envs": {"t": {}}}),
            "assets/common/env.secret.json": '{"envs": {}}'})
        w5 = self._by_id(ws_check.run_checks(ws), "W5")
        self.assertEqual(w5["level"], "warning")
        self.assertFalse(w5["ok"])


if __name__ == "__main__":
    unittest.main()
