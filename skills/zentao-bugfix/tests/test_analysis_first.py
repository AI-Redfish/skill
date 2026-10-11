#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bugfix.py 分析先行（analysis-first）单元测试。

验证「先输出分析报告、再实施修复」的脚本侧支撑：
- scaffold_report 骨架含分析先行流程要求提示，三部分均留（待填写）标记
- report_part12_status 三路径：no=第一/二部分已完整 / yes=仍有（待填写）/ missing=不存在
- report_full_status：全文（含第三部分）完成度；旧版三文件布局回退兼容
- update_report_part3：只替换自动小节，不触碰 AI 填写内容

运行：python -m unittest discover -s tests -p "test_analysis_first.py" -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bugfix.py"
spec = importlib.util.spec_from_file_location("bugfix", SCRIPT)
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)

REPORT = bf.REPORT_NAME


def make_info(report_dir):
    """构造 scaffold_report / update_report_part3 所需的最小 info dict。"""
    return {
        "report_dir": str(report_dir),
        "date": "20260923",
        "base_branch": "main",
        "head_short": "abc1234",
        "branch": "bugfix/123_20260923",
        "wt_path": str(report_dir.parent),
    }


class TestScaffoldReport(unittest.TestCase):
    def test_skeleton_has_analysis_first_note_and_markers(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            path = bf.scaffold_report({}, [], [], make_info(rd),
                                      "http://zentao.example.com", "123")
            text = Path(path).read_text(encoding="utf-8")
            # 骨架含分析先行流程要求（第一/二部分先于修复补全）
            self.assertIn("分析先行", text)
            self.assertIn("之前", text)
            # 三部分结构齐全，均留（待填写）标记
            self.assertIn("## 第一部分：根因分析", text)
            self.assertIn("## 第二部分：修复方案", text)
            self.assertIn("## 第三部分：修复结果与验证", text)
            self.assertIn("方案对比与取舍", text)
            self.assertIn("（待填写）", text)
            self.assertIn("<!--REPORT-AUTO:diff-->", text)
            self.assertIn("<!--REPORT-AUTO:assets-->", text)
            self.assertEqual(bf.report_part12_status(str(rd)), "yes")
            self.assertEqual(bf.report_full_status(str(rd)), "yes")

    def test_existing_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            bf.scaffold_report({}, [], [], make_info(rd),
                               "http://zentao.example.com", "123")
            done = rd / REPORT
            done.write_text(done.read_text(encoding="utf-8").replace("（待填写）", "已补全"),
                            encoding="utf-8")
            path = bf.scaffold_report({}, [], [], make_info(rd),
                                      "http://zentao.example.com", "123")
            self.assertNotIn("（待填写）", Path(path).read_text(encoding="utf-8"))


class TestReportPart12Status(unittest.TestCase):
    def test_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.report_part12_status(td), "missing")

    def test_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, REPORT).write_text("## 第一部分：根因分析\n\n（待填写）\n",
                                        encoding="utf-8")
            self.assertEqual(bf.report_part12_status(td), "yes")

    def test_part12_complete_but_part3_pending(self):
        with tempfile.TemporaryDirectory() as td:
            text = ("# 报告\n\n## 第一部分：根因分析\n\n根因：x（src/a.py:1）\n\n"
                    "## 第二部分：修复方案\n\n改 src/a.py。\n\n"
                    "## 第三部分：修复结果与验证\n\n（待填写）\n")
            Path(td, REPORT).write_text(text, encoding="utf-8")
            self.assertEqual(bf.report_part12_status(td), "no")
            self.assertEqual(bf.report_full_status(td), "yes")

    def test_full_complete(self):
        with tempfile.TemporaryDirectory() as td:
            text = ("# 报告\n\n## 第一部分：根因分析\n\n根因：x\n\n"
                    "## 第二部分：修复方案\n\n改 src/a.py。\n\n"
                    "## 第三部分：修复结果与验证\n\n已验证。\n")
            Path(td, REPORT).write_text(text, encoding="utf-8")
            self.assertEqual(bf.report_part12_status(td), "no")
            self.assertEqual(bf.report_full_status(td), "no")


class TestLegacyLayoutCompat(unittest.TestCase):
    """旧版三文件布局（--reuse 复用旧 worktree）的完成度回退兼容。"""

    def test_legacy_part12_and_full(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.report_part12_status(td), "missing")
            Path(td, "analysis.md").write_text("已完整\n", encoding="utf-8")
            # solution.md 缺失 → 第一/二部分整体缺失（需补建）
            self.assertEqual(bf.report_part12_status(td), "missing")
            Path(td, "solution.md").write_text("（待填写）\n", encoding="utf-8")
            self.assertEqual(bf.report_part12_status(td), "yes")
            Path(td, "solution.md").write_text("已完整\n", encoding="utf-8")
            self.assertEqual(bf.report_part12_status(td), "no")
            # fix-report.md 缺失 → 全文状态缺失（需生成）
            self.assertEqual(bf.report_full_status(td), "missing")
            Path(td, "fix-report.md").write_text("已完整\n", encoding="utf-8")
            self.assertEqual(bf.report_full_status(td), "no")


class TestUpdateReportPart3(unittest.TestCase):
    def test_updates_auto_sections_only(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            bf.scaffold_report({"title": "t"}, [], [], make_info(rd),
                               "http://zentao.example.com", "123")
            path = rd / REPORT
            text = path.read_text(encoding="utf-8")
            text = text.replace("（待填写）", "AI 已填写")
            path.write_text(text, encoding="utf-8")
            diff_data = ([{"path": "src/a.py", "add": "2", "del": "1", "untracked": False}],
                         "1 个文件修改(+2/-1)", "src/a.py | +2 / -1")
            out = bf.update_report_part3(make_info(rd), "123", "t", diff_data)
            result = Path(out).read_text(encoding="utf-8")
            # 自动小节已更新（变更表格 + 产物位置），AI 内容未被触碰
            self.assertIn("| `src/a.py` | +2 / -1 |", result)
            self.assertIn("scripts/", result)
            self.assertIn("work/bug.md", result)
            self.assertIn("AI 已填写", result)
            self.assertNotIn("（修复后运行", result)

    def test_creates_skeleton_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            diff_data = ([], "未检测到代码改动", "")
            out = bf.update_report_part3(make_info(rd), "123", "t", diff_data)
            result = Path(out).read_text(encoding="utf-8")
            self.assertIn("未检测到代码改动", result)
            self.assertIn("## 第三部分：修复结果与验证", result)


class TestDocCompleteStatus(unittest.TestCase):
    def test_three_states(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.doc_complete_status(td, REPORT), "missing")
            Path(td, REPORT).write_text("（待填写）\n", encoding="utf-8")
            self.assertEqual(bf.doc_complete_status(td, REPORT), "yes")
            Path(td, REPORT).write_text("已完整\n", encoding="utf-8")
            self.assertEqual(bf.doc_complete_status(td, REPORT), "no")


if __name__ == "__main__":
    unittest.main()
