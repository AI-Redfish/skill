import argparse
import contextlib
import io
import json
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import work_experience as we


class WorkExperienceTests(unittest.TestCase):
    def test_missing_requires_explicit_branches_and_workspace(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["dingtalk"]["notify_user_id"] = "u1"
        config["zentao"] = {"query_command": ["query"], "user_id": "z1"}
        config["git_repositories"] = [{"path": "/repo", "branches": []}]
        self.assertTrue(any("显式指定分支" in item for item in we.required_missing(config)))
        self.assertIn("agent_workspaces（至少一个）", we.required_missing(config))

    def test_lookback_window_uses_one_shared_period(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["schedule"]["window_mode"] = "lookback"
        config["schedule"]["lookback_days"] = 2
        start, end = we.window(config, datetime(2025, 1, 3, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(end, "2025-01-03T12:00:00+00:00")
        self.assertEqual(start, "2025-01-01T12:00:00+00:00")

    def test_daily_fixed_window_is_local_0600_to_1830(self):
        from datetime import timedelta, timezone as tz
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        local = tz(timedelta(hours=8))
        # 本地 2025-01-03 20:00 触发：窗口为当天 06:00–18:30
        now = datetime(2025, 1, 3, 12, 0, tzinfo=timezone.utc)
        start, end = we.window(config, now, tz=local)
        self.assertEqual(end, "2025-01-03T10:30:00+00:00")
        self.assertEqual(start, "2025-01-02T22:00:00+00:00")

    def test_daily_fixed_window_falls_back_before_end_time(self):
        from datetime import timedelta, timezone as tz
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        local = tz(timedelta(hours=8))
        # 本地 2025-01-03 10:00 手动补跑：回退到昨天 06:00–18:30 窗口
        now = datetime(2025, 1, 3, 2, 0, tzinfo=timezone.utc)
        start, end = we.window(config, now, tz=local)
        self.assertEqual(end, "2025-01-02T10:30:00+00:00")
        self.assertEqual(start, "2025-01-01T22:00:00+00:00")

    def test_daily_fixed_window_supports_cross_midnight(self):
        from datetime import timedelta, timezone as tz
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["schedule"]["daily_window_start"] = "22:00"
        config["schedule"]["daily_window_end"] = "06:00"
        local = tz(timedelta(hours=8))
        now = datetime(2025, 1, 3, 0, 0, tzinfo=timezone.utc)  # 本地 08:00
        start, end = we.window(config, now, tz=local)
        self.assertEqual(end, "2025-01-02T22:00:00+00:00")   # 本地 01-03 06:00
        self.assertEqual(start, "2025-01-02T14:00:00+00:00")  # 本地 01-02 22:00

    def test_required_missing_tolerates_absent_window_keys_but_flags_invalid(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["schedule"] = {"frequency": "daily", "time": "18:30"}
        self.assertNotIn("schedule.daily_window_start= HH:MM（24 小时制）", we.required_missing(config))
        config["schedule"]["daily_window_end"] = "25:00"
        self.assertIn("schedule.daily_window_end= HH:MM（24 小时制）", we.required_missing(config))
        config["schedule"]["daily_window_end"] = "06:00"
        config["schedule"]["daily_window_start"] = "06:00"
        self.assertIn("不能相同", we.required_missing(config)[0])
        config["schedule"]["window_mode"] = "custom"
        self.assertTrue(any("window_mode" in item for item in we.required_missing(config)))

    def test_windows_task_time_validation_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            we.validate_time("7:30")

    def test_draft_lifecycle_rejects_changed_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            (run / "work").mkdir(parents=True)
            (run / "work" / "manifest.json").write_text("{}", encoding="utf-8")
            args = type("Args", (), {"run": str(run), "force": False})
            self.assertEqual(we.cmd_draft_init(args), 0)
            approve = type("Args", (), {"run": str(run), "reviewer": "u1"})
            self.assertEqual(we.cmd_approve(approve), 0)
            self.assertEqual(we.cmd_verify(type("Args", (), {"run": str(run)})()), 0)
            (run / "draft.md").write_text("changed", encoding="utf-8")
            self.assertEqual(we.cmd_verify(type("Args", (), {"run": str(run)})()), 4)

    def test_session_parser_skips_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.jsonl").write_text("{broken\n", encoding="utf-8")
            config = {"agent_workspaces": [str(root)], "agent_session_dir": str(root)}
            records, errors = we.collect_sessions(config, "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
            self.assertEqual(records, [])
            self.assertEqual(len(errors), 1)

    def test_missing_pi_session_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            records, errors = we.collect_sessions({"agent_workspaces": [tmp], "agent_session_dir": str(Path(tmp) / "missing")},
                                                   "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
            self.assertEqual(records, [])
            self.assertEqual(len(errors), 1)

    def test_pi_session_parser_matches_header_cwd_and_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            session = root / "session.jsonl"
            lines = [
                {"type": "session", "version": 3, "id": "s1", "cwd": str(workspace)},
                {"type": "model_change", "timestamp": "2025-01-01T00:00:00+00:00"},
                {"type": "message", "timestamp": "2025-01-01T12:00:00+00:00", "message": {"role": "user", "content": "inside"}},
                {"type": "message", "timestamp": "2025-01-02T00:00:00+00:00", "message": {"role": "assistant", "content": "outside"}},
                {"type": "message", "timestamp": "2025-01-01T13:00:00+00:00", "message": {"role": "toolResult", "content": [{"type": "text", "text": "ignore"}]}},
            ]
            session.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
            other = root / "other.jsonl"
            other.write_text(json.dumps({"type": "session", "cwd": str(root / "unregistered")}) + "\n" + json.dumps(lines[2]) + "\n", encoding="utf-8")
            config = {"agent_workspaces": [str(workspace)], "agent_session_dir": str(root)}
            records, errors = we.collect_sessions(config, "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["session_id"], "s1")
            self.assertEqual([item["text"] for item in records[0]["records"]], ["inside"])

    def test_agent_worktree_discovery_unions_paths_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured = Path(tmp) / "configured"
            discovered = Path(tmp) / "discovered"
            configured.mkdir()
            discovered.mkdir()
            output = "worktree " + str(discovered) + "\nHEAD abc\n\n"
            config = {"agent_workspaces": [str(configured)], "agent_workspace_discovery": {
                "repository": str(configured), "include_all_registered_worktrees": True}}
            with patch.object(we, "run_argv", return_value=(0, output, "")) as runner:
                paths, errors = we.discover_agent_workspaces(config)
            self.assertEqual(errors, [])
            self.assertEqual({path.resolve() for path in paths}, {configured.resolve(), discovered.resolve()})
            self.assertEqual(runner.call_args.args[0][5:], ["list", "--porcelain"])

    def test_agent_command_requires_isolation_and_output_is_stdout(self):
        run = Path("C:/run")
        command = ["pi", "-p", "--no-tools", "--no-extensions", "--no-context-files", "--no-skills",
                   "--no-prompt-templates", "--no-themes", "--no-session", "--no-approve", "@{run_dir}/work/a.json"]
        argv, error = we.format_agent_command(command, run)
        self.assertIsNone(error)
        self.assertEqual(argv[-1].replace("\\", "/"), "@C:/run/work/a.json")
        _, error = we.format_agent_command(["pi", "-p"], run)
        self.assertIn("安全参数", error)
        valid = ("# 工作经验沉淀草稿\n## <analysis>分析\n来源：`work/manifest.json`\n"
                 "### 工作项清单\n### 聊天记录逐条细节\n## 待确定事项\n"
                 "## <conclusion>沉淀候选\n### 触发方式与辅助设计\n状态：待用户审核。\n## 审核说明\n"
                 "本次不修改任何目标产物。")
        body, error = we.validate_agent_output(valid)
        self.assertIsNotNone(body)
        self.assertIsNone(error)
        self.assertIsNone(we.validate_agent_output("# 工作经验沉淀草稿\n## <analysis>分析\n## <conclusion>沉淀候选\n## 审核说明")[0])
        self.assertIsNone(we.validate_agent_output("待填写")[0])

    @patch("work_experience.run_argv", return_value=(1, "", "not logged in"))
    def test_source_error_is_preserved(self, _run):
        data, error = we.collect_dingtalk({"dingtalk": {}}, "s", "e")
        self.assertIsNotNone(error)
        self.assertFalse(data["complete"])
        self.assertNotIn("stderr", data)
        self.assertNotIn("command", data)


class DynamicGitTests(unittest.TestCase):
    START = "2025-01-02T00:00:00+00:00"
    END = "2025-01-03T00:00:00+00:00"
    RULES = {"remote_prefixes": ["origin/dev"], "local_name_contains": ["zly"],
             "remote_name_contains": ["zly"]}

    def refs(self):
        return "\n".join((
            "refs/heads/release\t", "refs/heads/local-zly\t", "refs/heads/dev/local\t",
            "refs/remotes/origin/dev/v1\t", "refs/remotes/origin/developer\t",
            "refs/remotes/origin/feature/zly-test\t", "refs/remotes/upstream/feature/zly-test\t",
            "refs/remotes/origin/HEAD\trefs/remotes/origin/dev/v1",
            "refs/remotes/zly-server/feature/other\t", "refs/remotes/origin/release\t"))

    def test_exact_rule_union_and_symbolic_head_exclusion(self):
        repo = {"path": "/repo", "branches": ["release"], "branch_selection": self.RULES}
        with patch.object(we, "run_argv", return_value=(0, self.refs(), "")) as run:
            refs = we.discover_branches(repo)
        self.assertEqual({r["branch"] for r in refs}, {
            "release", "local-zly", "origin/dev/v1", "origin/developer",
            "origin/feature/zly-test", "upstream/feature/zly-test"})
        self.assertEqual(run.call_args.args[0][4], "for-each-ref")
        self.assertIn("--no-optional-locks", run.call_args.args[0])

    def test_refresh_every_call_discovers_new_branch(self):
        repo = {"path": "/repo", "branch_selection": self.RULES}
        with patch.object(we, "run_argv", side_effect=[(0, self.refs(), ""),
                (0, self.refs() + "\nrefs/heads/new-zly\t", "")]):
            first = we.discover_branches(repo)
            second = we.discover_branches(repo)
        self.assertEqual(len(second), len(first) + 1)
        self.assertIn("new-zly", [r["branch"] for r in second])

    def test_invalid_configs_never_run_git(self):
        bad = ({}, {"branches": "main"}, {"branches": [""]},
               {"branch_selection": {"unknown": ["x"]}},
               {"branch_selection": {"remote_prefixes": [""]}},
               {"branch_selection": {"remote_prefixes": "origin/dev"}},
               {"branches": ["main"], "author_emails": "me@example.test"},
               {"branches": ["main"], "deduplicate_commits": "yes"})
        for config in bad:
            with self.subTest(config=config), patch.object(we, "run_argv") as run:
                with self.assertRaises(ValueError):
                    we.discover_branches(dict(config, path="/repo"))
                run.assert_not_called()

    def test_explicit_unknown_ambiguous_and_empty_matches_stop(self):
        cases = ({"branches": ["missing"]},
                 {"branch_selection": {"local_name_contains": ["absent"]}},
                 {"branches": ["origin/dev/v1"]})
        for config in cases:
            with self.subTest(config=config), patch.object(we, "run_argv", return_value=(0,
                    self.refs() + "\nrefs/heads/origin/dev/v1\t", "")):
                with self.assertRaises(ValueError):
                    we.discover_branches(dict(config, path="/repo"))
        with patch.object(we, "run_argv", return_value=(0, self.refs(), "")):
            self.assertEqual(we.discover_branches({"path": "/repo", "branches": ["refs/remotes/origin/dev/v1"]})[0]["kind"], "remote")

    def test_discovery_failure_marks_source_failed_without_log(self):
        with patch.object(we, "run_argv", return_value=(1, "", "not a repository")) as run:
            data, errors = we.collect_git({"git_repositories": [{"path": "/missing", "branch_selection": self.RULES}]}, self.START, self.END)
        self.assertEqual(data, [])
        self.assertTrue(errors)
        self.assertEqual(run.call_count, 1)

    def test_author_exact_match_half_open_time_and_commit_dedup(self):
        inside = "2025-01-02T10:00:00+00:00"
        old = "2024-12-01T00:00:00+00:00"
        lines = "\n".join((
            f"a\t{old}\tMe\tme@example.test\t{inside}\tcherry-picked old author date",
            f"b\t{inside}\tOther\tnot-me@example.test\t{inside}\tnot mine",
            f"c\t{inside}\tMe\tme@example.test\t{self.END}\tend excluded",
            f"d\t{inside}\tMe\tme@example.test\t{self.START}\tstart included",
            f"e\t{inside}\tMe\tme@example.test\t{old}\tbefore start excluded"))
        config = {"git_repositories": [{"path": "/repo", "branch_selection": self.RULES,
                  "author_emails": ["ME@example.test"], "deduplicate_commits": True}]}
        refs = "refs/heads/local-zly\t\nrefs/remotes/origin/dev/v1\t"
        with patch.object(we, "run_argv", side_effect=[(0, refs, ""), (0, lines, ""), (0, lines, "")]) as run:
            data, errors = we.collect_git(config, self.START, self.END)
        self.assertEqual(errors, [])
        commits = [c for r in data for c in r["commits"]]
        self.assertEqual({c["commit"] for c in commits}, {"a", "d"})
        self.assertTrue(all(len(c["branches"]) == 2 for c in commits))
        self.assertEqual(data[1]["duplicate_commit_ids"], ["a", "d"])
        self.assertIn("--since-as-filter=" + self.START, run.call_args.args[0])
        self.assertTrue(run.call_args.args[0][-2].startswith("refs/"))

    def test_no_dedup_preserves_branch_records(self):
        line = "a\t2025-01-02T10:00:00+00:00\tMe\tme@example.test\t2025-01-02T10:00:00+00:00\tfix"
        config = {"git_repositories": [{"path": "/repo", "branches": ["main", "release"], "deduplicate_commits": False}]}
        with patch.object(we, "run_argv", side_effect=[(0, "refs/heads/main\t\nrefs/heads/release\t", ""), (0, line, ""), (0, line, "")]):
            data, errors = we.collect_git(config, self.START, self.END)
        self.assertEqual(errors, [])
        self.assertEqual(sum(len(r["commits"]) for r in data), 2)

    def test_dynamic_config_passes_required_check(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["dingtalk"]["notify_user_id"] = "u1"
        config["zentao"] = {"query_command": ["query"], "user_id": "z1"}
        config["agent_workspaces"] = ["/workspace"]
        config["git_repositories"] = [{"path": "/repo", "branch_selection": self.RULES}]
        self.assertEqual(we.required_missing(config), [])

    def test_log_failure_preserves_other_branch(self):
        repo = {"path": "/repo", "branches": ["main", "release"]}
        with patch.object(we, "run_argv", side_effect=[(0, "refs/heads/main\t\nrefs/heads/release\t", ""), (1, "", "missing object"), (0, "", "")]):
            data, errors = we.collect_git({"git_repositories": [repo]}, self.START, self.END)
        self.assertEqual(len(data), 2)
        self.assertEqual(len(errors), 1)

    def test_real_git_repo_discovery_dedup_and_no_mutation(self):
        import subprocess
        import os
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            def git(*args, env=None):
                p = subprocess.run(["git", "-C", td, *args], check=True, capture_output=True,
                                   encoding="utf-8", env=env)
                return p.stdout.strip()
            git("init", "-b", "main")
            git("config", "user.name", "Me")
            git("config", "user.email", "me@example.test")
            (path / "file.txt").write_text("original", encoding="utf-8")
            git("add", "file.txt")
            env = dict(os.environ, GIT_AUTHOR_DATE="2025-01-02T10:00:00+00:00", GIT_COMMITTER_DATE="2025-01-02T10:00:00+00:00")
            git("commit", "-m", "fixture", env=env)
            head = git("rev-parse", "HEAD")
            git("branch", "local-zly")
            git("update-ref", "refs/remotes/origin/dev/v1", head)
            git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev/v1")
            (path / "file.txt").write_text("developer unstaged", encoding="utf-8")
            before_refs = git("show-ref")
            before_index = (path / ".git/index").read_bytes()
            config = {"git_repositories": [{"path": td, "branch_selection": self.RULES, "author_emails": ["me@example.test"]}]}
            records, errors = we.collect_git(config, self.START, self.END)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)
            self.assertEqual(sum(len(r["commits"]) for r in records), 1)
            self.assertEqual(git("show-ref"), before_refs)
            self.assertEqual(git("branch", "--show-current"), "main")
            self.assertEqual((path / ".git/index").read_bytes(), before_index)
            self.assertEqual((path / "file.txt").read_text(encoding="utf-8"), "developer unstaged")
            git("branch", "new-zly")
            records, errors = we.collect_git(config, self.START, self.END)
            self.assertEqual(len(records), 3)
            self.assertEqual(errors, [])


class UncommittedGitTests(unittest.TestCase):
    START = DynamicGitTests.START
    END = DynamicGitTests.END

    def test_disabled_does_not_run_git(self):
        with patch.object(we, "run_argv") as run:
            self.assertEqual(we.collect_uncommitted({"path": "/repo"}, self.START, self.END), (None, None))
            run.assert_not_called()

    def test_invalid_candidate_configuration_rejected(self):
        cases = (True, {"enabled": "yes"}, {"enabled": True, "time_filter": "index_time"},
                 {"enabled": True, "classification": "verified"},
                 {"enabled": True, "author_verified": True},
                 {"enabled": True, "change_time_verified": True})
        for settings in cases:
            with self.subTest(settings=settings), patch.object(we, "run_argv") as run:
                with self.assertRaises(ValueError):
                    we.discover_branches({"path": "/repo", "branches": ["main"], "uncommitted": settings})
                run.assert_not_called()

    def test_half_open_mtime_window_and_missing_files(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, stamp in (("start.txt", self.START), ("end.txt", self.END),
                                ("old.txt", "2025-01-01T23:59:59+00:00")):
                (root / name).write_text("do not collect body", encoding="utf-8")
                seconds = datetime.fromisoformat(stamp).timestamp()
                os.utime(root / name, (seconds, seconds))
            raw = " M start.txt\0M  end.txt\0?? old.txt\0 D missing.txt\0"
            with patch.object(we, "run_argv", return_value=(0, raw, "")) as run:
                data, error = we.collect_uncommitted({"path": td, "uncommitted": {"enabled": True}}, self.START, self.END)
            self.assertIsNone(error)
            self.assertEqual([f["path"] for f in data["files"]], ["start.txt"])
            self.assertEqual(len(data["excluded"]), 3)
            self.assertEqual(data["excluded"][-1]["reason"], "file_missing_or_unreadable")
            self.assertEqual(data["files"][0]["classification"], "candidate")
            self.assertIs(data["files"][0]["author_verified"], False)
            self.assertIs(data["files"][0]["change_time_verified"], False)
            self.assertNotIn("do not collect body", json.dumps(data))
            self.assertIn("--no-optional-locks", run.call_args.args[0])
            self.assertIn("-z", run.call_args.args[0])

    def test_nul_paths_and_rename_destination_order(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            name = "新 文件.txt"
            file = Path(td) / name
            file.write_text("private contents", encoding="utf-8")
            stamp = datetime.fromisoformat(self.START).timestamp() + 60
            os.utime(file, (stamp, stamp))
            with patch.object(we, "run_argv", return_value=(0, "R  " + name + "\0old name.txt\0", "")):
                data, error = we.collect_uncommitted({"path": td, "uncommitted": {"enabled": True}}, self.START, self.END)
            self.assertIsNone(error)
            self.assertEqual(data["files"][0]["path"], name)
            self.assertEqual(data["files"][0]["previous_path"], "old name.txt")

    def test_status_failure_and_malformed_status_fail_closed(self):
        for response in ((1, "", "password=hidden"), (0, "broken\0", ""), (0, "R  destination\0", "")):
            with self.subTest(response=response), patch.object(we, "run_argv", return_value=response):
                data, error = we.collect_uncommitted({"path": "/repo", "uncommitted": {"enabled": True}}, self.START, self.END)
                self.assertIsNone(data)
                self.assertTrue(error)
                self.assertNotIn("hidden", error)

    def test_collector_records_candidates_once_not_per_branch(self):
        repo = {"path": "/repo", "branches": ["main", "release"], "uncommitted": {"enabled": True}}
        candidate = {"source": "uncommitted", "files": [{"path": "one.txt"}]}
        with patch.object(we, "run_argv", side_effect=[(0, "refs/heads/main\t\nrefs/heads/release\t", ""), (0, "", ""), (0, "", "")]), patch.object(we, "collect_uncommitted", return_value=(candidate, None)) as collect:
            data, errors = we.collect_git({"git_repositories": [repo]}, self.START, self.END)
        self.assertFalse(errors)
        self.assertEqual(len(data), 3)
        collect.assert_called_once_with(repo, self.START, self.END)
        self.assertIs(data[-1], candidate)

    def test_status_failure_retains_commit_records(self):
        repo = {"path": "/repo", "branches": ["main"], "uncommitted": {"enabled": True}}
        with patch.object(we, "run_argv", side_effect=[(0, "refs/heads/main\t", ""), (0, "", ""), (1, "", "status failed")]):
            data, errors = we.collect_git({"git_repositories": [repo]}, self.START, self.END)
        self.assertEqual(len(data), 1)
        self.assertEqual(len(errors), 1)

    def test_directory_is_excluded_and_symlink_target_not_followed(self):
        from types import SimpleNamespace
        import stat
        repo = {"path": "/repo", "uncommitted": {"enabled": True}}
        stamp = datetime.fromisoformat(self.START).timestamp() + 60
        with patch.object(we, "run_argv", return_value=(0, " M module\0 M link\0", "")), patch.object(Path, "lstat", side_effect=[SimpleNamespace(st_mode=stat.S_IFDIR, st_mtime=stamp), SimpleNamespace(st_mode=stat.S_IFLNK, st_mtime=stamp)]):
            data, error = we.collect_uncommitted(repo, self.START, self.END)
        self.assertIsNone(error)
        self.assertEqual([r["path"] for r in data["files"]], ["link"])
        self.assertEqual(data["excluded"][0]["reason"], "not_regular_file_or_symlink")

    def test_preview_supports_mixed_records_and_no_files_created(self):
        import argparse
        import contextlib
        import io
        records = [{"repository": "/repo", "branch": "main", "kind": "local", "commits": [], "duplicate_commit_ids": []},
                   {"repository": "/repo", "source": "uncommitted", "kind": "working_tree", "files": [{"path": "x"}], "excluded": []}]
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            with patch.object(we, "collect_git", return_value=(records, [])), contextlib.redirect_stdout(stdout):
                code = we.cmd_git_preview(argparse.Namespace(workdir=Path(td)))
            self.assertEqual(code, 0)
            data = json.loads(stdout.getvalue())["data"]
            self.assertTrue(data["uncommitted_collected"])
            self.assertEqual(data["branches"][-1]["uncommitted_files"], 1)
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_unterminated_invalid_status_and_unsafe_path_fail_closed(self):
        repo = {"path": "/repo", "uncommitted": {"enabled": True}}
        for raw in (" M file", "XX file\0", "?? ../outside\0"):
            with self.subTest(raw=raw), patch.object(we, "run_argv", return_value=(0, raw, "")):
                data, error = we.collect_uncommitted(repo, self.START, self.END)
                self.assertIsNone(data)
                self.assertTrue(error)

    def test_real_git_states_ignored_paths_and_no_mutation(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def git(*args):
                return subprocess.run(["git", "--no-optional-locks", "-C", td, *args], check=True,
                                      capture_output=True, encoding="utf-8").stdout
            git("init", "-b", "main")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.test")
            for name in ("staged.txt", "unstaged.txt", "both.txt", "old.txt", "gone.txt", "rename.txt", ".gitignore"):
                (root / name).write_text("ignored.txt\n" if name == ".gitignore" else name, encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "fixture")
            git("branch", "local-zly")
            (root / "staged.txt").write_text("staged", encoding="utf-8")
            (root / "both.txt").write_text("staged", encoding="utf-8")
            git("add", "staged.txt", "both.txt")
            (root / "both.txt").write_text("unstaged too", encoding="utf-8")
            (root / "unstaged.txt").write_text("unstaged", encoding="utf-8")
            (root / "old.txt").write_text("old change", encoding="utf-8")
            (root / "gone.txt").unlink()
            git("mv", "rename.txt", "新 文件.txt")
            (root / "untracked.txt").write_text("untracked", encoding="utf-8")
            (root / "ignored.txt").write_text("private ignored", encoding="utf-8")
            stamp = datetime.fromisoformat(self.START).timestamp() + 60
            for name in ("staged.txt", "unstaged.txt", "both.txt", "新 文件.txt", "untracked.txt", "ignored.txt"):
                os.utime(root / name, (stamp, stamp))
            os.utime(root / "old.txt", (stamp - 120, stamp - 120))
            before_refs = git("show-ref")
            before_index = (root / ".git/index").read_bytes()
            before_status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
            before_files = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
            repo = {"path": td, "branches": ["main", "local-zly"], "author_emails": ["other@example.test"], "uncommitted": {"enabled": True}}
            records, errors = we.collect_git({"git_repositories": [repo]}, self.START, self.END)
            self.assertFalse(errors)
            data = [r for r in records if r.get("source") == "uncommitted"]
            self.assertEqual(len(data), 1)
            candidates = {r["path"]: r["status"] for r in data[0]["files"]}
            self.assertEqual(candidates, {"staged.txt": "M ", "unstaged.txt": " M", "both.txt": "MM", "新 文件.txt": "R ", "untracked.txt": "??"})
            self.assertEqual(len(data[0]["excluded"]), 2)
            self.assertEqual(git("show-ref"), before_refs)
            self.assertEqual(git("branch", "--show-current").strip(), "main")
            self.assertEqual((root / ".git/index").read_bytes(), before_index)
            self.assertEqual(git("status", "--porcelain=v1", "-z", "--untracked-files=all"), before_status)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}, before_files)


class ConfigWarningTests(unittest.TestCase):
    """config-status 的 warnings：只报缺失路径，不阻断采集。"""

    def test_missing_paths_are_warnings_not_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            existing = Path(td) / "repo"
            existing.mkdir()
            config = {
                "git_repositories": [{"path": str(existing)}, {"path": str(Path(td) / "gone")}],
                "agent_workspaces": [str(existing), str(Path(td) / "gone2")],
                "targets": {"skill": [str(existing), str(Path(td) / "gone3")],
                           "workflow": "not-a-list"},
            }
            warnings = we.config_warnings(config)
            self.assertEqual(len(warnings), 3)
            self.assertTrue(all("不存在或不是目录" in w for w in warnings))
            self.assertTrue(any(w.startswith("targets.skill[1]") for w in warnings))
            self.assertEqual(we.config_warnings({}), [])

    def test_blank_and_non_string_paths_ignored(self):
        config = {"git_repositories": [{"path": "   "}, None, "x"],
                  "agent_workspaces": ["", 5, None],
                  "targets": {"skill": ["", None]}}
        self.assertEqual(we.config_warnings(config), [])

def task_json(**changes):
    value = {"State": "Ready", "LogonType": "Interactive", "RunLevel": "Limited",
             "StartWhenAvailable": True, "LastRunTime": "2026-10-14T12:00:00.0000000+08:00",
             "NextRunTime": "2026-10-15T12:00:00.0000000+08:00", "LastTaskResult": 0,
             "unknown": "drop-me"}
    value.update(changes)
    return json.dumps(value)


if __name__ == "__main__":
    unittest.main()
