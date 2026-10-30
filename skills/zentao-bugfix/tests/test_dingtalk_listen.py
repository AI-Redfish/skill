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

    def test_listener_name_list_no_longer_required(self):
        """监听名单校验已随监听器移除：missing_keys 只看禅道必需键。"""
        self.assertEqual(dl.missing_keys({"ZENTAO_BASE_URL": "http://x", "ZENTAO_ACCOUNT": "a",
                                          "ZENTAO_PASSWORD": "p"}), [])

    def test_bots_only_allowed(self):
        """只监听机器人时 DWS_LISTEN_USERS 可留空（真实部署场景）。"""
        cfg = {"ZENTAO_BASE_URL": "u", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "p",
               "DWS_LISTEN_BOTS": "通知机器人"}
        self.assertEqual(dl.missing_keys(cfg), [])

    def test_no_targets_at_all(self):
        """监听名单校验已随监听器移除：禅道必需键齐全即视为完整。"""
        cfg = {"ZENTAO_BASE_URL": "u", "ZENTAO_ACCOUNT": "a", "ZENTAO_PASSWORD": "p"}
        self.assertEqual(dl.missing_keys(cfg), [])

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

    def test_uncertain_cause_prompt_precedes_normal_flow(self):
        prepared = {"mode": "inplace", "project": "/repo",
                    "workspace": "/dev", "report_dir": "/reports"}
        for context in (None, prepared):
            with self.subTest(prepared=bool(context)):
                prompt = dl.build_fix_prompt("101", prepared=context)
                self.assertTrue(prompt.startswith("根因待确认分支优先"))
                for requirement in ("操作、配置、数据、环境", "暂停代码、配置和数据修改",
                                    "不调用 ready/finish", "包括 --no-change",
                                    "不释放或删除锁", "**排查状态**: 等待用户补充",
                                    "检查位置/只读操作", "预期结果与判定依据",
                                    "最小必需/可选资料", "采集方法", "时间范围",
                                    "脱敏要求", "在对话中告知", "恢复条件",
                                    "未修改代码、未修复", "已确认"):
                    self.assertIn(requirement, prompt)


class TestRoutedRuns(unittest.TestCase):
    def test_waiting_for_evidence_never_counts_as_success(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            rd = repo / "reports"
            rd.mkdir()
            rec = {"run_id": "current", "report_dir": str(rd),
                   "workspace": str(repo), "validation": {"returncode": 0}}
            dl._routes.save(rd / "meta.json", {"run_id": "current"})
            for name in ("solution.md", "fix-report.md"):
                (rd / name).write_text("暂停代码修改，等待补充；未修复", encoding="utf-8")
            for mode in ("worktree", "inplace"):
                for status in ("prepared", "no_change"):
                    with self.subTest(mode=mode, status=status):
                        rec.update(mode=mode, status=status)
                        dl._routes.save(dl._routes.record_path(repo, "1"), rec)
                        (rd / "analysis.md").write_text(
                            "## 2. 问题归属\n\n**结论**: 待确认\n"
                            "**排查状态**: 等待用户补充\n", encoding="utf-8")
                        dl._routes._reports.render_reports(rd, require_complete=True)
                        result = dl.verify_run("1", repo, "current")
                        self.assertFalse(result["ok"])
                        self.assertTrue(result["awaiting_evidence"])
                        self.assertEqual(result["status"], "awaiting_evidence")
                        self.assertTrue(result["analysis_complete"])
                        self.assertTrue(all(result["html_complete"].values()))
                        self.assertIsNotNone(result["report_html"])
            # 非代码问题确认后，允许现有经验证 no_change 流程正常结束。
            (rd / "analysis.md").write_text(
                "## 2. 问题归属\n\n**结论**: 待确认\n"
                "**排查状态**: 已确认\n\n## 5. 根因分析\n配置原因已验证，无需代码修改。\n",
                encoding="utf-8")
            dl._routes._reports.render_reports(rd, require_complete=True)
            result = dl.verify_run("1", repo, "current")
            self.assertTrue(result["ok"])
            self.assertFalse(result["awaiting_evidence"])
            self.assertEqual(result["status"], "no_change")

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
    def test_awaiting_evidence_notification_is_actionable_and_redacted(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            notifier = dl.ResultNotifier(Path(td) / "outbox.json")
            notifier.recipient = {"user_id": "me", "corp_id": "corp"}
            result = {"bug_id": "1", "ok": False, "status": "awaiting_evidence",
                      "report_dir": "/reports/1", "report_html": "/reports/1/fix-report.html",
                      "error": "SECRET raw Bug text"}
            with patch.object(dl, "run_dws", return_value='{"success":true}') as send:
                self.assertTrue(notifier.publish(result, "message:evidence")["sent"])
                args = send.call_args.args[0]
                text = args[args.index("--text") + 1]
                for expected in ("等待补充资料", "已暂停修改，未修复", "排查步骤",
                                 "最小资料清单", "脱敏数据及环境信息", "/reports/1"):
                    self.assertIn(expected, text)
                self.assertNotIn("处理成功", text)
                self.assertNotIn("SECRET", text)

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

class TestCreationFlags(unittest.TestCase):
    def test_no_window_flag(self):
        """Windows 下必须返回 CREATE_NO_WINDOW(不弹黑窗)，其他平台为 0。"""
        self.assertEqual(dl.creation_flags(), 0x08000000 if os.name == "nt" else 0)
        self.assertIsInstance(dl.creation_flags(), int)


class TestSingleShotEntries(unittest.TestCase):
    """单次执行入口：poll-once / fix-from-message（触发外移 AgentR 工作流后的替代能力）。"""

    class Args:
        def __init__(self, limit=50, text=("",), agent="", model=""):
            self.limit, self.text, self.agent, self.model = limit, text, agent, model

    @staticmethod
    def _config():
        return {"ZENTAO_BASE_URL": "http://x", "ZENTAO_ACCOUNT": "a",
                "ZENTAO_PASSWORD": "p", "BUGFIX_BASE_BRANCH": ""}

    class FakeNotifier:
        def bind_current_user(self):
            pass

        def publish(self, result, key):
            return {"sent": True}

    def setUp(self):
        self._saved = {name: getattr(dl, name) for name in
                       ("_list_open_bug_ids", "run_auto_fix", "resolve_repo",
                        "load_config", "extract_bug_intent", "ResultNotifier", "build_adapter")}
        dl.resolve_repo = lambda cfg: Path(".")
        dl.load_config = lambda path=None: self._config()
        dl.ResultNotifier = self.FakeNotifier
        dl.build_adapter = lambda cfg, args: object()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(dl, name, value)

    def test_poll_once_filters_resolved_and_reports_failure_exit_code(self):
        bugs = [{"id": "101", "title": "A", "resolution": None},
                {"id": "102", "title": "B", "resolution": "fixed"},
                {"id": "103", "title": "C", "resolution": ""}]
        dl._list_open_bug_ids = lambda cfg, limit=100: bugs
        fixes = []

        def fake_fix(adapter, bug_id, repo, base=None, reuse=False):
            fixes.append(bug_id)
            return {"bug_id": bug_id, "ok": bug_id == "101",
                    "status": "done" if bug_id == "101" else "blocked",
                    "error": None if bug_id == "101" else "boom"}
        dl.run_auto_fix = fake_fix
        code = dl.cmd_poll_once(self.Args(limit=50))
        self.assertEqual(fixes, ["101", "103"])      # resolved 的 102 不进修复
        self.assertEqual(code, 1)                    # 103 失败 → 退出码 1

    def test_poll_once_all_ok_exit_zero(self):
        dl._list_open_bug_ids = lambda cfg, limit=100: [{"id": "201", "title": "X", "resolution": ""}]
        dl.run_auto_fix = lambda adapter, bug_id, repo, base=None, reuse=False: {
            "bug_id": bug_id, "ok": True, "status": "done"}
        self.assertEqual(dl.cmd_poll_once(self.Args(limit=10)), 0)

    def test_poll_once_config_missing_exits(self):
        dl.load_config = lambda path=None: {}
        with self.assertRaises(SystemExit):
            dl.cmd_poll_once(self.Args())

    def test_fix_from_message_non_bug_does_not_fix(self):
        dl.extract_bug_intent = lambda adapter, sender, text: {
            "is_bugfix": False, "bug_id": None, "reason": "chat"}
        dl.run_auto_fix = lambda *a, **k: self.fail("非 bug 消息不应触发修复")
        self.assertEqual(dl.cmd_fix_from_message(self.Args(text=["今天天气不错"])), 0)

    def test_fix_from_message_bug_triggers_fix(self):
        dl.extract_bug_intent = lambda adapter, sender, text: {
            "is_bugfix": True, "bug_id": "308", "reason": ""}
        calls = []
        dl.run_auto_fix = lambda adapter, bug_id, repo, base=None, reuse=False: (
            calls.append(bug_id) or {"bug_id": bug_id, "ok": True, "status": "done"})
        self.assertEqual(dl.cmd_fix_from_message(self.Args(text=["修一下 bug 308"])), 0)
        self.assertEqual(calls, ["308"])


if __name__ == "__main__":
    unittest.main()
