import json
import tempfile
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
        self.assertIn("git_repositories[0].branches（必须显式指定）", we.required_missing(config))
        self.assertIn("agent_workspaces（至少一个）", we.required_missing(config))

    def test_window_uses_one_shared_period(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["schedule"]["lookback_days"] = 2
        start, end = we.window(config, datetime(2025, 1, 3, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(end, "2025-01-03T12:00:00+00:00")
        self.assertEqual(start, "2025-01-01T12:00:00+00:00")

    def test_windows_task_preview_uses_daily_time_and_persistence(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        preview = we.windows_task_preview(config, Path("C:/work"), "07:30")
        self.assertEqual(preview["task_name"], "AI-Redfish-work-experience-accumulate")
        self.assertIn("每日 07:30", preview["trigger"])
        self.assertIn("StartWhenAvailable=true", preview["trigger"])
        self.assertIn("任务计划程序", preview["restart_behavior"])

    def test_windows_weekly_task_preview_is_supported(self):
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        config["schedule"]["frequency"] = "weekly"
        preview = we.windows_task_preview(config, Path("C:/work"), "07:30")
        self.assertIn("每周一 07:30", preview["trigger"])

    def test_windows_task_time_validation_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            we.validate_time("7:30")

    def test_windows_argument_quoting(self):
        self.assertEqual(we.win_arg_quote("plain"), "plain")
        self.assertEqual(we.win_arg_quote("C:\\My Work\\dir"), '"C:\\My Work\\dir"')

    @patch("work_experience.run_argv", return_value=(0, "", ""))
    def test_windows_registration_contract(self, runner):
        import base64
        config = json.loads(json.dumps(we.DEFAULT_CONFIG))
        with patch("work_experience.schedule_command", return_value=["C:/Python/python.exe", "C:/My Work/work_experience.py", "run-cycle", "--workdir", "C:/My Work"]):
            installed, _ = we.install_windows_task(config, Path("C:/My Work"), "07:30")
        self.assertTrue(installed)
        script = base64.b64decode(runner.call_args.args[0][-1]).decode("utf-16le")
        self.assertIn("-LogonType Interactive -RunLevel Limited", script)
        self.assertNotIn("InteractiveToken", script)
        self.assertIn("-StartWhenAvailable", script)
        self.assertIn("Register-ScheduledTask", script)
        self.assertIn("Get-ScheduledTask", script)
        self.assertIn('"C:/My Work/work_experience.py"', script)

    @patch("work_experience.run_argv", return_value=(1, "", "Access denied"))
    def test_windows_registration_failure_not_reported_installed(self, runner):
        installed, error = we.install_windows_task(we.DEFAULT_CONFIG, Path("C:/Work"), "09:00")
        self.assertFalse(installed)
        self.assertIn("Access denied", error)

    def test_windows_task_name_rejects_directory(self):
        with self.assertRaises(ValueError):
            we.windows_task_name({"schedule": {"task_name": "folder/task"}})

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
            config = {"agent_workspaces": [str(root)]}
            records, errors = we.collect_sessions(config, "2025-01-01T00:00:00+00:00", "2025-01-02T00:00:00+00:00")
            self.assertEqual(records, [])
            self.assertEqual(len(errors), 1)

    @patch("work_experience.run_argv", return_value=(1, "", "not logged in"))
    def test_source_error_is_preserved(self, _run):
        data, error = we.collect_dingtalk({"dingtalk": {"search_args": []}}, "s", "e")
        self.assertIsNotNone(error)
        self.assertIn("失败", error)
        self.assertIn("stderr", data)


if __name__ == "__main__":
    unittest.main()
