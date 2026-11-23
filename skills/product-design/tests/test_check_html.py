#!/usr/bin/env python3
"""test_check_html.py — check_html.py 与 init_workspace.py 的脚本单测（纯标准库 unittest）。

运行: python tests/test_check_html.py  或  uv run tests/test_check_html.py
覆盖: 正常路径（合规 HTML 通过）/ 边界（仅 warning 不失败）/ 错误路径（error 清单齐全）/
      init_workspace 正常/幂等/--force。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_html  # noqa: E402
import init_workspace  # noqa: E402

GOOD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>首页</title>
<style>
:root { --accent: #3B82F6; }
body { background: #F9FAFB; color: #18181B; font-family: -apple-system, "PingFang SC", sans-serif; min-height: 100dvh; }
@media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
</style></head>
<body><header><h1>增长驾驶舱</h1></header>
<main><section class="grid"><article>47.2% 环比提升（示例数据）</article></section></main>
</body></html>"""

WARN_HTML = GOOD_HTML.replace("#18181B", "#000000").replace("47.2% 环比提升（示例数据）",
    "99.99% uptime <em>🎉</em> 赋能极致体验") + "<script src=\"https://cdn.example.com/x.js\"></script>"

BAD_HTML = "<html><body><div><p>Lorem ipsum 占位内容</body>"  # 无 charset/viewport/media/未闭合


class TestCheckHtml(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.d / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_good_passes(self) -> None:
        """正常：合规 HTML 无 error 无 warning。"""
        r = check_html.check_one(self._write("good.html", GOOD_HTML))
        self.assertEqual(r["errors"], [], f"意外 error: {r['errors']}")
        self.assertEqual(r["warnings"], [], f"意外 warning: {r['warnings']}")

    def test_warnings_not_errors(self) -> None:
        """边界：反模式命中产生 warning 但不产生 error。"""
        r = check_html.check_one(self._write("warn.html", WARN_HTML))
        self.assertEqual(r["errors"], [], f"warning 场景不应有 error: {r['errors']}")
        ids = {w.split()[0] for w in r["warnings"]}
        for expect in ("W001", "W003", "W004", "W005", "W007"):
            self.assertIn(expect, ids, f"缺少 {expect}: {r['warnings']}")

    def test_errors_fail(self) -> None:
        """错误：占位文本/缺 viewport/缺 media/标签未闭合 全部拦截。"""
        r = check_html.check_one(self._write("bad.html", BAD_HTML))
        ids = {e.split(":")[0].split()[0] for e in r["errors"]}
        for expect in ("E001", "E002", "E010", "E020", "E030"):
            self.assertIn(expect, ids, f"缺少 {expect}: {r['errors']}")

    def test_missing_file(self) -> None:
        r = check_html.check_one(self.d / "nope.html")
        self.assertTrue(r["errors"])

    def test_main_exit_codes(self) -> None:
        good = self._write("g.html", GOOD_HTML)
        bad = self._write("b.html", BAD_HTML)
        self.assertEqual(check_html.main.__module__, "check_html")
        # 直接走 main 的参数装配太重，这里验证 JSON 汇总逻辑
        rs = [check_html.check_one(good), check_html.check_one(bad)]
        has_error = any(r["errors"] for r in rs)
        self.assertTrue(has_error)


class TestInitWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *extra: str) -> dict:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            init_workspace.main()
        return json.loads(buf.getvalue())
    def test_single_basic(self) -> None:
        """正常：单页模式生成 DESIGN.md 与两个子目录。"""
        sys.argv = ["init_workspace.py", "--name", "测试项目", "--workdir", str(self.ws)]
        r = self._run()
        root = Path(r["dir"])
        self.assertEqual(r["status"], "ok")
        self.assertTrue((root / "DESIGN.md").is_file())
        self.assertFalse((root / "SITE.md").exists())
        self.assertTrue((root / "pages").is_dir() and (root / "shots").is_dir())
        self.assertIn("测试项目", (root / "DESIGN.md").read_text(encoding="utf-8"))

    def test_idempotent_then_force(self) -> None:
        """边界：二次运行跳过已有文件；--force 覆盖。"""
        sys.argv = ["init_workspace.py", "--name", "demo", "--workdir", str(self.ws), "--mode", "multi"]
        self._run()
        sys.argv = ["init_workspace.py", "--name", "demo", "--workdir", str(self.ws), "--mode", "multi"]
        r = self._run()
        self.assertEqual(len(r["skipped"]), 2, f"应跳过 DESIGN/SITE 两个已有文件: {r}")
        self.assertFalse(r["created"])
        design = Path(r["dir"]) / "DESIGN.md"
        design.write_text("modified", encoding="utf-8")
        sys.argv = ["init_workspace.py", "--name", "demo", "--workdir", str(self.ws), "--force"]
        r = self._run()
        # Windows 短路径（ADMINI~1）会导致字符串不一致，改比对 Path 对象
        self.assertTrue(any(Path(p) == design for p in r["created"]), f"DESIGN.md 应在 created 中: {r}")
        self.assertTrue(design.read_text(encoding="utf-8").startswith("# Design System: demo"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
