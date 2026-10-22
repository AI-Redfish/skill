import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import agentr_todo
import work_experience as we


DRAFT = """# 工作经验沉淀草稿

> 状态：待用户审核。本次不修改任何目标产物。

### 工作项清单

| 序号 | 工作项 | AI 可提效 | 是否沉淀 | 待确定项 |
|---|---|---|---|---|
| 1 | 修复空指针 | 是 | skill | 触发时机待确定 |
| 2 | 例行部署 | 否 | 无 | 无 |

## 待确定事项

- 无。
"""


def draft_run(td: str) -> Path:
    run = Path(td) / "run"
    run.mkdir(parents=True)
    (run / "draft.md").write_text(DRAFT, encoding="utf-8")
    we.write_json(run / "work" / "manifest.json",
                  {"window": {"start": "2026-10-22T00:30:00+00:00", "end": "2026-10-22T10:30:00+00:00"},
                   "sources": {"dingtalk": True, "zentao": False, "git": True, "sessions": True}})
    return run


class ReportTests(unittest.TestCase):
    def test_report_renders_tables_and_highlights_uncertain_cells(self):
        with tempfile.TemporaryDirectory() as td:
            run = draft_run(td)
            code = we.cmd_report(argparse.Namespace(run=str(run)))
            self.assertEqual(code, 0)
            html = (run / "report.html").read_text(encoding="utf-8")
            self.assertIn("<table>", html)
            self.assertIn("<th>AI 可提效</th>", html)
            self.assertIn('class="uncertain"', html)
            self.assertIn("2026-10-22T00:30:00+00:00", html)
            self.assertIn("zentro=失败".replace("zentro", "zentao"), html)

    def test_report_requires_draft(self):
        with tempfile.TemporaryDirectory() as td:
            code = we.cmd_report(argparse.Namespace(run=td))
            self.assertEqual(code, 2)

    def test_render_escapes_html(self):
        html = we.render_markdown_html("# T\n\n<script>alert(1)</script>", "T", "")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


TODO_CONFIG = {"enabled": True, "endpoint": "http://127.0.0.1:8320/todos", "timeout_seconds": 5}


def fake_post(status=200, item_id="todo_1", envelope=True):
    def _post(url, payload, timeout):
        if envelope:
            return status, {"item": {"id": item_id, "title": payload["title"]}}
        return status, {"unexpected": True}
    return _post


CTX = {k: "v" for k in ("date", "window_start", "window_end", "run_dir", "draft", "report", "sources_note")}


class AgentrTodoTests(unittest.TestCase):
    def test_endpoint_validation(self):
        self.assertEqual(agentr_todo.validate_endpoint("http://127.0.0.1:8320/todos/"),
                         "http://127.0.0.1:8320/todos")
        for bad in ("ftp://x/todos", "http://u:p@127.0.0.1/todos", "http://x/todos?a=1",
                    "http://127.0.0.1/token", "not-a-url"):
            with self.assertRaises(ValueError):
                agentr_todo.validate_endpoint(bad)

    def test_create_success_writes_marker_with_id_only(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "todo.json"
            state, error = agentr_todo.create(
                TODO_CONFIG,
                {"date": "2026-10-22", "window_start": "10-22 08:30", "window_end": "10-22 18:30",
                 "run_dir": "R", "draft": "D", "report": "P", "sources_note": "ok"},
                fake_post(), we.write_json, marker)
            self.assertIsNone(error)
            self.assertTrue(state["created"])
            self.assertEqual(state["id"], "todo_1")
            saved = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(saved["id"], "todo_1")
            self.assertNotIn("endpoint_response", saved)

    def test_create_failure_reports_without_marker(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "todo.json"
            state, error = agentr_todo.create(TODO_CONFIG, CTX, fake_post(status=500), we.write_json, marker)
            self.assertIsNone(state)
            self.assertIn("500", error)
            self.assertFalse(marker.exists())
            state, error = agentr_todo.create(TODO_CONFIG, CTX, fake_post(envelope=False), we.write_json, marker)
            self.assertIn("item.id", error)

    def test_create_request_failure_never_leaks_raw_error(self):
        def boom(url, payload, timeout):
            raise OSError("connection refused to http://127.0.0.1:8320 with secret=abc")
        with tempfile.TemporaryDirectory() as td:
            state, error = agentr_todo.create(TODO_CONFIG, CTX, boom, we.write_json, Path(td) / "t.json")
            self.assertIsNone(state)
            self.assertIn("OSError", error)
            self.assertNotIn("secret", error)

    def test_title_template_substitution_and_bounds(self):
        captured = {}
        def spy(url, payload, timeout):
            captured.update(payload)
            return 200, {"item": {"id": "x"}}
        config = dict(TODO_CONFIG, title_template="审核 {date} / {window_start}~{window_end} / {draft}")
        with tempfile.TemporaryDirectory() as td:
            state, error = agentr_todo.create(config, {k: "v" for k in
                ("date", "window_start", "window_end", "run_dir", "draft", "report", "sources_note")},
                spy, we.write_json, Path(td) / "t.json")
            self.assertIsNone(error)
            self.assertIn("2026-10-22" if False else "v", captured["title"])
        config_bad = dict(TODO_CONFIG, title_template="{unknown_key}")
        state, error = agentr_todo.create(config_bad, CTX, fake_post(), we.write_json, Path(td) / "t.json")
        self.assertIn("占位符", error)

    def test_assignee_included_when_configured(self):
        captured = {}
        def spy(url, payload, timeout):
            captured.update(payload)
            return 200, {"item": {"id": "x"}}
        with tempfile.TemporaryDirectory() as td:
            agentr_todo.create(dict(TODO_CONFIG, assignee="zhaoliyang"), {k: "v" for k in
                ("date", "window_start", "window_end", "run_dir", "draft", "report", "sources_note")},
                spy, we.write_json, Path(td) / "t.json")
        self.assertEqual(captured.get("assignee"), "zhaoliyang")

    def test_cycle_todo_disabled_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            run = draft_run(td)
            disabled = json.loads(json.dumps(we.DEFAULT_CONFIG))
            state, error = we.create_agentr_todo(disabled, run, {})
            self.assertIsNone(state)
            self.assertIsNone(error)
            we.write_json(run / "work" / "todo.json", {"created": True, "id": "todo_9"})
            config = json.loads(json.dumps(we.DEFAULT_CONFIG))
            config["agentr_todo"] = dict(TODO_CONFIG)
            state, error = we.create_agentr_todo(config, run, {})
            self.assertEqual(state["id"], "todo_9")
            self.assertEqual(state.get("skipped"), "already_created")

    def test_todo_create_command_reports_state(self):
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td) / "workdir"
            run = draft_run(td)
            config = json.loads(json.dumps(we.DEFAULT_CONFIG))
            config["agentr_todo"] = dict(TODO_CONFIG)
            with patch.object(we, "load_config", return_value=config), \
                 patch("agentr_todo.post_json", side_effect=fake_post()):
                code = we.cmd_todo_create(argparse.Namespace(workdir=wd, run=str(run)))
            self.assertEqual(code, 0)
            self.assertTrue((run / "work" / "todo.json").is_file())


if __name__ == "__main__":
    unittest.main()
