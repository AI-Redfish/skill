"""create-pr / auto_pr 集成测试：真实临时 Git 仓库 + 本地 bare 远程，无网络、无 gh。"""
import contextlib
import importlib.util
import io
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("routed_bugfix", SCRIPTS / "bugfix.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)
r = bf._routes

FAKE_PR_CMD = shlex.quote(sys.executable) + ' -c "import sys; print(\'https://git.example/pr/77\')"'
INIT_RESULT = {"status": "ok", "skills": [], "skills_failed": [], "prompt_files": 0,
               "prompt_failed": [], "errors": []}


def git(repo, *args):
    return r.text(repo, *args)


class AutoPrTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        # 本地 bare 远程，模拟 origin；push/分支检查全部走本地路径。
        self.remote = base / "remote.git"
        self.remote.mkdir()
        git(base, "init", "-b", "main", "--bare", str(self.remote))
        # 绑定工作区（inplace 目标）。
        self.workspace = base / "work"
        self.workspace.mkdir()
        git(self.workspace, "init", "-b", "main")
        git(self.workspace, "config", "user.name", "Test")
        git(self.workspace, "config", "user.email", "test@example.test")
        (self.workspace / "one.txt").write_text("initial\n", encoding="utf-8")
        git(self.workspace, "add", ".")
        git(self.workspace, "commit", "-m", "initial")
        git(self.workspace, "remote", "add", "origin", str(self.remote))
        git(self.workspace, "push", "-u", "origin", "main")
        # 分流项目：bug_id 101 → 绑定工作区，auto_pr=true。
        self.project = base / "proj"
        self.project.mkdir()
        self.rules([{"name": "订单", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True}])

    def rules(self, rules, config=None):
        r.save(r.config_path(self.project), {"config": config or {}, "rules": rules})

    def prepare(self, bug="101", title="ORDER failure", reuse=False, worktree_env=False):
        cache = self.project / ".agents" / "bugfix-work" / bug
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "bug.md").write_text("# Bug\n- **标题**: " + title, encoding="utf-8")
        args = SimpleNamespace(project=str(self.project), bug_id=bug, base_branch=None,
                               reuse=reuse, force=False, current_workspace=str(self.project))
        fetch = ({"title": title}, [], [], str(cache), "https://zentao.test", "bug")
        def run():
            with patch.object(bf, "fetch_bug_full", return_value=fetch), \
                 contextlib.redirect_stdout(io.StringIO()):
                return bf.cmd_prepare(args)
        if worktree_env:
            # 跳过 worktree 环境初始化的 GitHub 下载（已在单元测试中单独覆盖）。
            with patch.object(bf, "init_worktree_env", return_value=dict(INIT_RESULT)):
                return run()
        return run()

    def docs(self, bug="101"):
        rec = r.load_record(self.project, bug)
        for name in ("analysis.md", "solution.md", "fix-report.md"):
            (Path(rec["report_dir"]) / name).write_text("完整的分析、方案或验证记录", encoding="utf-8")
        r.ready(self.project, bug)
        return rec

    # ---------- 分流规则 ----------

    def test_select_returns_rule_auto_pr_and_validates_type(self):
        self.assertEqual(r.select(self.project, "101", "Order")["auto_pr"], True)
        self.rules([{"name": "关", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": False}])
        self.assertEqual(r.select(self.project, "101", "Order")["auto_pr"], False)
        self.rules([{"name": "缺省", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main"}])
        self.assertIsNone(r.select(self.project, "101", "Order")["auto_pr"])
        self.rules([{"name": "坏", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": "on"}])
        with self.assertRaises(r.RouteError):
            r.select(self.project, "101", "Order")

    def test_same_target_rules_use_first_hit_auto_pr(self):
        self.rules([{"name": "a", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True},
                    {"name": "b", "match": {"title_contains": "order"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": False}])
        self.assertEqual(r.select(self.project, "101", "ORDER")["auto_pr"], True)

    # ---------- inplace：finish 后按规则发起 PR ----------

    def test_inplace_pr_after_finish_push_and_report_update(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n", encoding="utf-8")
        check = shlex.quote(sys.executable) + ' -c "print(123)"'
        result = r.finish(self.project, "101", ["one.txt"], check)
        self.assertEqual(result["status"], "committed")
        self.rules([{"name": "订单", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True}],
                   config={"AUTO_PR_CMD": FAKE_PR_CMD})
        pr = r.create_pr(self.project, "101")
        self.assertEqual(pr["status"], "created")
        self.assertEqual(pr["url"], "https://git.example/pr/77")
        self.assertEqual(pr["backend"], "custom")
        self.assertEqual(pr["head"], "main")
        # 分支已推送到远端
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/main"), result["commit"])
        # 幂等：重复执行回显已有 PR，不再调用创建命令
        again = r.create_pr(self.project, "101")
        self.assertEqual(again["status"], "exists")
        self.assertEqual(again["url"], "https://git.example/pr/77")
        # 报告与运行记录落盘
        rec = r.load_record(self.project, "101")
        self.assertEqual(rec["pr"]["url"], "https://git.example/pr/77")
        report = Path(rec["report_dir"])
        self.assertIn("## Pull Request", (report / "fix-report.md").read_text(encoding="utf-8"))
        self.assertIn("git.example/pr/77", (report / "fix-report.html").read_text(encoding="utf-8"))
        self.assertEqual(r.read(report / "meta.json")["pr"]["url"], "https://git.example/pr/77")

    def test_inplace_pr_requires_finished_commit(self):
        self.prepare()
        self.rules([{"name": "订单", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True}],
                   config={"AUTO_PR_CMD": FAKE_PR_CMD})
        with self.assertRaisesRegex(r.RouteError, "finish"):
            r.create_pr(self.project, "101")

    def test_disabled_auto_pr_stops_force_overrides_and_config_fallback(self):
        # 规则显式关闭（prepare 时快照进运行记录）、config 也没开 → 拒绝发起
        disabled = {"name": "订单", "match": {"bug_id": "101"},
                    "workspace": str(self.workspace), "target_branch": "main",
                    "auto_pr": False}
        self.rules([disabled])
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n", encoding="utf-8")
        check = shlex.quote(sys.executable) + ' -c "print(123)"'
        r.finish(self.project, "101", ["one.txt"], check)
        with self.assertRaisesRegex(r.RouteError, "auto_pr 未开启"):
            r.create_pr(self.project, "101")
        # --force 人工确认后可强制发起
        self.rules([disabled], config={"AUTO_PR_CMD": FAKE_PR_CMD})
        pr = r.create_pr(self.project, "101", force=True)
        self.assertEqual(pr["status"], "created")
        # 规则缺省 auto_pr 时回退 config AUTO_PR=on
        self.rules([{"name": "订单二", "match": {"bug_id": "105"},
                     "workspace": str(self.workspace), "target_branch": "main"}],
                   config={"AUTO_PR": "on", "AUTO_PR_CMD": FAKE_PR_CMD})
        self.prepare("105")
        self.docs("105")
        (self.workspace / "two.txt").write_text("fixed 105\n", encoding="utf-8")
        r.finish(self.project, "105", ["two.txt"], check)
        pr = r.create_pr(self.project, "105")
        self.assertEqual(pr["status"], "created")

    def test_incomplete_reports_block_pr_unless_force(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n", encoding="utf-8")
        check = shlex.quote(sys.executable) + ' -c "print(123)"'
        rec = r.finish(self.project, "101", ["one.txt"], check)
        self.rules([{"name": "订单", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True}],
                   config={"AUTO_PR_CMD": FAKE_PR_CMD})
        # finish 之后报告又被改坏（模拟未补全就发起 PR）→ 拒绝
        (Path(rec["report_dir"]) / "fix-report.md").write_text("还有（待填写）", encoding="utf-8")
        with self.assertRaisesRegex(r.RouteError, "尚未完整落盘"):
            r.create_pr(self.project, "101")
        pr = r.create_pr(self.project, "101", force=True)
        self.assertEqual(pr["status"], "created")

    def test_dry_run_prints_command_without_side_effects(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n", encoding="utf-8")
        check = shlex.quote(sys.executable) + ' -c "print(123)"'
        r.finish(self.project, "101", ["one.txt"], check)
        before = git(self.remote, "rev-parse", "refs/heads/main")
        self.rules([{"name": "订单", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True}],
                   config={"AUTO_PR_CMD": FAKE_PR_CMD, "AUTO_PR_BASE_BRANCH": "release"})
        pr = r.create_pr(self.project, "101", dry_run=True)
        self.assertEqual(pr["status"], "dry_run")
        self.assertIn("https://git.example", " ".join(pr["command"]))
        self.assertEqual(pr["base"], "release")
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/main"), before)
        self.assertIsNone(r.load_record(self.project, "101").get("pr"))

    def test_cli_output_contract(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n", encoding="utf-8")
        check = shlex.quote(sys.executable) + ' -c "print(123)"'
        r.finish(self.project, "101", ["one.txt"], check)
        self.rules([{"name": "订单", "match": {"bug_id": "101"},
                     "workspace": str(self.workspace), "target_branch": "main",
                     "auto_pr": True}],
                   config={"AUTO_PR_CMD": FAKE_PR_CMD})
        args = SimpleNamespace(project=str(self.project), bug_id="101", base=None,
                               title=None, force=False, dry_run=False)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(bf.cmd_create_pr(args), 0)
        text = output.getvalue()
        self.assertIn("PR_STATUS=created", text)
        self.assertIn("PR_URL=https://git.example/pr/77", text)
        self.assertIn("PR_BACKEND=custom", text)

    # ---------- worktree：提交修复变更后发起 PR ----------

    def _worktree_project(self, config):
        """worktree 模式要求 --project 在 git 仓库内；清空规则避免命中绑定。"""
        self.project = self.workspace
        self.rules([], config=config)

    def test_worktree_pr_commits_fix_and_pushes_bugfix_branch(self):
        self._worktree_project({"AUTO_PR": "on", "AUTO_PR_CMD": FAKE_PR_CMD})
        self.prepare(bug="102", title="Unrelated failure", worktree_env=True)
        rec = r.load_record(self.project, "102")
        self.assertEqual(rec["mode"], "worktree")
        wt = Path(rec["workspace"])
        (wt / "fix.txt").write_text("bugfix\n", encoding="utf-8")
        # 根 AGENTS.md（环境初始化模板）不得进入 PR 提交
        (wt / "AGENTS.md").write_text("template\n", encoding="utf-8")
        for name in ("analysis.md", "solution.md", "fix-report.md"):
            (Path(rec["report_dir"]) / name).write_text("完整报告", encoding="utf-8")
        pr = r.create_pr(self.project, "102")
        self.assertEqual(pr["status"], "created")
        self.assertTrue(pr["head"].startswith("bugfix/102_"))
        # 提交信息与范围：只含修复代码，AGENTS.md 与 .agents/ 保持未提交
        self.assertEqual(git(wt, "log", "-1", "--pretty=%s"),
                         "fix(zentao): 修复 Bug #102 Unrelated failure")
        self.assertEqual(git(wt, "diff", "--name-only", "HEAD^", "HEAD"), "fix.txt")
        status = git(wt, "status", "--porcelain")
        self.assertIn("AGENTS.md", status)
        self.assertIn(".agents", status)
        # bugfix 分支已推送到远端
        remote_branches = git(self.remote, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        self.assertIn(pr["head"], remote_branches)
        rec = r.load_record(self.project, "102")
        self.assertEqual(rec["pr"]["url"], "https://git.example/pr/77")
        self.assertIn("## Pull Request", (Path(rec["report_dir"]) / "fix-report.md").read_text(encoding="utf-8"))

    def test_worktree_pr_requires_changes_and_complete_reports(self):
        self._worktree_project({"AUTO_PR": "on", "AUTO_PR_CMD": FAKE_PR_CMD})
        self.prepare(bug="103", title="Another failure", worktree_env=True)
        rec = r.load_record(self.project, "103")
        wt = Path(rec["workspace"])
        with self.assertRaisesRegex(r.RouteError, "没有待提交"):
            r.create_pr(self.project, "103")
        (wt / "fix.txt").write_text("bugfix\n", encoding="utf-8")
        (Path(rec["report_dir"]) / "analysis.md").write_text("完整", encoding="utf-8")
        (Path(rec["report_dir"]) / "solution.md").write_text("完整", encoding="utf-8")
        (Path(rec["report_dir"]) / "fix-report.md").write_text("还有（待填写）", encoding="utf-8")
        with self.assertRaisesRegex(r.RouteError, "尚未完整落盘"):
            r.create_pr(self.project, "103")

    def test_worktree_without_config_default_stops(self):
        self._worktree_project({})
        self.prepare(bug="104", title="Quiet failure", worktree_env=True)
        rec = r.load_record(self.project, "104")
        (Path(rec["workspace"]) / "fix.txt").write_text("bugfix\n", encoding="utf-8")
        for name in ("analysis.md", "solution.md", "fix-report.md"):
            (Path(rec["report_dir"]) / name).write_text("完整报告", encoding="utf-8")
        with self.assertRaisesRegex(r.RouteError, "auto_pr 未开启"):
            r.create_pr(self.project, "104")
        # 未产生提交
        self.assertEqual(git(Path(rec["workspace"]), "rev-list", "--count", "HEAD"), "1")


if __name__ == "__main__":
    unittest.main()
