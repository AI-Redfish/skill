#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bugfix.py 分析先行（analysis-first）单元测试。

验证「先输出分析报告、再实施修复」的脚本侧支撑：
- scaffold_analysis 骨架含分析先行流程要求提示，且分析章节留（待填写）标记
- analysis_complete_status 三路径：no=已完整 / yes=仍有（待填写）/ missing=文件不存在

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


def make_info(report_dir):
    """构造 scaffold_analysis 所需的最小 info dict。"""
    return {
        "report_dir": str(report_dir),
        "date": "20260923",
        "base_branch": "main",
        "head_short": "abc1234",
        "branch": "bugfix/123_20260923",
        "wt_path": str(report_dir.parent),
    }


class TestScaffoldAnalysis(unittest.TestCase):
    def test_skeleton_has_analysis_first_note_and_markers(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "bugfix" / "123"
            rd.mkdir(parents=True)
            path = bf.scaffold_analysis({}, [], [], make_info(rd),
                                        "http://zentao.example.com", "123")
            text = Path(path).read_text(encoding="utf-8")
            # 骨架含分析先行流程要求（先补全本报告再改代码）
            self.assertIn("分析先行", text)
            self.assertIn("之前", text)
            self.assertIn("修复方案", text)
            # 分析性章节留（待填写）标记（供 analysis_complete_status 检测）
            self.assertIn("（待填写）", text)
            self.assertEqual(bf.analysis_complete_status(str(rd)), "yes")

    def test_existing_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "bugfix" / "123"
            rd.mkdir(parents=True)
            bf.scaffold_analysis({}, [], [], make_info(rd),
                                 "http://zentao.example.com", "123")
            done = (rd / "analysis.md")
            done.write_text(done.read_text(encoding="utf-8").replace("（待填写）", "已补全"),
                            encoding="utf-8")
            path = bf.scaffold_analysis({}, [], [], make_info(rd),
                                        "http://zentao.example.com", "123")
            self.assertNotIn("（待填写）", Path(path).read_text(encoding="utf-8"))


class TestAnalysisCompleteStatus(unittest.TestCase):
    def test_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.analysis_complete_status(td), "missing")

    def test_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "analysis.md").write_text("## 2. 关键信息提取\n\n（待填写）\n",
                                               encoding="utf-8")
            self.assertEqual(bf.analysis_complete_status(td), "yes")

    def test_complete(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "analysis.md").write_text("# 分析报告\n\n根因：xxx（文件:行号）\n",
                                               encoding="utf-8")
            self.assertEqual(bf.analysis_complete_status(td), "no")


if __name__ == "__main__":
    unittest.main()
