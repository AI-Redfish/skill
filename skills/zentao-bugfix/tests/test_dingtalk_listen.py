#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dingtalk_listen.py 单元测试（纯标准库，不依赖 dws/网络/真实 Agent）。

运行：python -m unittest discover -s tests -p "test_dingtalk_listen.py" -v
"""
import atexit
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dingtalk_listen.py"
# 模块常量（CONFIG_FILE/LOG_DIR）在 import 时锥定 cwd：测试进程先切到临时目录，
# 避免从 skill 目录跑单测时把 .agents/logs 写进 skill 目录内
TEST_CWD = tempfile.mkdtemp(prefix="dl_test_cwd_")
atexit.register(shutil.rmtree, TEST_CWD, ignore_errors=True)
_old_cwd = os.getcwd()
os.chdir(TEST_CWD)
try:
    spec = importlib.util.spec_from_file_location("dingtalk_listen", SCRIPT)
    dl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dl)
finally:
    os.chdir(_old_cwd)


class TestJsonLoose(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(dl.parse_json_loose('{"a":1}'), {"a": 1})

    def test_fenced(self):
        text = '```json\n{"is_bugfix": true, "bug_id": "12345"}\n```'
        d = dl.parse_json_loose(text)
        self.assertTrue(d["is_bugfix"])
        self.assertEqual(d["bug_id"], "12345")

    def test_noisy_prefix_and_suffix(self):
        text = '好的，结果是：\n{"bug_id": "12"}\n以上。'
        self.assertEqual(dl.parse_json_loose(text)["bug_id"], "12")

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            dl.parse_json_loose("完全不是 JSON")


class TestEnvRoundtrip(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".agents" / "zentao-bugfix" / "routes.json"
            dl.save_config(p, {"A": "1"})
            dl.save_config(p, {"A": "2", "B": "x=y"})     # 覆盖 + 值含等号
            cfg = dl.load_config(p)
            self.assertEqual(cfg["A"], "2")
            self.assertEqual(cfg["B"], "x=y")

    def test_rules_preserved_when_saving_config(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "routes.json"
            rules = [{"name": "订单", "match": {"bug_id": "123"}, "workspace": "/dev", "target_branch": "feature/order"}]
            dl._routes.save(p, {"config": {"K": "1"}, "rules": rules})
            dl.save_config(p, {"K": "9"})
            self.assertEqual(dl._routes.read(p)["rules"], rules)
            self.assertEqual(dl.load_config(p)["K"], "9")


class TestPiSessionDetect(unittest.TestCase):
    def _mk(self, root, dirname, cwd, provider, model, older=0):
        d = root / dirname
        d.mkdir(parents=True)
        sf = d / "2026-01-01T00-00-00.jsonl"
        lines = ['{"type":"session","version":3,"cwd":%s}' % json.dumps(cwd),
                 '{"type":"model_change","provider":"%s","modelId":"%s"}' % (provider, model)]
        sf.write_text("\n".join(lines), encoding="utf-8")
        old = older or sf.stat().st_mtime
        import os as _os
        _os.utime(sf, (old, old))

    def test_match_and_miss(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._mk(root, "dirA", r"D:\\repo\\one", "prov-a", "model-a", older=time.time() - 100)
            self._mk(root, "dirB", r"D:\\repo\\two", "prov-b", "model-b")
            self.assertEqual(dl.detect_pi_session_model(root, r"D:\\repo\\two"), "prov-b/model-b")
            self.assertEqual(dl.detect_pi_session_model(root, r"D:\\repo\\one"), "prov-a/model-a")
            self.assertIsNone(dl.detect_pi_session_model(root, r"D:\\repo\\none"))


class TestDedup(unittest.TestCase):
    def test_seen_add_persist(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "processed.json"
            s1 = dl.DedupStore(p)
            self.assertFalse(s1.seen("m1"))
            s1.add("m1")
            self.assertTrue(s1.seen("m1"))
            s2 = dl.DedupStore(p)                      # 重新加载持久化
            self.assertTrue(s2.seen("m1"))


    def test_default_path_instantiation(self):
        """不传 path 时应回退到模块常量（曾经的真实 bug：默认参数 None 崩溃）。"""
        with tempfile.TemporaryDirectory() as td:
            old = dl.PROCESSED_FILE
            try:
                dl.PROCESSED_FILE = Path(td) / "processed.json"
                s = dl.DedupStore()               # 不传参，不应抛异常
                s.add("m9")
                self.assertTrue(dl.DedupStore().seen("m9"))
            finally:
                dl.PROCESSED_FILE = old


class TestAdapters(unittest.TestCase):
    def setUp(self):
        self._orig = dl.resolve_exe
        self._pf = dl._prompt_file
        dl.resolve_exe = lambda n: n            # 隔离环境：不真实解析路径
        dl._prompt_file = lambda p: Path("/tmp/fake-prompt.txt")   # 不真实落盘

    def tearDown(self):
        dl.resolve_exe = self._orig
        dl._prompt_file = self._pf

    def test_pi_extract_and_fix(self):
        a = dl.PiAdapter("provider-x/model-y")
        ce, stdin_text = a.extract("P")
        self.assertEqual(ce[0], "pi")
        self.assertIn("--no-tools", ce)
        self.assertIn("provider-x/model-y", ce)
        self.assertTrue(ce[-1].startswith("@"), "提示词必须走 @file 而非 argv")
        self.assertIsNone(stdin_text)
        cf, _ = a.fix("P", "/repo")
        self.assertIn("--skill", cf)
        self.assertNotIn("--no-tools", cf)             # 修复需要工具
        self.assertTrue(cf[-1].startswith("@"))

    def test_codex(self):
        a = dl.CodexAdapter("gpt-5")
        ce, si = a.extract("P")
        self.assertIn("read-only", ce)
        self.assertEqual(si, "P")                        # codex 提示词走 stdin
        cf, _ = a.fix("P", "/r")
        self.assertIn("danger-full-access", cf)

    def test_claude(self):
        a = dl.ClaudeAdapter("sonnet")
        ce, si = a.extract("P")
        self.assertIn("-p", ce)
        self.assertEqual(si, "P")
        cf, _ = a.fix("P", "/r")
        self.assertIn("--dangerously-skip-permissions", cf)

    def test_custom_template(self):
        a = dl.CustomAdapter("deepseek-chat", "dsh -p --model {model} {prompt}")
        ce, _ = a.extract('修 bug "12345"')
        self.assertEqual(ce[0], "dsh")
        self.assertIn("--model", ce)
        joined = " ".join(ce)
        self.assertNotIn('"', joined)                  # 引号已被中和，防注入

    def test_custom_missing_template(self):
        a = dl.CustomAdapter("m", "")
        with self.assertRaises(RuntimeError):
            a.extract("P")


class TestResolveExe(unittest.TestCase):
    def test_which_hit_and_fallback(self):
        orig = dl.shutil.which
        try:
            dl.shutil.which = lambda n: {"pi": "C:\\tools\\pi.cmd"}.get(n)
            self.assertEqual(dl.resolve_exe("pi"), "C:\\tools\\pi.cmd")
            dl.shutil.which = lambda n: {"pi.cmd": "D:\\x\\pi.cmd"}.get(n)
            self.assertEqual(dl.resolve_exe("pi"), "D:\\x\\pi.cmd")
            dl.shutil.which = lambda n: None
            self.assertEqual(dl.resolve_exe("nothing"), "nothing")
        finally:
            dl.shutil.which = orig


class TestExtractIntent(unittest.TestCase):
    def setUp(self):
        self._orig = dl.run_agent_cmd

    def _patch_run(self, outputs):
        seq = list(outputs)

        def fake(cmd, cwd=None, timeout=None, stdin_text=None):
            return seq.pop(0)
        dl.run_agent_cmd = fake

    def tearDown(self):
        dl.run_agent_cmd = self._orig            # 恢复被 patch 的函数

    def test_bug_message(self):
        self._patch_run(['{"is_bugfix": true, "bug_id": "BUG-12345", "reason": "r"}'])
        r = dl.extract_bug_intent(dl.PiAdapter("m"), "李四", "帮我修一下 BUG-12345")
        self.assertTrue(r["is_bugfix"])
        self.assertEqual(r["bug_id"], "12345")         # 非数字被清洗

    def test_chat_message(self):
        self._patch_run(['```json\n{"is_bugfix": false, "bug_id": null, "reason": "闲聊"}\n```'])
        r = dl.extract_bug_intent(dl.PiAdapter("m"), "李四", "今天天气不错")
        self.assertFalse(r["is_bugfix"])

    def test_alias_fields(self):
        self._patch_run(['{"is_bug_fix_request": true, "bugId": 12345}'])
        r = dl.extract_bug_intent(dl.PiAdapter("m"), "李四", "修 bug 12345")
        self.assertTrue(r["is_bugfix"])
        self.assertEqual(r["bug_id"], "12345")

    def test_prompt_contract(self):
        self.assertIn('"is_bugfix"', dl.EXTRACT_PROMPT)
        self.assertIn("bug-view-XXXXX.html", dl.EXTRACT_PROMPT)

    def test_agent_output_invalid(self):
        self._patch_run(["模型抽风了"])
        with self.assertRaises(ValueError):
            dl.extract_bug_intent(dl.PiAdapter("m"), "李四", "x")


class TestFrontendAnalysisPrompt(unittest.TestCase):
    """修复会话提示词必须要求前端只读分析与问题归属结论。"""

    def test_prompt_requires_layer_attribution(self):
        text = dl.build_fix_prompt("101")
        self.assertIn("问题归属", text)
        self.assertIn("FRONTEND_WORKSPACES", text)
        prepared = {"project": "D:/p", "workspace": "D:/wt", "report_dir": "D:/rd",
                    "mode": "worktree", "run_id": "abc"}
        text = dl.build_fix_prompt("101", None, prepared)
        self.assertIn("问题归属", text)
        self.assertIn("FRONTEND_WORKSPACES", text)
        self.assertIn("只读", text)
        self.assertIn("禁止修改、暂存或提交", text)

    def test_frontend_key_is_documented_and_round_trips(self):
        self.assertIn("FRONTEND_WORKSPACES", dl.KEY_HELP)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "routes.json"
            dl.save_config(p, {"FRONTEND_WORKSPACES": "D:/develop/project/wukong"})
            self.assertEqual(dl.load_config(p)["FRONTEND_WORKSPACES"], "D:/develop/project/wukong")


class TestSyncZentaoConfig(unittest.TestCase):
    def test_sync_and_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            old = dl.CONFIG_FILE
            try:
                src = Path(td) / "routes.json"
                dl.save_config(src, {"ZENTAO_BASE_URL": "http://z", "ZENTAO_ACCOUNT": "a",
                                  "ZENTAO_PASSWORD": "p"})
                dl.CONFIG_FILE = src
                repo = Path(td) / "repo"
                (repo / ".git").mkdir(parents=True)
                rules = [{"match": {"title_contains": "订单"}, "workspace": "/dev", "target_branch": "feature/order"}]
                dl._routes.save(dl._routes.config_path(repo), {"rules": rules, "config": {"BUGFIX_BASE_BRANCH": "release", "ZENTAO_ACCOUNT": "old"}})
                dl.sync_zentao_config_to_repo(repo)
                cfg = dl.load_config(dl._routes.config_path(repo))
                self.assertEqual(cfg["ZENTAO_BASE_URL"], "http://z")
                self.assertEqual(cfg["ZENTAO_ACCOUNT"], "a")
                self.assertEqual(cfg["BUGFIX_BASE_BRANCH"], "release")
                self.assertEqual(dl._routes.read(dl._routes.config_path(repo))["rules"], rules)
                self.assertIn(".agents/zentao-bugfix/routes.json", (repo / ".gitignore").read_text(encoding="utf-8"))
                # 二次同步不重复追加 gitignore
                dl.sync_zentao_config_to_repo(repo)
                text = (repo / ".gitignore").read_text(encoding="utf-8")
                self.assertEqual(text.count(".agents/zentao-bugfix/routes.json"), 1)
            finally:
                dl.CONFIG_FILE = old


class TestResolveRepo(unittest.TestCase):
    def test_env_priority_over_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r"
            (repo / ".git").mkdir(parents=True)
            got = dl.resolve_repo({"TARGET_PROJECT_PATH": str(repo)})
            self.assertEqual(got, repo.resolve())


class TestConfigLocation(unittest.TestCase):
    """Only startup-workspace routes.json is read; old .env is never a fallback."""

    def test_anchors_to_cwd_not_skill_dir(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                spec2 = importlib.util.spec_from_file_location("dl_reload", SCRIPT)
                dl2 = importlib.util.module_from_spec(spec2)
                spec2.loader.exec_module(dl2)
                base = Path(td).resolve()
                self.assertEqual(dl2.CONFIG_FILE, base / ".agents" / "zentao-bugfix" / "routes.json")
                self.assertEqual(dl2.LOG_DIR, base / ".agents" / "logs")
                # 不落在 skill 目录内（安装到 <工作空间>/.agents/skills/ 时会嵌套 .agents）
                self.assertFalse(str(dl2.CONFIG_FILE).startswith(
                    str(dl2.SKILL_DIR / ".agents")))
            finally:
                os.chdir(old_cwd)

    def test_legacy_env_not_read(self):
        with tempfile.TemporaryDirectory() as td:
            old = dl.CONFIG_FILE
            try:
                project = Path(td)
                (project / ".agents").mkdir()
                (project / ".agents" / ".env").write_text("OLD=1\n", encoding="utf-8")
                dl.CONFIG_FILE = dl._routes.config_path(project)
                self.assertEqual(dl.load_config(), {})
                dl.save_config(dl.CONFIG_FILE, {"NEW": "2"})
                self.assertEqual(dl.load_config(), {"NEW": "2"})
                self.assertEqual((project / ".agents" / ".env").read_text(), "OLD=1\n")
            finally:
                dl.CONFIG_FILE = old

    def test_invalid_config_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "routes.json"
            for content in ('not json', '{"config": []}', '{"config": {"KEY": 5}}'):
                p.write_text(content, encoding="utf-8")
                with self.assertRaises((ValueError, dl._routes.RouteError)):
                    dl.load_config(p)


class TestMissingAndMask(unittest.TestCase):
    def test_config_status_masks_password_and_reports_json_path(self):
        import contextlib
        import io
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "routes.json"
            dl.save_config(path, {"ZENTAO_PASSWORD": "test-password", "LISTEN_MODE": "poll"})
            output = io.StringIO()
            with patch.object(dl, "CONFIG_FILE", path), contextlib.redirect_stdout(output):
                dl.cmd_config_status(None)
            result = json.loads(output.getvalue())
            self.assertEqual(result["config_file"], str(path))
            self.assertNotIn("test-password", output.getvalue())
            self.assertEqual(result["present"]["LISTEN_MODE"], "poll")


    def test_missing_keys(self):
        self.assertEqual(dl.missing_keys({"ZENTAO_BASE_URL": "x"},
                                         ["ZENTAO_BASE_URL", "DWS_LISTEN_USERS"]),
                         ["DWS_LISTEN_USERS"])

    def test_bots_only_allowed(self):
        """只监听机器人时 DWS_LISTEN_USERS 可留空（真实部署场景）。"""
        cfg = {"ZENTAO_BASE_URL": "u", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "p",
               "DWS_LISTEN_BOTS": "通知机器人"}
        self.assertEqual(dl.missing_keys(cfg), [])

    def test_no_targets_at_all(self):
        cfg = {"ZENTAO_BASE_URL": "u", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "p"}
        self.assertIn("DWS_LISTEN_USERS", dl.missing_keys(cfg))

    def test_mask(self):
        self.assertEqual(dl.mask("secret123"), "sec***")
        self.assertEqual(dl.mask(""), "")


class TestVerifyFix(unittest.TestCase):
    """修复产物校验：无头会话退出码 0 ≠ 流程完成，以文件证据为准。"""

    def _mk_repo(self, td):
        repo = Path(td) / "repo"
        (repo / ".git").mkdir(parents=True)
        return repo

    def test_no_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mk_repo(td)
            v = dl.verify_fix("75042", repo)
            self.assertFalse(v["ok"])
            self.assertIsNone(v["worktree"])

    def test_worktree_with_meta(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mk_repo(td)
            wt = repo.parent / "bugfix_75042_20260920"
            rd = wt / ".agents" / "zentao-bugfix" / "75042"
            rd.mkdir(parents=True)
            (rd / "meta.json").write_text("{}", encoding="utf-8")
            v = dl.verify_fix("75042", repo)
            self.assertTrue(v["ok"])
            # Windows TEMP 可能是 8.3 短路径，按 realpath 归一后比较。
            self.assertEqual(os.path.realpath(v["worktree"]), os.path.realpath(str(wt)))
            self.assertIsNone(v["report"])          # 尚无 fix-report.md
            (rd / "fix-report.md").write_text("x", encoding="utf-8")
            self.assertTrue(dl.verify_fix("75042", repo)["report"].endswith("fix-report.md"))

    def test_legacy_report_dir_fallback(self):
        """旧版 worktree（.agents/bugfix/<id> 布局）也能被识别与校验。"""
        with tempfile.TemporaryDirectory() as td:
            repo = self._mk_repo(td)
            wt = repo.parent / "bugfix_75044_20260920"
            rd = wt / ".agents" / "bugfix" / "75044"
            rd.mkdir(parents=True)
            (rd / "meta.json").write_text("{}", encoding="utf-8")
            (rd / "analysis.md").write_text("已完整", encoding="utf-8")
            v = dl.verify_fix("75044", repo)
            self.assertTrue(v["ok"])
            self.assertTrue(v["report_dir"].endswith(".agents%sbugfix%s75044" % (os.sep, os.sep)))
            self.assertTrue(v["analysis_complete"])

    def test_worktree_without_meta_not_counted(self):
        """同名目录但无 meta.json（残留/伪造）不算 prepare 成功。"""
        with tempfile.TemporaryDirectory() as td:
            repo = self._mk_repo(td)
            (repo.parent / "bugfix_75042_20260920").mkdir()
            self.assertFalse(dl.verify_fix("75042", repo)["ok"])

    def test_analysis_first_states(self):
        """分析先行校验：analysis/solution 缺失/未补全/已完整三种状态。"""
        with tempfile.TemporaryDirectory() as td:
            repo = self._mk_repo(td)
            wt = repo.parent / "bugfix_75043_20260920"
            rd = wt / ".agents" / "zentao-bugfix" / "75043"
            rd.mkdir(parents=True)
            (rd / "meta.json").write_text("{}", encoding="utf-8")
            v = dl.verify_fix("75043", repo)
            self.assertTrue(v["ok"])
            self.assertFalse(v["analysis_complete"])          # missing
            self.assertEqual(v["analysis_state"], "missing")
            self.assertFalse(v["solution_complete"])
            self.assertEqual(v["solution_state"], "missing")
            (rd / "analysis.md").write_text("（待填写）", encoding="utf-8")
            v = dl.verify_fix("75043", repo)
            self.assertFalse(v["analysis_complete"])          # 仍有待填写
            self.assertEqual(v["analysis_state"], "yes")
            (rd / "analysis.md").write_text("根因：xxx（文件:行号）", encoding="utf-8")
            v = dl.verify_fix("75043", repo)
            self.assertTrue(v["analysis_complete"])
            self.assertEqual(v["analysis_state"], "no")
            (rd / "solution.md").write_text("方案：xxx（待填写）", encoding="utf-8")
            self.assertFalse(dl.verify_fix("75043", repo)["solution_complete"])
            (rd / "solution.md").write_text("方案：xxx", encoding="utf-8")
            self.assertTrue(dl.verify_fix("75043", repo)["solution_complete"])


class TestFixPrompt(unittest.TestCase):
    def test_with_base_branch(self):
        p = dl.build_fix_prompt("12345", "dev/v6.0.6.3")
        self.assertIn("基准分支必须使用 dev/v6.0.6.3", p)
        self.assertIn("prepare 12345 dev/v6.0.6.3 --project .", p)

    def test_without_base_branch(self):
        p = dl.build_fix_prompt("12345")
        self.assertIn("使用当前仓库所在分支", p)
        self.assertIn("prepare 12345 --project .", p)
        self.assertNotIn("基准分支必须", p)

    def test_analysis_first_ordering(self):
        """分析先行：提示词必须先补全 analysis.md/solution.md（不改代码）再实施修复。"""
        p = dl.build_fix_prompt("12345")
        self.assertIn("补全 analysis.md", p)
        self.assertIn("solution.md", p)
        self.assertIn("禁止修改任何代码文件", p)
        self.assertIn("依据 solution.md", p)
        # 顺序：补全 analysis.md 的步骤先于实施修复的步骤
        self.assertLess(p.index("补全 analysis.md"), p.index("实施修复"))
        # 分析报告落盘位置指向 worktree 的 .agents/zentao-bugfix
        self.assertIn(".agents/zentao-bugfix/", p)


class TestRoutedRuns(unittest.TestCase):
    def test_prepared_prompt_does_not_prepare_twice(self):
        prepared = {"mode": "inplace", "project": "/repo with space", "workspace": "/dev", "report_dir": "/dev/.agents/zentao-bugfix/1"}
        p = dl.build_fix_prompt("1", prepared=prepared)
        self.assertIn("禁止再次 prepare", p)
        self.assertIn("ready 1", p)
        self.assertIn("finish 1", p)
        self.assertIn("--check-command", p)
        self.assertLess(p.index("ready 1"), p.index("实施修复"))

    def test_verify_requires_current_run_complete_reports_and_commit(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            rd = repo / "reports"
            rd.mkdir()
            rec = {"run_id": "new", "report_dir": str(rd), "workspace": str(repo), "mode": "worktree"}
            dl._routes.save(dl._routes.record_path(repo, "1"), rec)
            dl._routes.save(rd / "meta.json", {"run_id": "old"})
            for name in ("analysis.md", "solution.md", "fix-report.md"):
                (rd / name).write_text("完整", encoding="utf-8")
            self.assertFalse(dl.verify_run("1", repo, "new")["ok"])
            dl._routes.save(rd / "meta.json", {"run_id": "new"})
            self.assertFalse(dl.verify_run("1", repo, "new")["ok"])  # HTML missing
            dl._routes._reports.render_reports(rd, require_complete=True)
            self.assertTrue(dl.verify_run("1", repo, "new")["ok"])
            rec.update(mode="inplace", status="prepared")
            dl._routes.save(dl._routes.record_path(repo, "1"), rec)
            self.assertFalse(dl.verify_run("1", repo, "new")["ok"])
            rec.update(status="no_change", validation={"returncode": 0})
            dl._routes.save(dl._routes.record_path(repo, "1"), rec)
            self.assertTrue(dl.verify_run("1", repo, "new")["ok"])
            (rd / "fix-report.md").write_text("已完整，但正文变化", encoding="utf-8")
            self.assertFalse(dl.verify_run("1", repo, "new")["ok"])  # stale HTML
            dl._routes._reports.render_reports(rd, require_complete=True)
            self.assertTrue(dl.verify_run("1", repo, "new")["ok"])
            (rd / "fix-report.md").write_text("（待填写）", encoding="utf-8")
            self.assertFalse(dl.verify_run("1", repo, "new")["ok"])

    def test_listener_runs_agent_in_prepared_workspace_and_verifies_current_run(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "source"
            repo.mkdir()
            workspace = Path(td) / "dev"
            workspace.mkdir()
            rd = workspace / ".agents" / "zentao-bugfix" / "1"
            rd.mkdir(parents=True)
            rec = {"run_id": "current", "report_dir": str(rd), "workspace": str(workspace), "mode": "worktree"}
            dl._routes.save(dl._routes.record_path(repo, "1"), rec)
            dl._routes.save(rd / "meta.json", {"run_id": "current"})
            for name in ("analysis.md", "solution.md", "fix-report.md"):
                (rd / name).write_text("完整", encoding="utf-8")
            dl._routes._reports.render_reports(rd, require_complete=True)
            adapter = dl.PiAdapter("m")
            with patch.object(dl, "fetch_resolution", return_value={"resolution": "unset"}), patch.object(dl, "sync_zentao_config_to_repo"), patch.object(dl.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "MODE=worktree", "")), patch.object(adapter, "fix", return_value=(["fake"], None)) as fix, patch.object(dl, "run_agent_cmd", return_value="done") as run:
                result = dl.run_auto_fix(adapter, "1", repo)
            self.assertTrue(result["ok"])
            self.assertEqual(run.call_args.kwargs["cwd"], str(workspace))
            self.assertEqual(fix.call_args.args[1], str(workspace))

    def test_waiting_jobs_preserve_order_resume_and_persist(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            li = dl.Listener([], dl.PiAdapter("m"), Path(td))
            path = Path(td) / "pending.json"
            pending = ["101", "102", "103"]
            with patch.object(li.notifier, "publish", return_value={"sent": True}), patch.object(dl, "run_auto_fix", side_effect=[
                {"ok": True, "status": "committed"},
                {"ok": False, "status": "waiting"},
                {"ok": False, "status": "waiting"}]) as fix:
                li._retry_waiting(pending, path)
            self.assertEqual(pending, ["102", "103"])
            self.assertEqual(dl._routes.read(path), ["102", "103"])
            self.assertEqual([call.args[1] for call in fix.call_args_list], ["101", "102", "103"])
            self.assertTrue(all(call.kwargs["reuse"] for call in fix.call_args_list))

    def test_workspace_error_never_starts_agent(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            rec = {"status": "workspace_error", "html_report": str(repo / "error.html"), "error": "不存在"}
            dl._routes.save(dl._routes.record_path(repo, "1"), rec)
            adapter = dl.PiAdapter("m")
            with patch.object(dl, "fetch_resolution", return_value={"resolution": "unset"}), patch.object(dl, "sync_zentao_config_to_repo"), patch.object(dl.subprocess, "run", return_value=subprocess.CompletedProcess([], 7, "HTML_REPORT=x", "")), patch.object(adapter, "fix") as fix:
                result = dl.run_auto_fix(adapter, "1", repo)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "workspace_error")
            fix.assert_not_called()


class TestResolutionGate(unittest.TestCase):
    """resolution 过滤：Resolution 有值的 Bug 不处理；未知值失败关闭。"""

    def test_blank_or_missing_value_is_processed_and_other_values_skip(self):
        for bug in ({"resolution": ""}, {"resolution": "   "}, {"resolution": None},
                    {"resolution": 0}):
            with self.subTest(bug=bug):
                self.assertEqual(dl.resolution_state(bug), "unset")
        for value in ("fixed", "notrepro", "bydesign", "duplicate", "已解决"):
            with self.subTest(value=value):
                self.assertEqual(dl.resolution_state({"resolution": value}), "set")
        for bug in ({}, {"resolution": 1}, {"resolution": 2}, {"resolution": {}},
                    {"resolution": []}, {"resolution": False}, "not-a-dict", None):
            with self.subTest(bug=bug):
                self.assertEqual(dl.resolution_state(bug), "unknown")

    def test_resolved_never_prepares_or_syncs(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            with patch.object(dl, "fetch_resolution", return_value={"resolution": "set"}), patch.object(dl, "_run_auto_fix") as fix:
                result = dl.run_auto_fix(dl.PiAdapter("m"), "1", Path(td))
            self.assertEqual(result["status"], "skipped_resolved")
            fix.assert_not_called()
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_unknown_or_query_failure_never_prepares(self):
        from unittest.mock import patch
        with patch.object(dl, "fetch_resolution", side_effect=RuntimeError("无法查询解决方案状态")), patch.object(dl, "_run_auto_fix") as fix:
            result = dl.run_auto_fix(dl.PiAdapter("m"), "1", Path("unused"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        fix.assert_not_called()

    def test_unset_proceeds_and_retry_rechecks(self):
        from unittest.mock import patch
        with patch.object(dl, "fetch_resolution", side_effect=[{"resolution": "unset"}, {"resolution": "set"}]), patch.object(dl, "_run_auto_fix", return_value={"ok": True}) as fix:
            self.assertTrue(dl.run_auto_fix(dl.PiAdapter("m"), "1", Path("unused"))["ok"])
            self.assertEqual(dl.run_auto_fix(dl.PiAdapter("m"), "1", Path("unused"), reuse=True)["status"], "skipped_resolved")
        self.assertEqual(fix.call_count, 1)

    def test_api_fallback_no_files_and_no_secret_errors(self):
        from unittest.mock import patch
        cfg = {"ZENTAO_BASE_URL": "https://example.test", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "secret"}
        with patch.object(dl, "load_config", return_value=cfg), patch.object(dl._bug_api, "fetch_bug_v1", return_value={"id": 1}), patch.object(dl._bug_api, "zentao_session"), patch.object(dl._bug_api, "fetch_bug_classic", return_value={"bug": {"id": "1", "resolution": ""}}), patch.object(dl._bug_api, "fetch_bug_full") as full:
            self.assertEqual(dl.fetch_resolution("1")["resolution"], "unset")
            full.assert_not_called()
        # v1/classic 都返回未知类型时失败关闭
        with patch.object(dl, "load_config", return_value=cfg), patch.object(dl._bug_api, "fetch_bug_v1", return_value={"id": 1}), patch.object(dl._bug_api, "zentao_session"), patch.object(dl._bug_api, "fetch_bug_classic", return_value={"bug": {"id": "1", "resolution": 1}}):
            with self.assertRaises(RuntimeError):
                dl.fetch_resolution("1")
        with patch.object(dl, "load_config", return_value=cfg), patch.object(dl._bug_api, "fetch_bug_v1", side_effect=RuntimeError("secret")), patch.object(dl._bug_api, "zentao_session", side_effect=RuntimeError("secret")):
            with self.assertRaises(RuntimeError) as err:
                dl.fetch_resolution("1")
            self.assertNotIn("secret", str(err.exception))

    def test_prepare_recheck_stops_before_files_or_reports(self):
        from unittest.mock import patch
        cfg = {"ZENTAO_BASE_URL": "https://example.test", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "secret"}
        for value in ("fixed", 1, "unknown"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                bug = {"id": 1, "resolution": value, "steps": '<img src="file-read-1.png">'}
                with patch.object(dl._bug_api, "load_config", return_value=("config", cfg)), patch.object(dl._bug_api, "fetch_bug_v1", return_value=bug), patch.object(dl._bug_api, "zentao_session"), patch.object(dl._bug_api, "fetch_bug_classic", return_value=None), patch.object(dl._bug_api, "download_images") as images:
                    with self.assertRaises(dl._bug_api.ResolutionStop):
                        dl._bug_api.fetch_bug_full(td, "1", skip_resolved=True)
                images.assert_not_called()
                self.assertEqual(list(Path(td).iterdir()), [])

    def test_prepare_race_does_not_start_agent(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            adapter = dl.PiAdapter("m")
            with patch.object(dl, "fetch_resolution", return_value={"resolution": "unset"}), patch.object(dl, "sync_zentao_config_to_repo"), patch.object(dl.subprocess, "run", return_value=subprocess.CompletedProcess([], 9, "RESOLUTION_STOP=set", "")) as prepare, patch.object(adapter, "fix") as fix:
                result = dl.run_auto_fix(adapter, "1", Path(td))
            self.assertNotIn("--only-unconfirmed", prepare.call_args.args[0])
            self.assertEqual(result["status"], "skipped_resolved")
            self.assertEqual(result["resolution"], "set")
            fix.assert_not_called()

    def test_wrong_bug_id_rejected(self):
        from unittest.mock import patch
        cfg = {"ZENTAO_BASE_URL": "https://example.test", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "secret"}
        with patch.object(dl, "load_config", return_value=cfg), patch.object(dl._bug_api, "fetch_bug_v1", return_value={"id": 2, "resolution": ""}), patch.object(dl._bug_api, "zentao_session"), patch.object(dl._bug_api, "fetch_bug_classic", return_value=None):
            with self.assertRaises(RuntimeError):
                dl.fetch_resolution("1")


class TestResultNotifications(unittest.TestCase):
    def test_current_user_required(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            n = dl.ResultNotifier(Path(td) / "outbox.json")
            with patch.object(dl, "run_dws", return_value=json.dumps({"authenticated": True, "user_id": "me", "corp_id": "corp"})):
                self.assertEqual(n.bind_current_user()["user_id"], "me")
            with patch.object(dl, "run_dws", return_value='{"authenticated":false}'):
                with self.assertRaises(RuntimeError):
                    n.bind_current_user()

    def test_all_outcomes_send_to_self_and_dedup(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            n = dl.ResultNotifier(Path(td) / "outbox.json")
            n.recipient = {"user_id": "me", "corp_id": "corp"}
            with patch.object(dl, "run_dws", return_value='{"success":true}') as send:
                for i, result in enumerate((
                    {"status": "skipped_resolved", "ok": False},
                    {"status": "duplicate", "ok": False},
                    {"status": "committed", "ok": True, "commit": "abc"},
                    {"status": "prepared", "mode": "worktree", "ok": True},
                    {"status": "blocked", "ok": False, "error": "SECRET raw Bug text"},
                    {"status": "waiting", "ok": False})):
                    result["bug_id"] = "1"
                    self.assertTrue(n.publish(result, "message:" + str(i))["sent"])
                    self.assertTrue(n.publish(result, "message:" + str(i))["sent"])
                self.assertEqual(send.call_count, 6)
                for call in send.call_args_list:
                    args = call.args[0]
                    self.assertEqual(args[args.index("--user") + 1], "me")
                    self.assertEqual(args[args.index("--profile") + 1], "corp:me")
                    self.assertIn("--idempotency-key", args)
                    self.assertIn("--format", args)
                    self.assertIn("--yes", args)
                    self.assertNotIn("SECRET", args[args.index("--text") + 1])
            self.assertEqual(n.pending_count(), 0)

    def test_failure_persist_restart_retry_same_recipient_and_key(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "outbox.json"
            n = dl.ResultNotifier(p)
            n.recipient = {"user_id": "me", "corp_id": "corp"}
            with patch.object(dl, "run_dws", side_effect=RuntimeError("SECRET")):
                result = n.publish({"bug_id": "1", "ok": True}, "message:m")
            self.assertFalse(result["sent"])
            self.assertEqual(n.pending_count(), 1)
            self.assertNotIn("SECRET", p.read_text(encoding="utf-8"))
            n2 = dl.ResultNotifier(p)
            n2.recipient = {"user_id": "other", "corp_id": "othercorp"}
            with patch.object(dl, "run_dws", return_value='{"success":true}') as send:
                n2.retry_pending()
            args = send.call_args.args[0]
            self.assertEqual(args[args.index("--user") + 1], "me")
            self.assertEqual(args[args.index("--idempotency-key") + 1], result["key"])
            self.assertEqual(dl.ResultNotifier(p).pending_count(), 0)

    def test_async_receipt_retries_query_not_send(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "outbox.json"
            n = dl.ResultNotifier(p)
            n.recipient = {"user_id": "me", "corp_id": "corp"}
            receipt = {"ok": True, "result": {"success": True}, "sendReceipt": {"openTaskId": "task"}}
            with patch.object(dl, "run_dws", side_effect=[json.dumps(receipt), RuntimeError("query failed")]) as calls:
                self.assertFalse(n.publish({"bug_id": "1", "ok": True}, "message:m")["sent"])
                self.assertEqual(calls.call_count, 2)
            n2 = dl.ResultNotifier(p)
            delivered = {"success": True, "result": {"sendStatus": "SUCCESS"}, "messageRef": {"openMessageId": "m"}}
            with patch.object(dl, "run_dws", return_value=json.dumps(delivered)) as calls:
                n2.retry_pending()
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(calls.call_args.args[0][1], "+messages-query-send-status")
            self.assertEqual(n2.pending_count(), 0)

    def test_async_pending_is_not_delivered(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            n = dl.ResultNotifier(Path(td) / "outbox.json")
            n.recipient = {"user_id": "me", "corp_id": "corp"}
            receipt = {"ok": True, "result": {"success": True}, "sendReceipt": {"openTaskId": "task"}}
            pending = {"success": True, "result": {"sendStatus": "PENDING"}}
            with patch.object(dl, "run_dws", side_effect=[json.dumps(receipt), json.dumps(pending)]):
                self.assertFalse(n.publish({"bug_id": "1", "ok": True}, "message:m")["sent"])
            self.assertEqual(n.pending_count(), 1)

    def test_false_success_keeps_pending(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            n = dl.ResultNotifier(Path(td) / "outbox.json")
            n.recipient = {"user_id": "me", "corp_id": "corp"}
            with patch.object(dl, "run_dws", return_value='{"success":false}'):
                self.assertFalse(n.publish({"bug_id": "1", "ok": False}, "message:m")["sent"])
            self.assertEqual(n.pending_count(), 1)

    def test_stream_poll_worker_same_gate_and_one_result(self):
        from unittest.mock import patch
        for mode in ("stream", "poll", "auto"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                li = dl.Listener([], dl.PiAdapter("m"), Path(td), mode=mode)
                li.queue.put(("bot", {"message_id": "m", "content": "1", "source": "stream"}))
                li.queue.put(("bot", dl.normalize_poll_message({"messageId": "m", "text": "1"})))
                li.queue.put(("bot", {"message_id": "notice", "content": dl.NOTICE_PREFIX + " Bug #1"}))
                li.stop_flag.set()
                with patch.object(dl, "extract_bug_intent", return_value={"is_bugfix": True, "bug_id": "1"}) as extract, patch.object(dl, "fetch_resolution", return_value={"resolution": "set"}) as query, patch.object(dl, "_run_auto_fix") as fix, patch.object(li.notifier, "publish", return_value={"sent": True}) as notice:
                    li._worker()
                self.assertEqual(extract.call_count, 1)
                self.assertEqual(query.call_count, 1)
                self.assertEqual(notice.call_count, 1)
                self.assertEqual(li.stats["skipped"], 1)
                self.assertEqual(li.stats["fix_fail"], 0)
                self.assertTrue(li.stats["last_fix"]["notification"]["sent"])
                fix.assert_not_called()

    def test_worker_success_and_failure_always_publish(self):
        from unittest.mock import patch
        for outcome in ({"ok": True, "status": "committed"}, {"ok": False, "status": "blocked"}):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as td:
                li = dl.Listener([], dl.PiAdapter("m"), Path(td))
                li.queue.put(("bot", {"message_id": "m", "content": "1"}))
                li.stop_flag.set()
                with patch.object(dl, "extract_bug_intent", return_value={"is_bugfix": True, "bug_id": "1"}), patch.object(dl, "run_auto_fix", return_value=outcome), patch.object(li.notifier, "publish", return_value={"sent": False}) as notice:
                    li._worker()
                self.assertEqual(notice.call_count, 1)
                self.assertEqual(li.stats["fix_ok"], int(outcome["ok"]))
                self.assertEqual(li.stats["fix_fail"], int(not outcome["ok"]))
                self.assertEqual(li.stats["last_fix"]["ok"], outcome["ok"])

    def test_extraction_failure_notifies_without_raw_message(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            li = dl.Listener([], dl.PiAdapter("m"), Path(td))
            li.queue.put(("bot", {"message_id": "m", "content": "SECRET"}))
            li.stop_flag.set()
            with patch.object(dl, "extract_bug_intent", side_effect=RuntimeError("extract failed")), patch.object(li.notifier, "publish", return_value={"sent": True}) as notice:
                li._worker()
            self.assertEqual(notice.call_args.args[0]["status"], "intent_failed")
            self.assertNotIn("SECRET", str(notice.call_args))

    def test_waiting_resume_notifies_completion(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            li = dl.Listener([], dl.PiAdapter("m"), Path(td))
            pending = ["1"]
            with patch.object(dl, "run_auto_fix", return_value={"ok": True, "status": "committed"}), patch.object(li.notifier, "publish", return_value={"sent": True}) as notice:
                li._retry_waiting(pending, Path(td) / "pending.json")
            self.assertEqual(pending, [])
            self.assertEqual(notice.call_args.args[0]["bug_id"], "1")
            self.assertEqual(li.stats["fix_ok"], 1)

    def test_atomic_claim_across_threads(self):
        import threading
        with tempfile.TemporaryDirectory() as td:
            store = dl.DedupStore(Path(td) / "ids.json")
            results = []
            threads = [threading.Thread(target=lambda: results.append(store.claim("m"))) for _ in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(results.count(True), 1)
            self.assertFalse(dl.DedupStore(store.path).claim("m"))


class TestCreationFlags(unittest.TestCase):
    def test_no_window_flag(self):
        """Windows 下必须返回 CREATE_NO_WINDOW(不弹黑窗)，其他平台为 0。"""
        self.assertEqual(dl.creation_flags(), 0x08000000 if os.name == "nt" else 0)
        self.assertIsInstance(dl.creation_flags(), int)


class TestPollFallback(unittest.TestCase):
    def test_normalize(self):
        m = {"sender": "李四", "senderId": "oid-1", "text": "修 bug 12345",
             "messageId": "m1", "conversationId": "c1", "createTime": "2026-09-19 21:00:00"}
        ev = dl.normalize_poll_message(m)
        self.assertEqual(ev["content"], "修 bug 12345")      # 事件同构字段
        self.assertEqual(ev["sender_open_dingtalk_id"], "oid-1")
        self.assertEqual(ev["source"], "poll")

    def test_norm_ts_formats(self):
        """时间归一化：空格/ISO/毫秒/时区/epoch 均可比较；垃圾输入返回空。"""
        self.assertEqual(dl._norm_ts("2026-09-19 21:00:00"), "20260919210000000000")
        self.assertEqual(dl._norm_ts("2026-09-19T21:00:00.5Z"), "20260919210000500000")
        self.assertEqual(dl._norm_ts("2026-09-19T21:00:00.123+08:00"), "20260919210000123000")
        self.assertEqual(dl._norm_ts(""), "")
        self.assertEqual(dl._norm_ts(None), "")
        self.assertEqual(dl._norm_ts("不是时间"), "")
        self.assertEqual(dl._norm_ts("1760000000123"),
                         dl._epoch_to_norm(1760000000))          # epoch 毫秒

    def test_pick_new_by_cutoff_window(self):
        """窗口重扫语义：≥cutoff 的都返回（去重由 DedupStore 负责），正序排列。"""
        msgs = [{"createTime": "2026-09-19 20:47:16", "messageId": "a"},
                {"createTime": "2026-09-19T21:05:00.250+08:00", "messageId": "b"},
                {"createTime": "2026-09-19 21:10:00", "messageId": "c"},
                {"createTime": "", "messageId": "d"}]
        cutoff = dl._epoch_to_norm(dl._norm_to_epoch("20260919210000000000"))
        fresh = dl.pick_new_poll_messages(msgs, cutoff)
        self.assertEqual([m["messageId"] for m in fresh], ["b", "c"])   # ≥cutoff+正序，格式混用也可比

    def test_cutoff_epoch_clamping(self):
        now = 1760000000
        # 无水位：窗口 = 过去 lookback
        self.assertEqual(dl.poll_cutoff_epoch("", now=now, lookback_sec=600, max_catchup_sec=3600),
                         now - 600)
        # 水位在 lookback 与 max_catchup 之间：窗口前探到水位（停机补漏）
        wm = dl._epoch_to_norm(now - 1200)
        self.assertEqual(dl.poll_cutoff_epoch(wm, now=now, lookback_sec=600, max_catchup_sec=3600),
                         now - 1200)
        # 水位过旧：被 max_catchup 托底，防远古消息重放
        wm_old = dl._epoch_to_norm(now - 86400)
        self.assertEqual(dl.poll_cutoff_epoch(wm_old, now=now, lookback_sec=600, max_catchup_sec=3600),
                         now - 3600)
        # 坏水位容忍：当作无水位
        self.assertEqual(dl.poll_cutoff_epoch("garbage", now=now, lookback_sec=600,
                                              max_catchup_sec=3600), now - 600)

    def test_rfc3339_local_whole_seconds(self):
        """--start 参数必须是本地时区 RFC3339 整秒（dws 只接受整秒边界）。"""
        s = dl._fmt_local_rfc3339(1760000000)
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")

    def test_poll_messages_window_args_and_fallback(self):
        """带时间窗时用 --start/--order asc；旧版 dws 报错可降级；信封兼容两种形态。"""
        calls = []
        orig = dl.run_dws

        def fake(args, timeout=60):
            calls.append(list(args))
            if "--start" in args:
                raise RuntimeError("unknown flag: --start")
            return json.dumps({"result": {"messages": [
                {"messageId": "m1", "text": "x", "createTime": "2026-09-19 21:00:00"}]}})
        try:
            dl.run_dws = fake
            with self.assertRaises(RuntimeError):
                dl.poll_messages("oid-1", start_epoch=1760000000)   # 现代路径失败即抛，由调用方降级
            msgs = dl.poll_messages("oid-1")                        # 降级路径（无时间窗）
            self.assertEqual(msgs[0]["messageId"], "m1")
            self.assertIn("--start", calls[0])
            self.assertIn("asc", calls[0])
            self.assertNotIn("--start", calls[1])
        finally:
            dl.run_dws = orig

    def test_poll_state_merge(self):
        """多目标水位读-改-写合并不互相关覆盖。"""
        old = dl.POLL_STATE_FILE
        try:
            with tempfile.TemporaryDirectory() as td:
                dl.POLL_STATE_FILE = Path(td) / "poll-state.json"
                dl._save_poll_state("甲", "20260919210000000000")
                dl._save_poll_state("乙", "20260919220000000000")
                st = dl._load_poll_states()
                self.assertEqual(st["甲"], "20260919210000000000")
                self.assertEqual(st["乙"], "20260919220000000000")
        finally:
            dl.POLL_STATE_FILE = old

    def test_mode_validation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r"
            (repo / ".git").mkdir(parents=True)
            import importlib
            with self.assertRaises(SystemExit):
                dl.Listener([("李四", "oid", "user")], dl.PiAdapter("m"), repo, None, "bad-mode")

    def test_poll_params_validation(self):
        """轮询参数：缺省用默认值，非法值报配置错（退出码 2 路径）。"""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r"
            (repo / ".git").mkdir(parents=True)
            li = dl.Listener([("李四", "oid", "user")], dl.PiAdapter("m"), repo)
            self.assertEqual(li.poll_lookback_min, dl.POLL_LOOKBACK_MIN)
            self.assertEqual(li.poll_max_catchup_min, dl.POLL_MAX_CATCHUP_MIN)
            self.assertEqual(li.poll_interval, dl.POLL_INTERVAL)
            with self.assertRaises(SystemExit):
                dl.Listener([("李四", "oid", "user")], dl.PiAdapter("m"), repo,
                            None, "auto", None, "abc", None)
            with self.assertRaises(SystemExit):
                dl.Listener([("李四", "oid", "user")], dl.PiAdapter("m"), repo,
                            None, "auto", None, "0", None)


class TestAutostart(unittest.TestCase):
    """开机自启模块：纯函数与开关逻辑（不碰真实系统计划任务/crontab）。"""

    def test_entry_defaults(self):
        e = dl._autostart_entry()
        self.assertEqual(e["args"], ["start", "--foreground"])
        self.assertTrue(e["script"].endswith("dingtalk_listen.py"))
        self.assertEqual(e["workspace"], str(dl.BASE_DIR))
        self.assertTrue(Path(e["python"]).name.startswith("python"))

    def test_ps_quote(self):
        self.assertEqual(dl._ps_quote("C:\\a b.py"), "'C:\\a b.py'")
        self.assertEqual(dl._ps_quote("it's"), "'it''s'")

    def test_win_ps_command(self):
        e = {"python": "C:\\py\\pythonw.exe", "script": "C:\\s p\\dingtalk_listen.py",
             "args": ["start", "--foreground"], "workspace": "C:\\ws dir"}
        ps = dl._win_ps_command(e)
        self.assertIn("-AtLogOn -User $u", ps)             # 当前用户登录触发
        self.assertIn("-AtStartup", ps)                    # 开机触发
        self.assertIn("-LogonType Interactive", ps)         # 保留用户网络凭据
        self.assertNotIn("-LogonType S4U", ps)
        self.assertIn("-Principal $p", ps)
        self.assertIn("-StartWhenAvailable", ps)
        self.assertIn("-RestartCount 3", ps)
        self.assertIn("-RestartInterval (New-TimeSpan -Minutes 1)", ps)
        self.assertIn("-MultipleInstances IgnoreNew", ps)
        self.assertIn("-ExecutionTimeLimit ([TimeSpan]::Zero)", ps)  # 无 72h 时限
        self.assertIn("-WorkingDirectory 'C:\\ws dir'", ps)
        self.assertIn("-Argument '\"C:\\s p\\dingtalk_listen.py\" start --foreground'", ps)
        self.assertIn("-TaskName '%s'" % dl.AUTOSTART_NAME, ps)
        self.assertIn("-Force", ps)                         # 幂等覆盖

    def test_mac_plist_xml(self):
        e = {"python": "/usr/bin/python3", "script": "/opt/space dir/dl.py",
             "args": ["start", "--foreground"], "workspace": "/Users/x/ws & ops"}
        xml = dl._mac_plist_xml(e)
        self.assertIn("<string>%s</string>" % dl.AUTOSTART_LABEL, xml)
        self.assertIn("<string>/usr/bin/python3</string>", xml)
        self.assertIn("<string>/opt/space dir/dl.py</string>", xml)
        self.assertIn("<string>start</string>", xml)
        self.assertIn("<key>RunAtLoad</key>\n    <true/>", xml)
        self.assertIn("<key>KeepAlive</key>\n    <false/>", xml)
        self.assertIn("<string>/Users/x/ws &amp; ops</string>", xml)  # XML 转义

    def test_linux_unit_content(self):
        e = {"python": "/usr/bin/python3", "script": "/opt/space dir/dl.py",
             "args": ["start", "--foreground"], "workspace": "/home/x/ws dir"}
        u = dl._linux_unit_content(e)
        self.assertIn("WorkingDirectory=/home/x/ws dir", u)
        self.assertIn("ExecStart=/usr/bin/python3 '/opt/space dir/dl.py'"
                      " start --foreground", u)
        self.assertIn("Restart=on-failure", u)
        self.assertIn("WantedBy=default.target", u)

    def test_linux_cron_entry(self):
        e = {"python": "/usr/bin/python3", "script": "/opt/space dir/dl.py",
             "args": ["start", "--foreground"], "workspace": "/home/x/ws dir"}
        line = dl._linux_cron_entry(e)
        self.assertTrue(line.startswith("@reboot cd '/home/x/ws dir' &&"))
        self.assertIn("'/opt/space dir/dl.py' start --foreground", line)
        self.assertIn("cron.out", line)

    def test_cron_strip_managed(self):
        foreign = ["0 9 * * * /usr/bin/backup", "# user comment"]
        lines = foreign + ["", dl.CRON_BEGIN, "@reboot old-entry", dl.CRON_END, "", "kept"]
        # 块内条目移除，块外的空行保留（仅收尾空行会被清理）
        self.assertEqual(dl._cron_strip_managed(lines),
                         foreign + ["", "", "kept"])
        self.assertEqual(dl._cron_strip_managed(foreign), foreign)   # 无托管块不动
        self.assertEqual(dl._cron_strip_managed([]), [])
        self.assertEqual(dl._cron_strip_managed([dl.CRON_BEGIN, "x", dl.CRON_END]), [])
        # 块在末尾且后有尾随空行 → 清理尾随空行
        self.assertEqual(dl._cron_strip_managed(foreign + ["", dl.CRON_BEGIN, "x", dl.CRON_END, "", ""]),
                         foreign)

    def test_ensure_autostart_switches(self):
        import argparse
        args = argparse.Namespace(no_autostart=False)
        called = []
        orig = dl.autostart_install
        dl.autostart_install = lambda: called.append(1) or {"installed": True}
        try:
            dl._ensure_autostart(args, {"LISTEN_AUTOSTART": "off"})
            self.assertEqual(called, [])                    # off → 不创建
            args.no_autostart = True
            dl._ensure_autostart(args, {})
            self.assertEqual(called, [])                    # --no-autostart → 不创建
            args.no_autostart = False
            dl._ensure_autostart(args, {})                  # 默认 → 创建
            self.assertEqual(called, [1])
            dl._ensure_autostart(args, {"LISTEN_AUTOSTART": "ON"})
            self.assertEqual(called, [1, 1])                # 大小写不敏感
        finally:
            dl.autostart_install = orig

    def test_ensure_autostart_install_failure_not_fatal(self):
        import argparse
        args = argparse.Namespace(no_autostart=False)

        def boom():
            raise RuntimeError("no permission")
        orig = dl.autostart_install
        dl.autostart_install = boom
        try:
            dl._ensure_autostart(args, {})                  # 创建失败不抛出（不影响监听）
        finally:
            dl.autostart_install = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
