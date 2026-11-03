#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_cases.py 的单元测试（纯标准库 unittest）。

覆盖三路径：正常文档通过、各类 error 命中、AC 覆盖统计正确。
运行：python tests/test_validate_cases.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate_cases.py"

GOOD_DOC = """# 演示需求 测试用例

## 四、分模块用例
### 拍照核验（TC-PV）
| 用例编号 | 关联AC | 用例类型 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|---|---|
| TC-PV-001 | AC7-1 | 正例 | P0 | 计划A已开启开关 | 1. 保存计划<br>2. 查看详情 | 1. 保存成功<br>2. 详情回显"开启" |
| TC-PV-002 | AC7-9 | 边界 | P1 | 历史计划无字段 | 1. 查看历史计划详情 | 1. 开关按"关闭"兼容展示 |
| TC-PV-003 | | 权限 | P0 | 无查看权限账号 | 1. 直接访问详情接口 | 1. 返回无权限错误 |
"""

BAD_DOC = """# 缺陷文档

| 用例编号 | 关联AC | 用例类型 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|---|---|
| TC-X-01 | AC1 | 正例 | P5 | 前置 | 步骤 | 功能正常 |
| TC-X-01 | | 反例 | P1 | | | |
| NOT-TC-1 | AC2 | 其他 | P2 | 前置 | 步骤 | 结果说明 |
"""

PRD_TEXT = """# PRD
验收标准：AC7-1 开关展示；AC7-9 默认兼容；AC7-10 五态展示；AC7-13 查看授权。
"""


def run_script(args: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    return proc.returncode, json.loads(proc.stdout)


class ValidateCasesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_good_doc_passes(self) -> None:
        doc = self._write("good.md", GOOD_DOC)
        code, result = run_script(["--cases", str(doc)])
        self.assertEqual(0, code, result)
        self.assertEqual("ok", result["status"])
        self.assertEqual(3, result["total"])
        self.assertIsNone(result["coverage"])

    def test_bad_doc_reports_errors(self) -> None:
        doc = self._write("bad.md", BAD_DOC)
        code, result = run_script(["--cases", str(doc)])
        self.assertEqual(1, code)
        self.assertEqual("fail", result["status"])
        codes = {i["code"] for i in result["issues"]}
        # 重复编号、格式不符、非法优先级、模糊断言、缺必填列均应命中
        self.assertIn("E001", codes)
        self.assertIn("E002", codes)
        self.assertIn("E004", codes)
        self.assertIn("W002", codes)
        self.assertIn("E003", codes)

    def test_ac_coverage(self) -> None:
        doc = self._write("good.md", GOOD_DOC)
        prd = self._write("prd.md", PRD_TEXT)
        code, result = run_script(["--cases", str(doc), "--prd", str(prd)])
        self.assertEqual(0, code)
        cov = result["coverage"]
        self.assertEqual(4, cov["acTotal"])
        self.assertEqual(2, cov["acCovered"])
        self.assertEqual(["AC7-10", "AC7-13"], cov["acMissing"])
        self.assertEqual(50.0, cov["rate"])

    def test_empty_table_is_error(self) -> None:
        doc = self._write("empty.md", "# 无用例\n\n没有表格。\n")
        code, result = run_script(["--cases", str(doc)])
        self.assertEqual(1, code)
        codes = {i["code"] for i in result["issues"]}
        self.assertIn("E006", codes)

    def test_missing_file_exit_2(self) -> None:
        code, result = run_script(["--cases", str(self.dir / "nope.md")])
        self.assertEqual(2, code)
        self.assertEqual("error", result["status"])


if __name__ == "__main__":
    unittest.main()
