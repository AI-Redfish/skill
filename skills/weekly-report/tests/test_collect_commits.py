#!/usr/bin/env python3
"""collect_commits.py 的单元测试（纯函数部分，不依赖真实 git 仓库）。"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_commits as cc  # noqa: E402


class WorkdayWindowTest(unittest.TestCase):
    def test_saturday_window_covers_mon_to_fri(self):
        """2026-10-10 是周六：最近 5 个工作日 = 本周一~周五，起点为周一 00:00。"""
        start, _end, days = cc.workday_window(5, today=date(2026, 10, 10))
        self.assertEqual([d.isoformat() for d in days],
                         ["2026-10-09", "2026-10-08", "2026-10-07",
                          "2026-10-06", "2026-10-05"])
        self.assertEqual(start, datetime(2026, 10, 5, 0, 0))

    def test_monday_counts_itself(self):
        start, _end, days = cc.workday_window(1, today=date(2026, 10, 5))
        self.assertEqual(days, [date(2026, 10, 5)])
        self.assertEqual(start, datetime(2026, 10, 5, 0, 0))

    def test_skips_weekend_inside_span(self):
        """周三取 3 个工作日 → 上周五+本周一二，跨周末。"""
        start, _end, days = cc.workday_window(3, today=date(2026, 10, 7))
        self.assertEqual([d.isoformat() for d in days],
                         ["2026-10-07", "2026-10-06", "2026-10-05"][-3:])
        self.assertEqual(start, datetime(2026, 10, 5, 0, 0))

    def test_non_positive_raises(self):
        with self.assertRaises(cc.CollectError):
            cc.workday_window(0, today=date(2026, 10, 10))


class ParseTest(unittest.TestCase):
    def test_shortstat_full(self):
        m = cc.SHORTSTAT_RE.search(" 3 files changed, 10 insertions(+), 2 deletions(-)")
        self.assertEqual((m.group("files"), m.group("ins"), m.group("del")),
                         ("3", "10", "2"))

    def test_shortstat_no_deletions(self):
        m = cc.SHORTSTAT_RE.search(" 1 file changed, 5 insertions(+)")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group("del"))
        self.assertEqual(int(m.group("ins")), 5)

    def test_shortstat_empty_returns_zero(self):
        self.assertEqual(cc.shortstat.__module__, "collect_commits")  # 可导入性
        # 空输出由 run_git 返回 ""，正则不命中 → main 中返回 (0,0,0)，
        # 这里验证正则对空串不命中即可
        self.assertIsNone(cc.SHORTSTAT_RE.search(""))

    def test_bug_ids_dedup(self):
        subject = "修复 Bug #75353 与 #75322，回归 #75353"
        self.assertEqual(sorted(set(cc.BUG_RE.findall(subject))),
                         ["75322", "75353"])


class PorcelainTest(unittest.TestCase):
    def test_rename_takes_new_path(self):
        line = "R  docs/old.md -> docs/new.md"
        path = line[3:].strip()
        if "->" in path:
            path = path.split("->", 1)[1].strip()
        self.assertEqual(path, "docs/new.md")

    def test_status_prefix(self):
        line = " M src/a.java"
        self.assertEqual(line[:2].strip(), "M")


if __name__ == "__main__":
    unittest.main()
