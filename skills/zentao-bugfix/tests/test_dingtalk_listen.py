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
# 模块常量（ENV_FILE/LOG_DIR）在 import 时锥定 cwd：测试进程先切到临时目录，
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
            p = Path(td) / ".agents" / ".env"
            dl.save_env(p, {"A": "1"})
            dl.save_env(p, {"A": "2", "B": "x=y"})     # 覆盖 + 值含等号
            cfg = dl.load_env(p)
            self.assertEqual(cfg["A"], "2")
            self.assertEqual(cfg["B"], "x=y")

    def test_comments_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "e.env"
            p.write_text("# 注释\nK=1\n", encoding="utf-8")
            dl.save_env(p, {"K": "9"})
            self.assertIn("# 注释", p.read_text(encoding="utf-8"))
            self.assertEqual(dl.load_env(p)["K"], "9")


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


class TestSyncZentaoEnv(unittest.TestCase):
    def test_sync_and_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            old = dl.ENV_FILE
            try:
                src = Path(td) / "skill.env"
                dl.save_env(src, {"ZENTAO_BASE_URL": "http://z", "ZENTAO_ACCOUNT": "a",
                                  "ZENTAO_PASSWORD": "p"})
                dl.ENV_FILE = src
                repo = Path(td) / "repo"
                (repo / ".git").mkdir(parents=True)
                dl.sync_zentao_env_to_repo(repo)
                cfg = dl.load_env(repo / ".agents" / ".env")
                self.assertEqual(cfg["ZENTAO_BASE_URL"], "http://z")
                self.assertIn(".agents/.env", (repo / ".gitignore").read_text(encoding="utf-8"))
                # 二次同步不重复追加 gitignore
                dl.sync_zentao_env_to_repo(repo)
                text = (repo / ".gitignore").read_text(encoding="utf-8")
                self.assertEqual(text.count(".agents/.env"), 1)
            finally:
                dl.ENV_FILE = old


class TestResolveRepo(unittest.TestCase):
    def test_env_priority_over_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r"
            (repo / ".git").mkdir(parents=True)
            got = dl.resolve_repo({"TARGET_PROJECT_PATH": str(repo)})
            self.assertEqual(got, repo.resolve())


class TestEnvLocation(unittest.TestCase):
    """配置/日志锥定启动工作空间，不锥 skill 目录；旧位置只读兑底 + 自动迁移。"""

    def test_anchors_to_cwd_not_skill_dir(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                spec2 = importlib.util.spec_from_file_location("dl_reload", SCRIPT)
                dl2 = importlib.util.module_from_spec(spec2)
                spec2.loader.exec_module(dl2)
                base = Path(td).resolve()
                self.assertEqual(dl2.ENV_FILE, base / ".agents" / ".env")
                self.assertEqual(dl2.LOG_DIR, base / ".agents" / "logs")
                # 不落在 skill 目录内（安装到 <工作空间>/.agents/skills/ 时会嵌套 .agents）
                self.assertNotEqual(dl2.ENV_FILE, dl2.LEGACY_ENV_FILE)
                self.assertFalse(str(dl2.ENV_FILE).startswith(
                    str(dl2.SKILL_DIR / ".agents")))
            finally:
                os.chdir(old_cwd)

    def test_legacy_readonly_fallback_and_migration(self):
        with tempfile.TemporaryDirectory() as td:
            old_env, old_legacy = dl.ENV_FILE, dl.LEGACY_ENV_FILE
            try:
                legacy = Path(td) / "legacy" / ".agents" / ".env"
                legacy.parent.mkdir(parents=True)
                legacy.write_text("A=1\n# 注释\n", encoding="utf-8")
                dl.LEGACY_ENV_FILE = legacy
                dl.ENV_FILE = Path(td) / "ws" / ".agents" / ".env"
                # 新位置不存在 → 只读兑底读旧位置
                self.assertEqual(dl.load_env(), {"A": "1"})
                self.assertFalse(dl.ENV_FILE.is_file())
                # 迁移：整体拷贝到工作空间，旧文件保留
                dl.migrate_legacy_env()
                self.assertTrue(dl.ENV_FILE.is_file())
                self.assertIn("# 注释", dl.ENV_FILE.read_text(encoding="utf-8"))
                self.assertTrue(legacy.is_file())
                # 迁移后新位置生效，不再走兑底
                dl.save_env(dl.ENV_FILE, {"B": "2"})
                cfg = dl.load_env()
                self.assertEqual(cfg, {"A": "1", "B": "2"})
            finally:
                dl.ENV_FILE, dl.LEGACY_ENV_FILE = old_env, old_legacy

    def test_new_env_wins_over_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            old_env, old_legacy = dl.ENV_FILE, dl.LEGACY_ENV_FILE
            try:
                legacy = Path(td) / "legacy.env"
                legacy.write_text("OLD=1\n", encoding="utf-8")
                new = Path(td) / ".agents" / ".env"
                new.parent.mkdir(parents=True)
                new.write_text("NEW=1\n", encoding="utf-8")
                dl.LEGACY_ENV_FILE, dl.ENV_FILE = legacy, new
                self.assertEqual(dl.load_env(), {"NEW": "1"})   # 新位置优先，不合并旧键
                # 新位置已存在时迁移不覆盖
                legacy.write_text("OLD=2\n", encoding="utf-8")
                dl.migrate_legacy_env()
                self.assertEqual(new.read_text(encoding="utf-8"), "NEW=1\n")
            finally:
                dl.ENV_FILE, dl.LEGACY_ENV_FILE = old_env, old_legacy


class TestMissingAndMask(unittest.TestCase):
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
            rd = wt / ".agents" / "bugfix" / "75042"
            rd.mkdir(parents=True)
            (rd / "meta.json").write_text("{}", encoding="utf-8")
            v = dl.verify_fix("75042", repo)
            self.assertTrue(v["ok"])
            self.assertEqual(v["worktree"], str(wt))
            self.assertIsNone(v["report"])          # 尚无 fix-report.md
            (rd / "fix-report.md").write_text("x", encoding="utf-8")
            self.assertTrue(dl.verify_fix("75042", repo)["report"].endswith("fix-report.md"))

    def test_worktree_without_meta_not_counted(self):
        """同名目录但无 meta.json（残留/伪造）不算 prepare 成功。"""
        with tempfile.TemporaryDirectory() as td:
            repo = self._mk_repo(td)
            (repo.parent / "bugfix_75042_20260920").mkdir()
            self.assertFalse(dl.verify_fix("75042", repo)["ok"])


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

    def test_pick_new_by_watermark(self):
        msgs = [{"createTime": "2026-09-19 20:47:16", "messageId": "a"},
                {"createTime": "2026-09-19 21:05:00", "messageId": "b"},
                {"createTime": "2026-09-19 21:10:00", "messageId": "c"}]
        fresh = dl.pick_new_poll_messages(msgs, "2026-09-19 21:00:00")
        self.assertEqual([m["messageId"] for m in fresh], ["b", "c"])   # 严格大于+正序

    def test_mode_validation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r"
            (repo / ".git").mkdir(parents=True)
            import importlib
            with self.assertRaises(SystemExit):
                dl.Listener([("李四", "oid", "user")], dl.PiAdapter("m"), repo, None, "bad-mode")


if __name__ == "__main__":
    unittest.main(verbosity=2)
