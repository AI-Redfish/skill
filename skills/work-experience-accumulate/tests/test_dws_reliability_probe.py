#!/usr/bin/env python3
"""dws_reliability_probe 的纯函数与 argv 构造测试。"""
import datetime as dt
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import dws_reliability_probe as rp
import dingtalk_query as dq

ARGS = ["--limit", "30", "--page-limit", "40"]
TZ = dt.timezone(dt.timedelta(hours=8))


class ArgvTests(unittest.TestCase):
    def test_search_argv_has_paging_and_format(self):
        argv = dq._search_argv("dws.exe", "corp:user", ARGS,
                               "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
        self.assertEqual(argv[:4], ["dws.exe", "chat", "+search-msg", "--limit"])
        for flag in ("--page-all", "--order", "asc", "--no-reactions", "--start",
                     "--end", "--profile", "--format"):
            self.assertIn(flag, argv)
        self.assertNotIn("--yes", argv)

    def test_list_all_argv_uses_local_format(self):
        argv = dq._list_all_argv("dws.exe", "corp:user",
                                 "2026-01-01 08:00:00", "2026-01-02 08:00:00", 30, 40)
        self.assertEqual(argv[:4], ["dws.exe", "chat", "message", "list-all"])
        self.assertIn("2026-01-01 08:00:00", argv)
        self.assertIn("--page-all", argv)
        self.assertIn("--no-reactions", argv)


class ClassifyTests(unittest.TestCase):
    def test_ok_when_stdout_has_payload(self):
        self.assertEqual(rp.classify(500, ""), "ok")

    def test_shape_error_classified(self):
        err = '{"error":{"category":"api","message":"下游缺少明确的集合字段，无法判定结果为空"}}'
        self.assertEqual(rp.classify(0, err), "shape")

    def test_dws_error_and_unknown_classified_without_raw_text(self):
        err = '{"error":{"category":"api","server_error_code":"RATE_LIMIT_ERROR"}}'
        self.assertEqual(rp.classify(0, err), "dws_error:RATE_LIMIT_ERROR")
        self.assertEqual(rp.classify(0, "plain text failure"), "unknown")


class MessageCountTests(unittest.TestCase):
    def test_search_count(self):
        self.assertEqual(rp.message_count("search", '{"count": 7}'), 7)
        self.assertIsNone(rp.message_count("search", "not-json"))

    def test_list_all_counts_messages_across_conversations(self):
        payload = json.dumps({"result": {"conversationMessagesList": [
            {"messages": [{}, {}, {}]}, {"messages": [{}]}]}})
        self.assertEqual(rp.message_count("list_all", payload), 4)


class SummarizeTests(unittest.TestCase):
    def test_counts_ok_fail_and_class_distribution(self):
        rows = [
            {"entry": "search", "ok": True, "class": "ok", "count": 10},
            {"entry": "search", "ok": True, "class": "ok", "count": 12},
            {"entry": "search", "ok": False, "class": "shape", "count": None},
            {"entry": "list_all", "ok": False, "class": "dws_error:X", "count": None},
        ]
        summary = rp.summarize(rows)
        self.assertEqual(summary["search"]["ok"], 2)
        self.assertEqual(summary["search"]["fail"], 1)
        self.assertEqual(summary["search"]["by_class"], {"shape": 1})
        self.assertEqual(summary["search"]["counts"], [10, 12])
        self.assertEqual(summary["list_all"]["fail"], 1)
        self.assertEqual(summary["list_all"]["by_class"], {"dws_error:X": 1})

    def test_probe_once_builds_entries_and_reports_seconds(self):
        captured = []

        def runner(argv, timeout=600):
            captured.append(argv)
            if argv[2] == "+search-msg":
                return 0, '{"count": 3}', ""
            return 0, json.dumps({"paging": {"total": 3},
                                  "result": {"conversationMessagesList": [
                                      {"messages": [{}, {}, {}]}]}}), ""

        rows = []
        for entry in ("search", "list_all"):
            rows.append(rp.probe_once(entry, "dws.exe", "corp:user", TZ, ARGS,
                                      "2026-01-01T00:00:00+00:00",
                                      "2026-01-02T00:00:00+00:00", "", runner))
        self.assertTrue(all(r["ok"] for r in rows))
        self.assertEqual([r["count"] for r in rows], [3, 3])
        self.assertTrue(all(r["seconds"] >= 0 for r in rows))
        self.assertIn("--start", captured[0])


if __name__ == "__main__":
    unittest.main()
