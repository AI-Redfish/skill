import contextlib
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.error

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import zentao_query as zq
import work_experience as we

START = "2025-01-02T00:00:00+00:00"
END = "2025-01-03T00:00:00+00:00"
USER = "zhaoliyang"


def bug(**changes):
    result = {"id": 1, "product": 7, "status": "resolved", "resolvedBy": {"account": USER, "realname": "not an identifier"},
              "resolvedDate": "2025-01-02T08:00:00+08:00", "deleted": False, "title": "fixture", "resolution": "fixed"}
    result.update(changes)
    return result


class QueryTests(unittest.TestCase):
    def test_window_timezone_exact_user_status_and_deleted(self):
        start, end = zq.timestamp(START), zq.timestamp(END)
        self.assertTrue(zq.selected(bug(), USER, start, end))
        self.assertTrue(zq.selected(bug(resolvedBy=USER), USER, start, end))
        for row in (bug(resolvedDate=END), bug(resolvedDate="2025-01-01T23:59:59Z"), bug(resolvedBy="other"),
                    bug(resolvedBy={"account": "other", "realname": USER}), bug(status="closed"), bug(status="active"), bug(deleted=True)):
            self.assertFalse(zq.selected(row, USER, start, end))

    def test_unknown_fields_and_naive_time_fail_closed(self):
        start, end = zq.timestamp(START), zq.timestamp(END)
        for row in (bug(status=None), bug(status="unknown"), bug(resolvedBy=None), bug(resolvedBy={"realname": USER}),
                    bug(resolvedDate="0000-00-00 00:00:00"), bug(resolvedDate="2025-01-02 12:00:00"), bug(deleted=None)):
            with self.subTest(row=row), self.assertRaises(zq.QueryError):
                zq.selected(row, USER, start, end)

    def test_credentials_reused_without_copying_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td) / ".agents"
            (root / "zentao-bugfix").mkdir(parents=True)
            route = root / "zentao-bugfix/routes.json"
            route.write_text(json.dumps({"config": {"ZENTAO_BASE_URL": "https://example.test/zentao", "ZENTAO_ACCOUNT": USER}}), encoding="utf-8")
            (root / ".env").write_text("export ZENTAO_PASSWORD='env-secret'\nOTHER=ignore\n", encoding="utf-8")
            before = route.read_bytes()
            self.assertEqual(zq.credentials(td), ("https://example.test/zentao", USER, "env-secret"))
            with patch.dict(os.environ, {"ZENTAO_PASSWORD": "override"}):
                self.assertEqual(zq.credentials(td)[-1], "override")
            self.assertEqual(route.read_bytes(), before)
            self.assertFalse((root / "work-experience-accumulate").exists())

    def test_credentials_errors_do_not_reveal_contents(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            root = Path(td) / ".agents/zentao-bugfix"
            root.mkdir(parents=True)
            (root / "routes.json").write_text("{ secret-value", encoding="utf-8")
            with self.assertRaises(zq.QueryError) as caught:
                zq.credentials(td)
            self.assertNotIn("secret-value", str(caught.exception))

    def test_preserves_base_path_and_rejects_embedded_credentials(self):
        client = zq.Client("https://example.test/zentao/", USER, "secret")
        self.assertEqual(client.base, "https://example.test/zentao")
        for base in ("file:///tmp/x", "https://name:password@example.test", "https://example.test/?token=x"):
            with self.assertRaises(zq.QueryError):
                zq.Client(base, USER, "secret")

    def test_pagination_uses_server_limit_and_reads_all_pages(self):
        client = zq.Client("https://example.test", USER, "secret")
        with patch.object(client, "request", side_effect=[
                {"page": 1, "total": 3, "limit": 2, "products": [{"id": 1}, {"id": 2}]},
                {"page": 2, "total": 3, "limit": 2, "products": [{"id": 3}]}]) as request:
            self.assertEqual([r["id"] for r in client.pages("/products", "products")], [1, 2, 3])
            self.assertEqual(request.call_args.args[1]["page"], 2)
            self.assertEqual(request.call_args.args[1]["limit"], 2)

    def test_empty_page_valid_only_for_zero_total(self):
        client = zq.Client("https://example.test", USER, "secret")
        with patch.object(client, "request", return_value={"page": 1, "total": 0, "limit": 100, "products": []}):
            self.assertEqual(list(client.pages("/products", "products")), [])

    def test_pagination_failures_never_claim_completeness(self):
        first = {"page": 1, "total": 2, "limit": 1, "products": [{"id": 1}]}
        cases = ([{"products": []}], [{"page": 2, "total": 0, "limit": 1, "products": []}],
                 [{"page": 1, "total": 2, "limit": 1, "products": []}],
                 [first, {"page": 2, "total": 3, "limit": 1, "products": [{"id": 2}]}],
                 [first, {"page": 2, "total": 2, "limit": 1, "products": [{"id": 1}]}],
                 [{"page": 1, "total": 1, "limit": 1, "products": [{"id": "../bad"}]}])
        for responses in cases:
            client = zq.Client("https://example.test", USER, "secret")
            with self.subTest(responses=responses), patch.object(client, "request", side_effect=responses), self.assertRaises(zq.QueryError):
                list(client.pages("/products", "products"))

    def test_exact_identity_and_window_validated_before_login(self):
        client = zq.Client("https://example.test", USER, "secret")
        for user, start, end in (("other", START, END), (USER, END, START), (USER, "bad", END)):
            with patch.object(client, "login") as login, self.assertRaises(zq.QueryError):
                zq.query(client, user, start, end)
            login.assert_not_called()

    def test_detail_recheck_race_and_whitelist_redaction(self):
        client = zq.Client("https://example.test", USER, "secret-value")
        client.token = "dummy-token-value"
        candidates = [bug(id=1), bug(id=2), bug(id=3), bug(id=4)]
        details = [bug(id=1, title="secret-value", steps="private body", unknown="private-field"),
                   bug(id=2, status="closed"), bug(id=3, resolvedBy="other"), bug(id=4, resolvedDate=END)]
        with patch.object(client, "login"), patch.object(client, "pages", side_effect=[[{"id": 7}], candidates]), patch.object(client, "request", side_effect=details):
            data = zq.query(client, USER, START, END)
        self.assertEqual(len(data["records"]), 1)
        self.assertEqual(data["changed_candidates_skipped"], 3)
        self.assertEqual(data["records"][0]["title"], "[已脱敏]")
        self.assertNotIn("private", json.dumps(data))
        self.assertEqual(data["records"][0]["resolvedDate"], START)
        self.assertTrue(data["complete"])

    def test_detail_mismatch_or_malformed_does_not_succeed(self):
        for detail in (bug(id=2), bug(status=None), bug(product=8)):
            client = zq.Client("https://example.test", USER, "secret")
            with patch.object(client, "login"), patch.object(client, "pages", side_effect=[[{"id": 7}], [bug()]]), patch.object(client, "request", return_value=detail), self.assertRaises(zq.QueryError):
                zq.query(client, USER, START, END)

    def test_main_errors_static_without_traceback_or_secret(self):
        argv = ["zentao_query", "--workdir", "/tmp", "--start", START, "--end", END, "--resolved-by", USER]
        stdout = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(zq, "credentials", side_effect=RuntimeError("secret-raw-error")), contextlib.redirect_stdout(stdout):
            self.assertEqual(zq.main(), 3)
        self.assertNotIn("secret-raw-error", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["status"], "error")

    def test_transport_http_errors_and_request_limits_are_safe(self):
        client = zq.Client("https://example.test", USER, "secret")
        client.token = "dummy-private-token"
        error = urllib.error.HTTPError("https://example.test/?dummy-private-token", 403, "private-error", {}, None)
        with patch.object(client.opener, "open", side_effect=error), self.assertRaises(zq.QueryError) as caught:
            client.request("/products")
        self.assertNotIn("private", str(caught.exception))
        client.requests = 2000
        with patch.object(client.opener, "open") as op, self.assertRaises(zq.QueryError):
            client.request("/products")
        op.assert_not_called()

    def test_local_http_contract_only_login_post_otherwise_get(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def respond(self, data, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(("POST", self.path, payload))
                if self.path == "/zentao/api.php/v1/tokens":
                    self.respond({"token": "ephemeral"})
                else:
                    self.respond({"error": "unexpected write"}, 400)
            def do_GET(self):
                calls.append(("GET", self.path, self.headers.get("Token")))
                if "/products/7/bugs?" in self.path:
                    self.respond({"page": 1, "total": 1, "limit": 100, "bugs": [bug()]})
                elif "/products?" in self.path:
                    self.respond({"page": 1, "total": 1, "limit": 100, "products": [{"id": 7}]})
                elif self.path.endswith("/bugs/1"):
                    self.respond(bug())
                else:
                    self.respond({"error": "unknown"}, 404)
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = zq.Client(f"http://127.0.0.1:{server.server_port}/zentao", USER, "fixture-only")
            data = zq.query(client, USER, START, END)
            self.assertTrue(data["complete"])
            self.assertEqual(len(data["records"]), 1)
            self.assertEqual([c[0] for c in calls], ["POST", "GET", "GET", "GET"])
            self.assertFalse(calls[0][2]["addAction"])
            self.assertTrue(all(c[2] == "ephemeral" for c in calls[1:]))
            self.assertIn("status=resolvedbyme", calls[2][1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_redirect_not_followed(self):
        with self.assertRaises(zq.QueryError):
            zq.NoRedirect().redirect_request(None, None, 302, "private", {}, "https://other.test")


class CollectorIntegrationTests(unittest.TestCase):
    def envelope(self):
        return {"status": "ok", "data": {"window": {"start": START, "end": END}, "user_id": USER,
                "scope": "all_accessible_products", "time_basis": "resolvedDate", "complete": True,
                "products_scanned": 1, "bugs_scanned": 1, "requests": 4, "changed_candidates_skipped": 0,
                "records": [{"id": "1", "product": "7", "status": "resolved", "resolvedBy": USER,
                "resolvedDate": START, "title": "fixture", "resolution": "fixed", "url": "https://example.test/bug-view-1.html"}]}}

    def config(self):
        return {"zentao": {"user_id": USER, "query_command": ["python", "adapter", "--start", "{start}", "--end", "{end}", "--resolved-by", "{user_id}"]}}

    def test_valid_envelope_and_argument_contract(self):
        result = self.envelope()
        result["data"]["unknown"] = "discard-private"
        with patch.object(we, "run_argv", return_value=(0, json.dumps(result), "unused")) as runner:
            data, error = we.collect_zentao(self.config(), START, END)
        self.assertIsNone(error)
        self.assertEqual(len(data["records"]), 1)
        self.assertNotIn("unknown", data)
        self.assertEqual(runner.call_args.kwargs["timeout"], 540)
        self.assertIn(USER, runner.call_args.args[0])
        self.assertIn(START, runner.call_args.args[0])
        self.assertIn(END, runner.call_args.args[0])

    def test_invalid_output_is_not_a_successful_empty_result(self):
        mutations = []
        for key, value in (("complete", False), ("user_id", "other"), ("window", {}),
                           ("time_basis", "openedDate"), ("scope", "selected_products"), ("records", {}),
                           ("products_scanned", "private-statistic")):
            result = self.envelope()
            result["data"][key] = value
            mutations.append(result)
        for field, value in (("status", "closed"), ("resolvedBy", "other"), ("resolvedDate", END), ("steps", "private-body")):
            result = self.envelope()
            result["data"]["records"][0][field] = value
            mutations.append(result)
        result = self.envelope()
        result["data"]["records"].append(copy.deepcopy(result["data"]["records"][0]))
        mutations.append(result)
        raws = ["private malformed response", "[]", "null", json.dumps({"status": "error", "error": "private"})]
        raws += [json.dumps(r) for r in mutations]
        for raw in raws:
            with self.subTest(raw=raw), patch.object(we, "run_argv", return_value=(0, raw, "private-stderr")):
                data, error = we.collect_zentao(self.config(), START, END)
                self.assertTrue(error)
                self.assertFalse(data["complete"])
                self.assertEqual(data["records"], [])
                self.assertNotIn("private", json.dumps(data) + error)

    def test_failed_process_and_bad_command_do_not_store_secrets(self):
        with patch.object(we, "run_argv", return_value=(3, "private-stdout", "private-stderr")):
            data, error = we.collect_zentao(self.config(), START, END)
        self.assertNotIn("private", json.dumps(data) + error)
        for command in ([], "not-array", ["adapter", "{password}"], [None]):
            config = self.config()
            config["zentao"]["query_command"] = command
            with patch.object(we, "run_argv") as runner:
                data, error = we.collect_zentao(config, START, END)
                self.assertTrue(error)
                runner.assert_not_called()

    def test_preview_only_summary_no_writes(self):
        import argparse
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            with patch.object(we, "load_config", return_value=self.config()), patch.object(we, "window", return_value=(START, END)), patch.object(we, "run_argv", return_value=(0, json.dumps(self.envelope()), "")), contextlib.redirect_stdout(stdout):
                self.assertEqual(we.cmd_zentao_preview(argparse.Namespace(workdir=Path(td))), 0)
            data = json.loads(stdout.getvalue())["data"]
            self.assertEqual(data["matched_count"], 1)
            self.assertEqual(data["bug_ids"], ["1"])
            self.assertNotIn("title", stdout.getvalue())
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_source_failure_marks_manifest_and_preserves_other_sources(self):
        import argparse
        config = self.config()
        config.update({"dingtalk": {"notify_user_id": "u1"}, "git_repositories": [{"path": "/repo", "branches": ["main"]}], "agent_workspaces": ["/workspace"]})
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            with patch.object(we, "load_config", return_value=config), patch.object(we, "collect_dingtalk", return_value=([], None)), patch.object(we, "run_argv", return_value=(3, "raw-private", "raw-private")), patch.object(we, "collect_git", return_value=([{"fixture": True}], [])), patch.object(we, "collect_sessions", return_value=([], [])), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(we.cmd_collect(argparse.Namespace(workdir=Path(td), run=str(run))), 3)
            manifest = json.loads((run / "work/manifest.json").read_text())
            self.assertFalse(manifest["sources"]["zentao"])
            self.assertTrue(manifest["sources"]["git"])
            self.assertNotIn("raw-private", (run / "work/zentao.json").read_text())
            self.assertEqual(json.loads((run / "work/git.json").read_text()), [{"fixture": True}])


if __name__ == "__main__":
    unittest.main()
