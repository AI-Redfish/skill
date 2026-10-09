"""Routing and commit integration tests; real temporary Git repos, no network/Agent."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("routed_bugfix", SCRIPTS / "bugfix.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)
r = bf._routes


def git(repo, *args):
    return r.text(repo, *args)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "source"
        self.project.mkdir()
        self.workspace = Path(self.tmp.name) / "dev"
        self.workspace.mkdir()
        git(self.workspace, "init", "-b", "feature/order")
        git(self.workspace, "config", "user.name", "Test")
        git(self.workspace, "config", "user.email", "test@example.test")
        for name in ("one.txt", "two.txt", "developer.txt"):
            (self.workspace / name).write_text("initial\n")
        git(self.workspace, "add", ".")
        git(self.workspace, "commit", "-m", "initial")
        self.rule = {"name": "订单", "match": {"title_contains": "Order"},
                     "workspace": str(self.workspace), "target_branch": "feature/order"}
        self.rules([self.rule])

    def rules(self, rules):
        r.save(r.root(self.project) / "routes.json", {"rules": rules})

    def prepare(self, bug="101", title="ORDER failure", reuse=False):
        cache = self.project / ".agents" / "bugfix-work" / bug
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "bug.md").write_text("# Bug\n- **标题**: " + title)
        args = SimpleNamespace(project=str(self.project), bug_id=bug, base_branch=None,
                               reuse=reuse, force=False, current_workspace=str(self.project))
        with patch.object(bf, "fetch_bug_full", return_value=({"title": title}, [], [], str(cache), "https://zentao.test", "bug")), contextlib.redirect_stdout(io.StringIO()):
            return bf.cmd_prepare(args)

    def docs(self, bug="101"):
        rec = r.load_record(self.project, bug)
        for name in ("analysis.md", "solution.md", "fix-report.md"):
            (Path(rec["report_dir"]) / name).write_text("完整的分析、方案或验证记录", encoding="utf-8")
        r.ready(self.project, bug)
        return rec

    @property
    def check(self):
        # Portable executable path, also when Windows Python contains spaces.
        return shlex.quote(sys.executable) + ' -c "print(123)"'

    def test_unified_config_save_and_routing_preserve_each_other(self):
        args = SimpleNamespace(project=str(self.project), pairs=["ZENTAO_BASE_URL=https://z.test", "ZENTAO_ACCOUNT=test", "ZENTAO_PASSWORD=secret", "BUGFIX_BASE_BRANCH=release"])
        self.assertEqual(bf.cmd_save_config(args), 0)
        path, config = bf.load_config(self.project)
        self.assertEqual(Path(path), r.config_path(self.project))
        self.assertEqual(config["BUGFIX_BASE_BRANCH"], "release")
        self.assertEqual(r.read(path)["rules"], [self.rule])
        self.assertEqual(r.select(self.project, "101", "Order")["mode"], "inplace")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(bf.cmd_config_status(SimpleNamespace(project=str(self.project))), 0)
        self.assertNotIn("secret", output.getvalue())
        self.assertIn("config_path", json.loads(output.getvalue()))

    def test_bug_fetch_ignores_old_env_when_json_config_absent(self):
        env = self.project / ".agents" / ".env"
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text("ZENTAO_BASE_URL=https://old.test\nZENTAO_ACCOUNT=old\nZENTAO_PASSWORD=old\n")
        with patch.object(bf, "fetch_bug_v1") as fetch:
            with self.assertRaises(SystemExit) as exc:
                bf.fetch_bug_full(str(self.project), "101")
        self.assertEqual(exc.exception.code, 2)
        fetch.assert_not_called()

    def test_config_only_document_keeps_default_worktree(self):
        r.save(r.config_path(self.project), {"config": {"ZENTAO_ACCOUNT": "a"}})
        self.assertEqual(r.select(self.project, "101", "Order")["mode"], "worktree")

    def test_missing_routes_default(self):
        (r.root(self.project) / "routes.json").unlink()
        self.assertEqual(r.select(self.project, "101", "Order")["mode"], "worktree")

    def test_exact_precedes_title_and_same_target_not_conflict(self):
        self.rules([self.rule, dict(self.rule, match={"bug_id": "101"}, target_branch="other")])
        self.assertEqual(r.select(self.project, "101", "Order")["branch"], "other")
        self.rules([self.rule, dict(self.rule, match={"title_contains": "failure"})])
        self.assertEqual(r.select(self.project, "101", "Order failure")["mode"], "inplace")

    def test_title_literal_casefold_and_conflict(self):
        self.assertEqual(r.select(self.project, "101", "order failure")["mode"], "inplace")
        self.assertEqual(r.select(self.project, "101", "unrelated")["mode"], "worktree")
        self.rules([dict(self.rule, match={"title_contains": "[Order]"})])
        self.assertEqual(r.select(self.project, "101", "Order")["mode"], "worktree")
        self.rules([self.rule, dict(self.rule, target_branch="other")])
        self.assertEqual(r.select(self.project, "101", "Order")["mode"], "worktree")

    def test_invalid_rules_stop(self):
        for match in ({"title_contains": ""}, {"task": "3"}, {"bug_id": "1", "title_contains": "Order"}):
            self.rules([dict(self.rule, match=match)])
            with self.assertRaises(r.RouteError):
                r.select(self.project, "1", "Order")

    def test_two_bugs_serial_two_commits_no_worktree(self):
        initial = git(self.workspace, "rev-parse", "HEAD")
        self.assertEqual(self.prepare(), 0)
        self.assertEqual(self.prepare("102"), 6)
        self.docs()
        (self.workspace / "one.txt").write_text("fix 101\n")
        first = r.finish(self.project, "101", ["one.txt"], self.check)
        self.assertEqual(first["status"], "committed")
        self.assertEqual(git(self.workspace, "rev-parse", "HEAD^"), initial)
        self.assertEqual(self.prepare("102"), 0)
        self.docs("102")
        (self.workspace / "two.txt").write_text("fix 102\n")
        second = r.finish(self.project, "102", ["two.txt"], self.check)
        self.assertEqual(git(self.workspace, "rev-parse", "HEAD^"), first["commit"])
        self.assertEqual(git(self.workspace, "diff", "--name-only", "HEAD^", "HEAD"), "two.txt")
        self.assertNotEqual(first["commit"], second["commit"])
        self.assertEqual(len(git(self.workspace, "worktree", "list", "--porcelain").split("worktree ")) - 1, 1)
        self.assertEqual(self.prepare("101"), 4)

    def test_preserves_staged_unstaged_and_untracked_developer_changes(self):
        dev = self.workspace / "developer.txt"
        dev.write_text("developer staged\n")
        git(self.workspace, "add", "developer.txt")
        dev.write_text("developer unstaged too\n")
        (self.workspace / "private.txt").write_text("untracked\n")
        staged = git(self.workspace, "diff", "--cached")
        unstaged = git(self.workspace, "diff", "--", "developer.txt")
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n")
        result = r.finish(self.project, "101", ["one.txt"], self.check)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(git(self.workspace, "diff", "--cached"), staged)
        self.assertEqual(git(self.workspace, "diff", "--", "developer.txt"), unstaged)
        self.assertEqual(git(self.workspace, "show", "HEAD:developer.txt"), "initial")
        self.assertEqual((self.workspace / "private.txt").read_text(), "untracked\n")

    def test_reverse_staged_changes_still_count_as_dirty(self):
        p = self.workspace / "one.txt"
        p.write_text("staged development\n")
        git(self.workspace, "add", "one.txt")
        p.write_text("initial\n")  # Working tree matches HEAD but index has user work.
        self.prepare()
        rec = r.load_record(self.project, "101")
        self.assertIn("one.txt", rec["snapshot"]["dirty"])
        self.docs()
        p.write_text("bug fix\n")
        with self.assertRaisesRegex(r.RouteError, "混合"):
            r.finish(self.project, "101", ["one.txt"], self.check)

    def test_mixed_file_refused_keeps_branch_locked(self):
        (self.workspace / "one.txt").write_text("developer\n")
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("developer plus bug fix\n")
        with self.assertRaisesRegex(r.RouteError, "混合"):
            r.finish(self.project, "101", ["one.txt"], self.check)
        self.assertEqual(self.prepare("102"), 6)
        self.assertEqual(git(self.workspace, "rev-list", "--count", "HEAD"), "1")

    def test_validation_and_hook_failure_block_next_bug(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n")
        with self.assertRaisesRegex(r.RouteError, "验证失败"):
            r.finish(self.project, "101", ["one.txt"], shlex.quote(sys.executable) + ' -c "raise SystemExit(1)"')
        self.assertEqual(self.prepare("102"), 6)
        hook = self.workspace / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        with self.assertRaises(r.RouteError):
            r.finish(self.project, "101", ["one.txt"], self.check)
        self.assertEqual(self.prepare("102"), 6)
        self.assertEqual(git(self.workspace, "diff", "--cached"), "")

    def test_ready_before_code_and_required_for_finish(self):
        self.prepare()
        (self.workspace / "one.txt").write_text("too early\n")
        with self.assertRaisesRegex(r.RouteError, "已改变"):
            r.ready(self.project, "101")
        with self.assertRaisesRegex(r.RouteError, "ready"):
            r.finish(self.project, "101", ["one.txt"], self.check)

    def test_no_change_releases_without_empty_commit(self):
        self.prepare()
        self.docs()
        rec = r.finish(self.project, "101", [], self.check, no_change=True)
        self.assertEqual(rec["status"], "no_change")
        self.assertEqual(git(self.workspace, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.prepare("102"), 0)

    def test_missing_workspace_html_in_current_and_retry(self):
        missing = Path(self.tmp.name) / "absent"
        self.rules([dict(self.rule, workspace=str(missing))])
        with patch.object(r, "open_report", return_value=True) as opened:
            self.assertEqual(self.prepare(title='<script>alert(1)</script> Order'), 7)
        rec = r.load_record(self.project, "101")
        report = Path(rec["html_report"])
        self.assertTrue(report.is_relative_to(self.project / ".agents"))
        self.assertIn("&lt;script&gt;", report.read_text())
        self.assertNotIn("<script>", report.read_text())
        opened.assert_called_once_with(report)
        self.assertFalse(missing.exists())
        self.rules([self.rule])
        self.assertEqual(self.prepare(), 0)

    def test_browser_failure_and_wrong_branch_report(self):
        self.rules([dict(self.rule, target_branch="wrong")])
        with patch.object(r, "open_report", side_effect=OSError("no browser")):
            self.assertEqual(self.prepare(), 7)
        rec = r.load_record(self.project, "101")
        self.assertFalse(rec["browser_opened"])
        self.assertIn("no browser", rec["browser_error"])
        self.assertTrue(Path(rec["html_report"]).is_file())
        self.assertEqual(git(self.workspace, "branch", "--show-current"), "feature/order")

    def test_resume_reuses_snapshot_and_locks(self):
        self.prepare()
        self.docs()
        before = r.load_record(self.project, "101")
        (self.workspace / "one.txt").write_text("fixed\n")
        self.assertEqual(self.prepare(reuse=True), 0)
        after = r.load_record(self.project, "101")
        self.assertEqual(after["snapshot"], before["snapshot"])
        self.assertEqual(after["run_id"], before["run_id"])
        r.finish(self.project, "101", ["one.txt"], self.check)

    def test_process_reservation_blocks_other_project_and_process(self):
        self.prepare()
        script = ('import importlib.util,json,sys;'
                  's=importlib.util.spec_from_file_location("r",sys.argv[1]);'
                  'r=importlib.util.module_from_spec(s);s.loader.exec_module(r);'
                  'r.reserve(sys.argv[2],"102",json.loads(sys.argv[3]))')
        route = r.select(self.project, "101", "Order")
        proc = subprocess.run([sys.executable, "-c", script, str(SCRIPTS / "bugfix_routes.py"),
                               str(Path(self.tmp.name) / "another"), json.dumps(route)], capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b"Busy", proc.stderr)

    def test_default_prepare_creates_worktree_and_reports_mode(self):
        # Default route still fetches the bug first, then creates an isolated worktree.
        self.project = self.workspace
        self.assertEqual(self.prepare(title="Unrelated failure"), 0)
        rec = r.load_record(self.project, "101")
        self.assertEqual(rec["mode"], "worktree")
        self.assertNotEqual(Path(rec["workspace"]), self.workspace)
        self.assertEqual(git(self.workspace, "branch", "--show-current"), "feature/order")

    def test_report_filters_existing_developer_files(self):
        (self.workspace / "developer.txt").write_text("developer\n")
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n")
        rec = r.load_record(self.project, "101")
        (Path(rec["report_dir"]) / "fix-report.md").unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bf.cmd_report(SimpleNamespace(project=str(self.project), bug_id="101", force=False)), 0)
        content = (Path(rec["report_dir"]) / "fix-report.md").read_text()
        self.assertIn("one.txt", content)
        self.assertNotIn("developer.txt", content)

    def test_active_session_blocks_reuse_even_same_bug(self):
        self.prepare()
        rec = r.load_record(self.project, "101")
        script = ('import importlib.util,json,sys;'
                  's=importlib.util.spec_from_file_location("r",sys.argv[1]);'
                  'r=importlib.util.module_from_spec(s);s.loader.exec_module(r);'
                  'r.reserve(sys.argv[2],"101",json.loads(sys.argv[3]),True)')
        with r.active_execution(rec):
            proc = subprocess.run([sys.executable, "-c", script, str(SCRIPTS / "bugfix_routes.py"),
                                   str(self.project), json.dumps(rec["route"])], capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b"Busy", proc.stderr)

    def test_external_head_change_and_file_list_mismatch_block_commit(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").write_text("fixed\n")
        with self.assertRaisesRegex(r.RouteError, "全部变更"):
            r.finish(self.project, "101", ["two.txt"], self.check)
        git(self.workspace, "commit", "--allow-empty", "-m", "external")
        with self.assertRaisesRegex(r.RouteError, "HEAD"):
            r.finish(self.project, "101", ["one.txt"], self.check)
        self.assertEqual(self.prepare("102"), 6)

    def test_error_html_uses_current_workspace_not_target_project(self):
        self.rules([dict(self.rule, workspace=str(Path(self.tmp.name) / "missing"))])
        cache = self.project / ".agents" / "bugfix-work" / "101"
        cache.mkdir(parents=True)
        current = Path(self.tmp.name) / "listener"
        args = SimpleNamespace(project=str(self.project), current_workspace=str(current), bug_id="101", base_branch=None, reuse=False, force=False)
        with patch.object(bf, "fetch_bug_full", return_value=({"title": "Order"}, [], [], str(cache), "https://z.test", "bug")), patch.object(r, "open_report", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bf.cmd_prepare(args), 7)
        rec = r.load_record(self.project, "101")
        self.assertTrue(Path(rec["html_report"]).is_relative_to(current / ".agents"))

    def test_add_delete_and_spaces(self):
        self.prepare()
        self.docs()
        (self.workspace / "one.txt").unlink()
        (self.workspace / "new file.txt").write_text("new\n")
        rec = r.finish(self.project, "101", ["one.txt", "new file.txt"], self.check)
        self.assertEqual(rec["status"], "committed")
        self.assertEqual(git(self.workspace, "status", "--porcelain", "--", "one.txt", "new file.txt"), "")


if __name__ == "__main__":
    unittest.main()
