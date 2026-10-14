#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bugfix.py 分析先行（analysis-first）单元测试。

验证「先输出分析报告、再实施修复」的脚本侧支撑：
- scaffold_analysis 骨架含分析先行流程要求提示，且分析章节留（待填写）标记
- analysis_complete_status 三路径：no=已完整 / yes=仍有（待填写）/ missing=文件不存在

运行：python -m unittest discover -s tests -p "test_analysis_first.py" -v
"""
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            path = bf.scaffold_analysis({}, [], [], make_info(rd),
                                        "http://zentao.example.com", "123")
            text = Path(path).read_text(encoding="utf-8")
            # 骨架含分析先行流程要求（先补全本报告与 solution.md 再改代码）
            self.assertIn("分析先行", text)
            self.assertIn("之前", text)
            self.assertIn("solution.md", text)
            self.assertIn("解决方案", text)
            # 分析性章节留（待填写）标记（供 analysis_complete_status 检测）
            self.assertIn("（待填写）", text)
            self.assertEqual(bf.analysis_complete_status(str(rd)), "yes")

    def test_existing_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
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


class TestScaffoldSolution(unittest.TestCase):
    """solution.md（解决方案）骨架与完成度校验。"""

    def test_skeleton_and_status(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            path = bf.scaffold_solution({"title": "t"}, make_info(rd), "123")
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("解决方案", text)
            self.assertIn("analysis.md", text)          # 关联分析报告
            self.assertIn("方案对比与取舍", text)
            self.assertIn("影响面评估", text)
            self.assertIn("风险与回滚", text)
            self.assertIn("验证计划", text)
            self.assertIn("（待填写）", text)
            self.assertEqual(bf.solution_complete_status(str(rd)), "yes")

    def test_existing_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            bf.scaffold_solution({}, make_info(rd), "123")
            done = rd / "solution.md"
            done.write_text(done.read_text(encoding="utf-8").replace("（待填写）", "已补全"),
                            encoding="utf-8")
            path = bf.scaffold_solution({}, make_info(rd), "123")
            self.assertNotIn("（待填写）", Path(path).read_text(encoding="utf-8"))
            self.assertEqual(bf.solution_complete_status(str(rd)), "no")

    def test_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.solution_complete_status(td), "missing")


class TestDocCompleteStatus(unittest.TestCase):
    def test_three_states(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.doc_complete_status(td, "analysis.md"), "missing")
            Path(td, "analysis.md").write_text("（待填写）\n", encoding="utf-8")
            self.assertEqual(bf.doc_complete_status(td, "analysis.md"), "yes")
            Path(td, "analysis.md").write_text("已完整\n", encoding="utf-8")
            self.assertEqual(bf.doc_complete_status(td, "analysis.md"), "no")


class TestFrontendAttributionSection(unittest.TestCase):
    """问题归属：骨架必填章节 + 结论行提取 + 前端工作区只读分析声明。"""

    def _scaffold(self, td, frontend=None):
        rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
        rd.mkdir(parents=True)
        info = make_info(rd)
        if frontend is not None:
            info["frontend_workspaces"] = frontend
        bf.scaffold_analysis({}, [], [], info, "http://zentao.example.com", "123")
        return rd

    def test_skeleton_has_required_attribution_section(self):
        with tempfile.TemporaryDirectory() as td:
            rd = self._scaffold(td, ["D:/develop/project/wukong"])
            text = (rd / "analysis.md").read_text(encoding="utf-8")
            self.assertIn("## 2. 问题归属", text)
            self.assertIn("前端问题", text)
            self.assertIn("后端问题", text)
            self.assertIn("待确认", text)
            self.assertIn("**结论**:", text)              # 结论行格式要求
            self.assertIn("D:/develop/project/wukong", text)   # 自动列出前端工作区
            self.assertIn("只读", text)
            self.assertIn("不是修复目标", text)
            # 章节编号连续，分析性章节仍留（待填写）标记
            self.assertIn("## 3. 关键信息提取", text)
            self.assertIn("## 6. 遗留问题", text)
            self.assertEqual(bf.analysis_complete_status(str(rd)), "yes")

    def test_skeleton_without_frontend_says_unverifiable(self):
        with tempfile.TemporaryDirectory() as td:
            rd = self._scaffold(td)
            text = (rd / "analysis.md").read_text(encoding="utf-8")
            self.assertIn("未配置", text)
            self.assertIn("无法用本地代码验证", text)

    def test_solution_requires_consistent_landing_zone(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            path = bf.scaffold_solution({"title": "t"}, make_info(rd), "123")
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("问题归属", text)
            self.assertIn("改动范围", text)
            self.assertIn("其他工作空间", text)
            self.assertIn("不写本地代码改动", text)
            self.assertEqual(bf.solution_complete_status(str(rd)), "yes")


class TestAnalysisLayerAttribution(unittest.TestCase):
    """analysis_layer_attribution：只从「问题归属」章节的 `**结论**:` 行提取。"""

    def _write(self, td, body):
        Path(td, "analysis.md").write_text(body, encoding="utf-8")
        return td

    def test_missing_and_unparsed_states(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.analysis_layer_attribution(td), "missing")
            # 有「问题归属」章节但没有结论行
            self._write(td, "## 2. 问题归属（前端问题 / 后端问题 / 前后端 / 待确认）\n\n（待填写）\n")
            self.assertEqual(bf.analysis_layer_attribution(td), "unparsed")
            # 没有「问题归属」章节
            self._write(td, "## 2. 关键信息提取\n\n**结论**: 前端问题\n")
            self.assertEqual(bf.analysis_layer_attribution(td), "unparsed")

    def test_extracts_each_choice_and_prefers_frontend_backend_hyphen(self):
        cases = [("前端问题", "前端问题"), ("后端问题", "后端问题"),
                 ("前后端", "前后端"), ("待确认", "待确认")]
        for written, expected in cases:
            with self.subTest(written=written), tempfile.TemporaryDirectory() as td:
                self._write(td, "## 2. 问题归属（前端问题 / 后端问题 / 前后端 / 待确认）\n\n"
                                "**结论**: %s（置信度：高）\n\n判定依据：`a.vue:12`\n\n"
                                "## 3. 关键信息提取\n\n**结论**: 不相关的一句\n" % written)
                self.assertEqual(bf.analysis_layer_attribution(td), expected)
        # 「前后端」不能被误判为「后端」
        with tempfile.TemporaryDirectory() as td:
            self._write(td, "## 2. 问题归属\n\n> **结论**: 前后端（前端缺字段，后端也返回空）\n")
            self.assertEqual(bf.analysis_layer_attribution(td), "前后端")

    def test_section_boundary_and_guidance_line_are_not_misread(self):
        with tempfile.TemporaryDirectory() as td:
            # 章节结束后的其他章节结论不影响归属
            self._write(td, "## 2. 问题归属\n\n**结论**: 后端问题\n\n"
                            "## 3. 根因分析\n\n**结论**: 前端问题（仅描述症状位置）\n")
            self.assertEqual(bf.analysis_layer_attribution(td), "后端问题")

    def test_default_skeleton_is_not_a_conclusion(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "123"
            rd.mkdir(parents=True)
            bf.scaffold_analysis({}, [], [], make_info(rd), "http://z", "123")
            # 骨架里的「填写要求」行包含候选词，但不得被当成结论
            self.assertEqual(bf.analysis_layer_attribution(str(rd)), "unparsed")


class TestFrontendWorkspaces(unittest.TestCase):
    """FRONTEND_WORKSPACES：只读分析工作区的解析与配置写入。"""

    def test_parse_skips_blank_and_rejects_non_string(self):
        cfg = {"FRONTEND_WORKSPACES": " D:/a , /b ,, "}
        self.assertEqual(len(bf.frontend_workspaces(cfg, "D:/project")), 2)
        self.assertEqual(bf.frontend_workspaces({}, "D:/p"), [])
        self.assertEqual(bf.frontend_workspaces({"FRONTEND_WORKSPACES": ""}, "D:/p"), [])
        self.assertEqual(bf.frontend_workspaces({"FRONTEND_WORKSPACES": 5}, "D:/p"), [])
        self.assertEqual(bf.frontend_workspaces(None, "D:/p"), [])

    def test_relative_path_anchors_to_project(self):
        got = bf.frontend_workspaces({"FRONTEND_WORKSPACES": "front"}, "D:/project")
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].replace("\\", "/").endswith("/project/front"))

    def test_save_config_accepts_frontend_key_and_still_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(bf.cmd_save_config(
                SimpleNamespace(project=td, pairs=["FRONTEND_WORKSPACES=D:/develop/project/wukong"])), 0)
            self.assertEqual(bf.load_config(td)[1]["FRONTEND_WORKSPACES"],
                             "D:/develop/project/wukong")
            self.assertEqual(bf.cmd_save_config(
                SimpleNamespace(project=td, pairs=["BOGUS_KEY=1"])), 2)
            self.assertNotIn("BOGUS_KEY", bf.load_config(td)[1])


class TestResolutionGateInPrepare(unittest.TestCase):
    """prepare 默认跳过 Resolution 有值的 Bug；未知值失败关闭；--allow-resolved 可覆盖。"""

    def _args(self, td, **changes):
        base = dict(project=td, bug_id="101", base_branch=None, reuse=False, force=False,
                    current_workspace=td, allow_resolved=False)
        base.update(changes)
        return SimpleNamespace(**base)

    def test_default_gate_returns_9_for_set_and_10_for_unknown(self):
        for state, expected in (("set", 9), ("unknown", 10)):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as td:
                out = io.StringIO()
                with patch.object(bf, "fetch_bug_full", side_effect=bf.ResolutionStop(state)) as fetch, \
                     contextlib.redirect_stdout(out):
                    self.assertEqual(bf.cmd_prepare(self._args(td)), expected)
                self.assertIs(fetch.call_args.kwargs.get("skip_resolved"), True)
                self.assertIn("RESOLUTION_STOP=" + state, out.getvalue())

    def test_allow_resolved_bypasses_gate(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(bf, "fetch_bug_full", side_effect=RuntimeError("stop-here")) as fetch, \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    bf.cmd_prepare(self._args(td, allow_resolved=True))
            self.assertNotIn("skip_resolved", fetch.call_args.kwargs)


class TestChangeScopeGuard(unittest.TestCase):
    """改动范围：硬性声明行 + finish 拒绝跨工作空间提交。"""

    def test_scope_line_is_required_and_parsed(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / ".agents" / "zentao-bugfix" / "101"
            rd.mkdir(parents=True)
            bf.scaffold_analysis({}, [], [], make_info(rd), "http://z", "101")
            self.assertEqual(bf.analysis_change_scope(str(rd)), "unparsed")
            self.assertIn("**改动范围**:", (rd / "analysis.md").read_text(encoding="utf-8"))
            body = (rd / "analysis.md").read_text(encoding="utf-8")
            for line, expected in (("**改动范围**: 仅当前工作空间", "仅当前工作空间"),
                                   ("**改动范围**: 需要其他工作空间（本次不修改）", "需要其他工作空间")):
                with self.subTest(line=line):
                    (rd / "analysis.md").write_text(body.replace("（待填写）", line, 1),
                                                     encoding="utf-8")
                    self.assertEqual(bf.analysis_change_scope(str(rd)), expected)

    def test_other_sections_and_guidance_lines_are_not_misread(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "analysis.md").write_text(
                "## 2. 问题归属\n\n**结论**: 后端问题\n\n（待填写）\n\n"
                "## 3. 关键信息提取\n\n**改动范围**: 需要其他工作空间\n", encoding="utf-8")
            self.assertEqual(bf.analysis_change_scope(td), "unparsed")
        with tempfile.TemporaryDirectory() as td:
            Path(td, "analysis.md").write_text(
                "## 2. 问题归属（前端问题 / 后端问题 / 前后端 / 待确认）\n\n"
                "**结论**: 前后端\n\n**改动范围**: 仅当前工作空间\n", encoding="utf-8")
            self.assertEqual(bf.analysis_change_scope(td), "仅当前工作空间")
            self.assertEqual(bf.analysis_layer_attribution(td), "前后端")

    def _finish_args(self, td, **changes):
        base = dict(project=td, bug_id="101", files=["a.py"], check_command="true",
                    no_change=False)
        base.update(changes)
        return SimpleNamespace(**base)

    def test_finish_refuses_commit_when_scope_is_other_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "rd"
            rd.mkdir()
            (rd / "analysis.md").write_text(
                "## 2. 问题归属\n\n**结论**: 前端问题\n\n"
                "**改动范围**: 需要其他工作空间（本次不修改）\n", encoding="utf-8")
            record = {"report_dir": str(rd), "mode": "inplace"}
            with patch.object(bf._routes, "load_record", return_value=record), \
                 patch.object(bf._routes, "finish") as finish, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bf.cmd_finish(self._finish_args(td)), 8)
            finish.assert_not_called()

    def test_finish_proceeds_for_current_workspace_scope(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "rd"
            rd.mkdir()
            (rd / "analysis.md").write_text(
                "## 2. 问题归属\n\n**结论**: 后端问题\n\n"
                "**改动范围**: 仅当前工作空间\n", encoding="utf-8")
            record = {"report_dir": str(rd), "mode": "inplace"}
            with patch.object(bf._routes, "load_record", return_value=record), \
                 patch.object(bf._routes, "finish", return_value={"status": "committed"}) as finish, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bf.cmd_finish(self._finish_args(td)), 0)
            finish.assert_called_once()

    def test_finish_no_change_is_not_blocked_by_scope(self):
        with tempfile.TemporaryDirectory() as td:
            rd = Path(td) / "rd"
            rd.mkdir()
            (rd / "analysis.md").write_text(
                "## 2. 问题归属\n\n**改动范围**: 需要其他工作空间\n", encoding="utf-8")
            record = {"report_dir": str(rd), "mode": "inplace"}
            with patch.object(bf._routes, "load_record", return_value=record), \
                 patch.object(bf._routes, "finish", return_value={"status": "no_change"}) as finish, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bf.cmd_finish(self._finish_args(td, no_change=True, files=[])), 0)
            finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
