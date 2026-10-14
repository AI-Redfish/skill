import argparse
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import dingtalk_query as dq
import work_experience as we

START = "2025-01-02T00:00:00+00:00"
END = "2025-01-03T00:00:00+00:00"
SOURCE = {"scope": "all_accessible", "executable": "dws-fixture", "profile": "corp:user",
          "notify_user_id": "user", "message_timezone": "+08:00", "search_args": []}
AUTH = {"authenticated": True, "corp_id": "corp", "user_id": "user"}


def row(**changes):
    value = {"messageId": "message-1", "conversationId": "conversation-1", "senderId": "sender-1",
             "sender": "private name", "time": "2025-01-02 08:00:00", "createTime": "2025-01-02 08:00:00",
             "text": "fixture text", "unknown": "discard-private"}
    value.update(changes)
    return value


def ledger(rows=None, **changes):
    rows = [row()] if rows is None else rows
    value = {"contractVersion": "im.message-list.v1", "count": len(rows), "enrichedCount": len(rows),
             "failedCount": 0, "warningCount": 0, "pagesFetched": 1, "messages": rows,
             "failures": [], "warnings": [], "complete": True, "paginationKnown": True,
             "hasMore": False, "partial": False, "truncated": False,
             "truncatedByPageLimit": False, "truncatedByResultLimit": False,
             "queryRange": {"startTime": "2025-01-02T08:00:00+08:00", "endTime": "2025-01-03T08:00:00+08:00", "semantics": "[start,end)"}}
    value.update(changes)
    return value


SHAPE_ERROR = '{"error":{"category":"api","code":1,"message":"下游缺少明确的集合字段，无法判定结果为空"}}'


def iso_plus8(stamp):
    return dt.datetime.fromisoformat(stamp).astimezone(
        dt.timezone(dt.timedelta(hours=8))).isoformat()


def ledger_for(start, end, rows=None):
    """与指定子窗口匹配的完整 ledger。"""
    value = ledger([] if rows is None else rows)
    value["queryRange"] = {"startTime": iso_plus8(start), "endTime": iso_plus8(end),
                           "semantics": "[start,end)"}
    return value


def row_at(message_id, day, hour, **changes):
    text = "2025-01-02 %02d:00:00" % hour if day == 2 else "2025-01-03 %02d:00:00" % hour
    return row(messageId=message_id, time=text, createTime=text, **changes)


class TestListAllFallback(unittest.TestCase):
    """search 形状失败后的跨接口兑底：message list-all（本地时间格式）。"""

    TZ = dt.timezone(dt.timedelta(hours=8))

    @staticmethod
    def envelope(messages, **paging_changes):
        paging = {"hasMore": False, "pages": 1, "requestSatisfied": True,
                  "sourceExhausted": True, "truncated": False, "total": len(messages)}
        paging.update(paging_changes)
        return json.dumps({"success": True, "arguments": [], "paging": paging,
                           "result": {"conversationMessagesList": [
                               {"openConversationId": "cid1", "messages": messages}],
                               "hasMore": False, "nextCursor": ""}})

    @staticmethod
    def message(mid, minute, **changes):
        value = {"messageId": mid, "conversationId": "cid1", "senderId": "u1",
                 "createTime": "2025-01-02 09:%02d:00" % minute, "text": "hello"}
        value.update(changes)
        return value

    def test_search_failure_falls_back_to_list_all(self):
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            if argv[1] == "auth":
                return 0, json.dumps(AUTH), ""
            if argv[2] == "message":
                return 0, self.envelope([self.message("m1", 10)]), ""
            return 1, "", SHAPE_ERROR

        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        self.assertEqual(data["collection_strategy"], "list_all")
        self.assertEqual(data["records"][0]["message_id"], "m1")
        self.assertEqual(data["records"][0]["time"], "2025-01-02T01:10:00+00:00")
        la = next(a for a in calls if a[2] == "message")
        self.assertIn("2025-01-02 08:00:00", la)          # 本地时间格式
        self.assertIn("2025-01-03 08:00:00", la)
        self.assertIn("--no-reactions", la)

    @patch("dingtalk_query.time.sleep")
    def test_incomplete_or_mismatched_list_all_is_not_complete(self, sleep):
        for changes in ({"truncated": True}, {"total": 5}, {"requestSatisfied": False}):
            with self.subTest(changes=changes):
                def runner(argv, cwd=None, timeout=None):
                    if argv[1] == "auth":
                        return 0, json.dumps(AUTH), ""
                    if argv[2] == "message":
                        return 0, self.envelope([self.message("m1", 10)], **changes), ""
                    return 1, "", SHAPE_ERROR
                data, error = dq.collect(SOURCE, START, END, runner)
                self.assertFalse(data["complete"])
                self.assertEqual(data["collection_strategy"], "list_all")
                self.assertTrue(error)
                self.assertEqual(len(data["records"]), 1)

    @patch("dingtalk_query.time.sleep")
    def test_bad_envelope_fails_closed_and_falls_back_to_split(self, sleep):
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            if argv[1] == "auth":
                return 0, json.dumps(AUTH), ""
            if argv[2] == "message":
                return 0, '{"success": true}', ""
            if argv[1] == "chat" and argv[2] == "+search-msg":
                start = argv[argv.index("--start") + 1]
                end = argv[argv.index("--end") + 1]
                if start == START and end == END:
                    return 1, "", SHAPE_ERROR
            # 分窗切片：全部失败
            return 1, "", SHAPE_ERROR

        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertFalse(data["complete"])
        self.assertEqual(data["records"], [])
        self.assertIn("无法判断结果是否为空", error)
        self.assertTrue(any(a[2] == "message" for a in calls))   # 确实尝试过兑底

    @patch("dingtalk_query.time.sleep")
    def test_timezone_mismatch_blocks_list_all_fallback(self, sleep):
        source = dict(SOURCE, message_timezone="+05:00")
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            if argv[1] == "auth":
                return 0, json.dumps(AUTH), ""
            if argv[2] == "message":
                return 0, self.envelope([self.message("m1", 10)]), ""
            return 1, "", SHAPE_ERROR

        data, error = dq.collect(source, START, END, runner)
        self.assertFalse(any(a[2] == "message" for a in calls))  # 时区不一致直接不调用
        self.assertFalse(data["complete"])

    def test_normalize_list_all_dedups_skips_and_redacts(self):
        messages = [self.message("m1", 10), self.message("m1", 12),
                    self.message("m2", 30, text="password=private hello"),
                    self.message("m3", 0, createTime="2025-01-03 09:00:00")]
        data = dq._normalize_list_all(self.envelope(messages), SOURCE, START, END, self.TZ)
        self.assertEqual([r["message_id"] for r in data["records"]], ["m1", "m2"])
        self.assertEqual(data["duplicates_skipped"], 1)
        self.assertEqual(data["outside_window_skipped"], 1)
        self.assertNotIn("private", json.dumps(data))
        self.assertTrue(data["complete"])
        self.assertEqual(data["paging_total"], 4)
        self.assertEqual(data["returned_count"], 4)

    def test_normalize_list_all_fails_closed_on_unknown_envelope(self):
        bad = [None, [], '{"success":false}', '{"success":true}',
               json.dumps({"success": True, "paging": {}}),
               json.dumps({"success": True, "paging": {"hasMore": False,
                           "requestSatisfied": "x", "sourceExhausted": True,
                           "truncated": False, "total": 0, "pages": 1},
                           "result": {"conversationMessagesList": []}}),
               json.dumps({"success": True, "paging": {"hasMore": False,
                           "requestSatisfied": True, "sourceExhausted": True,
                           "truncated": False, "total": -1, "pages": 1},
                           "result": {"conversationMessagesList": []}}),
               json.dumps({"success": True, "paging": {"hasMore": False,
                           "requestSatisfied": True, "sourceExhausted": True,
                           "truncated": False, "total": 0, "pages": 1},
                           "result": {"conversationMessagesList": [{"messages": "x"}]}}),
               self.envelope([self.message(None, 10)])]
        for raw in bad:
            with self.subTest(raw=str(raw)[:40]):
                with self.assertRaises(dq.QueryError):
                    dq._normalize_list_all(raw, SOURCE, START, END, self.TZ)


class DingtalkSplitWindowTests(unittest.TestCase):
    """宽窗口触发下游字段缺失时，按有界子窗口覆盖同一区间并合并。

    端到端观测：切片越窄越稳（同一 6h 区间失败，拆成两个 3h 成功），因此用
    「窗口越宽越容易失败」的模型驱动降级路径。
    """

    # 所有消息（本地时间 +08:00）；按请求区间过滤，模拟真实返回
    ALL_ROWS = [
        ("a", "2025-01-02 09:00:00"),     # 01:00Z
        ("a", "2025-01-02 10:30:00"),     # 02:30Z，同 ID，用于去重
        ("b", "2025-01-02 13:00:00"),     # 05:00Z
        ("c", "2025-01-02 18:00:00"),     # 10:00Z
        ("d", "2025-01-02 23:00:00"),     # 15:00Z
        ("e", "2025-01-03 06:00:00"),     # 次日 22:00Z
    ]

    def _rows_in(self, start, end):
        start_dt, end_dt = dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end)
        tz = dt.timezone(dt.timedelta(hours=8))
        picked = []
        for message_id, local in self.ALL_ROWS:
            when = dt.datetime.fromisoformat(local.replace(" ", "T")).replace(tzinfo=tz)
            if start_dt <= when < end_dt:
                picked.append(row(messageId=message_id, time=local, createTime=local))
        return picked

    def _runner(self, calls=None, wide_fails_hours=None, fail_start_band=None):
        """full 窗口总是失败；可选：超过 wide_fails_hours 的切片也失败。"""
        def runner(argv, cwd=None, timeout=None):
            if calls is not None:
                calls.append(argv)
            if argv[1] == "auth":
                return 0, json.dumps(AUTH), ""
            if argv[2] == "message":
                # list-all 兑底不可用，逼出分窗路径
                return 1, "", '{"error":{"category":"api","message":"list-all unavailable"}}'
            start = argv[argv.index("--start") + 1]
            end = argv[argv.index("--end") + 1]
            if start == START and end == END:
                return 1, "", SHAPE_ERROR
            span = dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)
            if wide_fails_hours is not None and span > dt.timedelta(hours=wide_fails_hours):
                return 1, "", SHAPE_ERROR
            if fail_start_band and fail_start_band[0] <= start < fail_start_band[1]:
                return 1, "", SHAPE_ERROR
            return 0, json.dumps(ledger_for(start, end, self._rows_in(start, end))), ""
        return runner

    @patch("dingtalk_query.time.sleep")
    def test_split_covers_window_and_dedups_across_boundary(self, sleep):
        data, error = dq.collect(SOURCE, START, END, self._runner())
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        self.assertEqual(data["collection_strategy"], "split")
        self.assertEqual(data["sub_windows"], 8)
        self.assertEqual(data["failed_windows"], 0)
        self.assertEqual([r["message_id"] for r in data["records"]], ["a", "b", "c", "d", "e"])
        self.assertEqual(data["duplicates_skipped"], 1)
        self.assertEqual(data["window"], {"start": START, "end": END})
        self.assertEqual(data["outside_window_skipped"], 0)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    @patch("dingtalk_query.time.sleep")
    def test_failed_slice_is_halved_until_it_succeeds(self, sleep):
        data, error = dq.collect(SOURCE, START, END, self._runner(wide_fails_hours=2))
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        self.assertEqual(data["sub_windows"], 16)      # 8 个 3h 全部二分一次
        self.assertEqual(data["failed_windows"], 0)
        self.assertEqual([r["message_id"] for r in data["records"]], ["a", "b", "c", "d", "e"])
        self.assertEqual(data["duplicates_skipped"], 1)   # a 在两个相邻半区重复且只留一条

    @patch("dingtalk_query.time.sleep")
    def test_unfixable_slice_keeps_evidence_and_marks_incomplete(self, sleep):
        band = ("2025-01-02T05:00:00+00:00", "2025-01-02T09:00:00+00:00")
        data, error = dq.collect(SOURCE, START, END, self._runner(fail_start_band=band))
        self.assertFalse(data["complete"])
        self.assertIn("分窗采集不完整", error)
        self.assertIn("4 个切片失败", error)             # 3h -> 1.5h -> 45min，叶子全部失败
        self.assertEqual(data["failed_windows"], 4)
        self.assertEqual([r["message_id"] for r in data["records"]], ["a", "b", "c", "d", "e"])

    @patch("dingtalk_query.time.sleep")
    def test_all_slices_failing_returns_original_diagnosis(self, sleep):
        band = (START, "2025-01-03T00:00:01+00:00")
        data, error = dq.collect(SOURCE, START, END, self._runner(fail_start_band=band))
        self.assertEqual(data["records"], [])
        self.assertFalse(data["complete"])
        self.assertIn("无法判断结果是否为空", error)

    @patch("dingtalk_query.time.sleep")
    def test_circuit_breaker_stops_wasted_calls_during_outage(self, sleep):
        calls = []
        data, error = dq.collect(SOURCE, START, END,
                                 self._runner(calls=calls, fail_start_band=(START, END)))
        searches = [c for c in calls if any("search-msg" in a for a in c)]
        # 全部形状失败时，熔断后不再烧完整个预算
        self.assertLess(len(searches), 3 + 24)
        self.assertFalse(data["complete"])
        self.assertTrue(error)
        self.assertEqual(data["records"], [])

    @patch("dingtalk_query.time.sleep")
    def test_circuit_breaker_does_not_trigger_when_slices_recover(self, sleep):
        data, error = dq.collect(SOURCE, START, END, self._runner())
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        self.assertEqual(data["sub_windows"], 8)

    @patch("dingtalk_query.time.sleep")
    def test_sub_query_budget_is_bounded(self, sleep):
        calls = []
        data, error = dq.collect(SOURCE, START, END,
                                 self._runner(calls=calls, fail_start_band=(START, END)))
        searches = [c for c in calls if any("search-msg" in a for a in c)]
        # 1 次宽窗口 + 最多 shape_retries 次退避重试 + 最多 2×max_sub_windows 次切片
        self.assertLessEqual(len(searches), 3 + 24)
        self.assertFalse(data["complete"])
        self.assertTrue(error)

    @patch("dingtalk_query.time.sleep")
    def test_shape_retry_schedule_is_bounded_and_configurable(self, sleep):
        payload = '{"error":{"category":"api","message":"下游缺少明确的集合字段，无法判定结果为空"}}'

        def make_runner(calls):
            def runner(argv, cwd=None, timeout=None):
                calls.append(argv)
                if argv[1] == "auth":
                    return 0, json.dumps(AUTH), ""
                return 1, "", payload
            return runner

        for configured, expected_waits in ((0, []), (1, [5]), (3, [5, 10, 20])):
            with self.subTest(configured=configured):
                sleep.reset_mock()
                calls = []
                # 关闭分窗（单切片）只看退避序列本身
                source = dict(SOURCE, shape_retries=configured, fallback_window_hours=24,
                              max_sub_windows=2)
                data, error = dq.collect(source, START, END, make_runner(calls))
                self.assertEqual([c.args[0] for c in sleep.call_args_list], expected_waits)
                self.assertFalse(data["complete"])
                self.assertIn("无法判断结果是否为空", error)

    @patch("dingtalk_query.time.sleep")
    def test_server_instructed_retry_happens_at_most_once(self, sleep):
        # 非形状类错误不进入退避序列，只按服务端时间重试一次
        payload = json.dumps({"error": {"retryable": True, "retry_after_seconds": 2}})
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            if argv[1] == "auth":
                return 0, json.dumps(AUTH), ""
            return 1, "", payload

        data, error = dq.collect(SOURCE, START, END, runner)
        searches = [c for c in calls if any("search-msg" in a for a in c)]
        self.assertEqual(len(searches), 2)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2.0])
        self.assertTrue(error)

    def test_sub_windows_cover_exactly_and_respect_bounds(self):
        bounds = dq._sub_windows(START, END, 3, 12)
        self.assertEqual(len(bounds), 8)
        self.assertEqual(bounds[0][0], START)
        self.assertEqual(bounds[-1][1], END)
        for (_, previous_end), (next_start, _) in zip(bounds, bounds[1:]):
            self.assertEqual(previous_end, next_start)
        self.assertEqual(len(dq._sub_windows(START, END, 1, 4)), 4)    # 超出宽度预算时自动加宽
        self.assertEqual(dq._sub_windows(START, END, 24, 4), [])       # 无法覆盖就不切
        self.assertEqual(dq._sub_windows(END, START, 3, 12), [])

    def test_invalid_split_configuration_is_rejected_before_any_call(self):
        for changes in ({"fallback_window_hours": 0}, {"fallback_window_hours": "3"},
                        {"fallback_window_hours": True}, {"fallback_window_hours": 25},
                        {"split_max_depth": 4}, {"split_max_depth": -1},
                        {"shape_retries": 4}, {"shape_retries": -1}, {"shape_retries": "2"},
                        {"max_sub_windows": 1}, {"max_sub_windows": 25},
                        {"max_sub_windows": None}):
            with self.subTest(changes=changes):
                runner = Mock()
                data, error = dq.collect(dict(SOURCE, **changes), START, END, runner)
                self.assertTrue(error)
                runner.assert_not_called()


class DingtalkQueryTests(unittest.TestCase):
    def test_time_conversion_and_whitelisted_evidence(self):
        data = dq.normalize(json.dumps(ledger()), SOURCE, START, END)
        self.assertTrue(data["complete"])
        self.assertEqual(data["records"][0]["time"], START)
        self.assertTrue(data["records"][0]["content_is_untrusted_data"])
        self.assertNotIn("private", json.dumps(data))

    def test_half_open_boundary_and_dedup_per_conversation(self):
        rows = [row(), row(), row(messageId="end", time="2025-01-03 08:00:00", createTime="2025-01-03 08:00:00"),
                row(messageId="old", time="2025-01-02 07:59:59", createTime="2025-01-02 07:59:59"),
                row(conversationId="conversation-2")]
        data = dq.normalize(json.dumps(ledger(rows)), SOURCE, START, END)
        self.assertEqual(len(data["records"]), 2)
        self.assertEqual(data["duplicates_skipped"], 1)
        self.assertEqual(data["outside_window_skipped"], 2)

    def test_empty_complete_ledger_valid(self):
        data = dq.normalize(json.dumps(ledger([])), SOURCE, START, END)
        self.assertTrue(data["complete"])
        self.assertEqual(data["records"], [])

    def test_page_limits_failures_and_warnings_are_incomplete(self):
        for changes in ({"complete": False}, {"hasMore": True}, {"paginationKnown": False},
                        {"partial": True}, {"truncated": True}, {"truncatedByPageLimit": True},
                        {"truncatedByResultLimit": True}, {"enrichedCount": 0},
                        {"failedCount": 1, "failures": [{"raw": "private"}]},
                        {"warningCount": 1, "warnings": ["private-warning"]}):
            with self.subTest(changes=changes):
                data = dq.normalize(json.dumps(ledger(**changes)), SOURCE, START, END)
                self.assertFalse(data["complete"])
                self.assertEqual(len(data["records"]), 1)
                self.assertNotIn("private", json.dumps(data))

    def test_unknown_contract_time_window_fields_fail_closed(self):
        cases = [ledger(contractVersion="unknown"), ledger(count=2), ledger(failedCount=1),
                 ledger(pagesFetched="private"), ledger(complete="true"), ledger(messages={}),
                 ledger(failures=None), ledger(queryRange={}), ledger(enrichedCount=2)]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(dq.QueryError):
                dq.normalize(json.dumps(payload), SOURCE, START, END)
        for raw in ("private-not-json", "null", "[]", "{\"success\":false}"):
            with self.subTest(raw=raw), self.assertRaises(dq.QueryError):
                dq.normalize(raw, SOURCE, START, END)

    def test_missing_ids_malformed_time_and_inconsistent_time_fail(self):
        for changes in ({"messageId": None}, {"conversationId": ""}, {"senderId": 1},
                        {"createTime": "bad"}, {"time": "2025-01-02 09:00:00"}, {"text": None}):
            with self.subTest(changes=changes), self.assertRaises(dq.QueryError):
                dq.normalize(json.dumps(ledger([row(**changes)])), SOURCE, START, END)

    def test_credentials_and_scope_flags_not_allowed(self):
        for args in (["--start", START], ["--profile", "other:user"], ["--download-resources", "true"],
                     ["--client-secret", "private"], ["--mock", "true"], ["--group", "other"],
                     ["--limit", "31"], ["--page-limit", "41"], ["--limit", "1", "--limit", "2"],
                     ["--page-all"], "not-array", [None, "2"]):
            source = dict(SOURCE, search_args=args)
            runner = Mock()
            data, error = dq.collect(source, START, END, runner)
            self.assertTrue(error)
            self.assertFalse(data["complete"])
            runner.assert_not_called()

    def test_config_identity_timezone_and_scope_required(self):
        for changes in ({"scope": "selected"}, {"profile": "corp:other"}, {"profile": "corp:user,other:user"},
                        {"profile": None}, {"message_timezone": None}, {"message_timezone": "+15:00"},
                        {"executable": ""}):
            runner = Mock()
            data, error = dq.collect(dict(SOURCE, **changes), START, END, runner)
            self.assertTrue(error)
            runner.assert_not_called()

    def test_fixed_command_and_identity_check_no_write_flags(self):
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (0, json.dumps(ledger()), "")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        cmd = runner.call_args.args[0]
        self.assertEqual(cmd[:3], ["dws-fixture", "chat", "+search-msg"])
        for flag in ("--start", "--end", "--profile", "--format", "--page-all"):
            self.assertEqual(cmd.count(flag), 1)
        self.assertIn(START, cmd)
        self.assertIn(END, cmd)
        self.assertNotIn("--yes", cmd)
        self.assertNotIn("--download-resources", cmd)
        self.assertIn("--no-reactions", cmd)
        self.assertIn("--limit", cmd)
        self.assertEqual(cmd[cmd.index("--limit") + 1], "30")
        self.assertEqual(runner.call_args.kwargs["timeout"], 600)

    @patch("dingtalk_query.time.sleep")
    def test_retryable_dws_error_retries_once_after_bounded_delay(self, sleep):
        retryable = json.dumps({"error": {"retryable": True, "retry_after_seconds": 2}})
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (1, "", retryable),
                                   (0, json.dumps(ledger()), "")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        self.assertEqual(runner.call_count, 3)
        sleep.assert_called_once_with(2.0)

    @patch("dingtalk_query.time.sleep")
    def test_top_level_dws_error_envelope_can_retry(self, sleep):
        retryable = json.dumps({"success": False, "code": "RATE_LIMIT_ERROR",
                                "retryable": True, "retry_after_seconds": 1})
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (1, "", retryable),
                                   (0, json.dumps(ledger()), "")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        sleep.assert_called_once_with(1.0)

    def test_long_or_invalid_retry_delay_fails_closed(self):
        for error_payload in (
                {"retryable": True, "retry_after_seconds": 61},
                {"retryable": True, "retry_after_seconds": "bad"},
                {"retryable": True, "next_retry_at": "bad"}):
            with self.subTest(error_payload=error_payload):
                runner = Mock(side_effect=[(0, json.dumps(AUTH), ""),
                                           (1, "", json.dumps({"error": error_payload}))])
                data, error = dq.collect(SOURCE, START, END, runner)
                self.assertTrue(error)
                self.assertEqual(runner.call_count, 2)

    @patch("dingtalk_query.time.sleep")
    def test_missing_collection_error_retries_then_splits_and_fails_closed(self, sleep):
        payload = '{"error":{"category":"api","code":1,"message":"下游缺少明确的集合字段，无法判定结果为空"}}'
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            if argv[1] == "auth":
                return 0, json.dumps(AUTH), ""
            return 1, "", payload

        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertFalse(data["complete"])
        self.assertIn("无法判断结果是否为空", error)
        self.assertNotIn("category", error)
        searches = [c for c in calls if any("search-msg" in a for a in c)]
        self.assertLessEqual(len(searches), 3 + 24)      # 宽窗口 + 退避重试 + 有界切片
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    @patch("dingtalk_query.time.sleep")
    def test_missing_collection_error_can_recover_on_retry(self, sleep):
        payload = '{"error":{"reason":"missing_collection"}}'
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (1, "", payload),
                                   (0, json.dumps(ledger()), "")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertTrue(data["complete"])
        self.assertEqual(runner.call_count, 3)

    @patch("dingtalk_query.time.sleep")
    def test_plain_text_missing_collection_marker_is_retried_once(self, sleep):
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""),
                                   (1, "", "下游缺少明确的集合字段，无法判定结果为空"),
                                   (0, json.dumps(ledger()), "")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertTrue(data["complete"])

    def test_auth_permission_and_confirmation_errors_are_never_retried(self):
        for payload in ('{"error":{"category":"auth","retryable":true}}',
                        '{"error":{"category":"permission","retryable":true}}',
                        '{"error":{"reason":"confirmation_required","retryable":true}}'):
            with self.subTest(payload=payload):
                runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (1, "", payload)])
                data, error = dq.collect(SOURCE, START, END, runner)
                self.assertTrue(error)
                self.assertEqual(runner.call_count, 2)


    def test_retryable_dws_error_in_stdout_is_recognized_but_partial_output_is_not_retried(self):
        retry_error = json.dumps({"error": {"retryable": True, "retry_after_seconds": 0}})
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (1, retry_error, ""), (0, json.dumps(ledger()), "")])
        with patch("dingtalk_query.time.sleep"):
            data, error = dq.collect(SOURCE, START, END, runner)
        self.assertIsNone(error)
        self.assertEqual(runner.call_count, 3)
        partial_runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (1, retry_error + "partial", "")])
        data, error = dq.collect(SOURCE, START, END, partial_runner)
        self.assertTrue(error)
        self.assertEqual(partial_runner.call_count, 2)

    def test_auth_failure_or_identity_change_stops_before_search(self):

        for auth in ({"authenticated": False}, dict(AUTH, user_id="other"), dict(AUTH, corp_id="other"), []):
            runner = Mock(return_value=(0, json.dumps(auth), "private-stderr"))
            data, error = dq.collect(SOURCE, START, END, runner)
            self.assertTrue(error)
            self.assertEqual(runner.call_count, 1)
            self.assertNotIn("private", json.dumps(data) + error)

    def test_nonzero_search_discards_private_raw_output(self):
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (7, "private-result", "password=private-error")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertFalse(data["complete"])
        self.assertEqual(data["records"], [])
        self.assertNotIn("private", json.dumps(data) + error)

    def test_zero_exit_partial_keeps_evidence_and_marks_failed(self):
        runner = Mock(side_effect=[(0, json.dumps(AUTH), ""), (0, json.dumps(ledger(truncatedByPageLimit=True, complete=False)), "")])
        data, error = dq.collect(SOURCE, START, END, runner)
        self.assertTrue(error)
        self.assertFalse(data["complete"])
        self.assertEqual(len(data["records"]), 1)

    def test_excerpt_redaction_and_length_limit(self):
        raw = "password=private\n令牌 private\nAuthorization: Bearer private\nhttps://x.test/?key=private\na@example.test 13812345678\n" + "x" * 2000
        text = dq.excerpt(raw)
        self.assertNotIn("private", text)
        self.assertNotIn("13812345678", text)
        self.assertNotIn("a@example.test", text)
        self.assertLessEqual(len(text), 1000)

    def test_invalid_window_never_calls_dws(self):
        for start, end in ((END, START), (START, START), ("bad", END), ("2025-01-02 00:00:00", END)):
            runner = Mock()
            data, error = dq.collect(SOURCE, start, end, runner)
            self.assertTrue(error)
            runner.assert_not_called()

    def test_partial_source_marks_manifest_and_preserves_records(self):
        config = {"dingtalk": SOURCE, "git_repositories": [{"path": "/repo", "branches": ["main"]}],
                  "zentao": {"query_command": ["fixture"], "user_id": "fixture"}, "agent_workspaces": ["/workspace"]}
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            partial = ledger(complete=False, truncatedByPageLimit=True)
            with patch.object(we, "load_config", return_value=config), patch.object(we, "window", return_value=(START, END)), patch.object(we, "run_argv", side_effect=[(0, json.dumps(AUTH), ""), (0, json.dumps(partial), "")]), patch.object(we, "collect_zentao", return_value=({"fixture": True}, None)), patch.object(we, "collect_git", return_value=([], [])), patch.object(we, "collect_sessions", return_value=([], [])), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(we.cmd_collect(argparse.Namespace(workdir=Path(td), run=str(run))), 3)
            manifest = json.loads((run / "work/manifest.json").read_text())
            data = json.loads((run / "work/dingtalk.json").read_text())
            self.assertFalse(manifest["sources"]["dingtalk"])
            self.assertTrue(manifest["sources"]["zentao"])
            self.assertFalse(data["complete"])
            self.assertEqual(len(data["records"]), 1)
            self.assertNotIn("private", (run / "work/dingtalk.json").read_text())

    def test_preview_summary_only_no_files_or_messages(self):
        runner_results = [(0, json.dumps(AUTH), ""), (0, json.dumps(ledger()), "")]
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            with patch.object(we, "load_config", return_value={"dingtalk": SOURCE}), patch.object(we, "window", return_value=(START, END)), patch.object(we, "run_argv", side_effect=runner_results), contextlib.redirect_stdout(stdout):
                self.assertEqual(we.cmd_dingtalk_preview(argparse.Namespace(workdir=Path(td))), 0)
            data = json.loads(stdout.getvalue())["data"]
            self.assertEqual(data["matched_count"], 1)
            self.assertNotIn("records", data)
            self.assertNotIn("fixture text", stdout.getvalue())
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
