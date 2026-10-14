"""Verify paired reports, offline rendering, escaping and content freshness."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "report_html.py"
spec = importlib.util.spec_from_file_location("bug_report_html", SCRIPT)
rh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rh)


class ReportHtmlTests(unittest.TestCase):
    def test_three_reports_same_directory_and_current_after_regeneration(self):
        with tempfile.TemporaryDirectory(prefix="bug报告 ") as td:
            directory = Path(td)
            for name in rh.REPORT_NAMES:
                (directory / name).write_text("# 中文报告\n\n## 根因\n\n证据：`src/app.py:10`\n", encoding="utf-8")
            result = rh.render_reports(directory, require_complete=True)
            self.assertEqual(set(result), {"analysis", "solution", "fix-report"})
            self.assertTrue(all(rh.current_reports(directory).values()))
            path = directory / "fix-report.md"
            with path.open("a", encoding="utf-8") as f:
                f.write("\n## 最终提交结果\n\nCommit：`abc123`\n")
            self.assertFalse(rh.current_reports(directory)["fix-report"])
            rh.render_reports(directory, require_complete=True)
            self.assertIn("abc123", (directory / "fix-report.html").read_text(encoding="utf-8"))
            self.assertTrue(all(rh.current_reports(directory).values()))

    def test_tables_evidence_code_images_and_links_offline(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "analysis.md"
            source.write_text('''# Bug #123 分析

## 代码证据

| 文件 | 说明 |
|---|---|
| `src/app.py:10` | 缺少空值校验 |

> 禅道原文：保存失败

```python
if x < 0:
    print("<script>不能执行</script>")
```

![复现截图](screenshot.png)

[修复报告](fix-report.md)

3. 检查请求
4. 检查返回值
''', encoding="utf-8")
            output = Path(rh.generate(source)).read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN">', output)
        self.assertIn('<table>', output)
        self.assertIn('<code>src/app.py:10</code>', output)
        self.assertIn('<blockquote>', output)
        self.assertIn('src="screenshot.png"', output)
        self.assertIn('href="fix-report.md"', output)
        self.assertIn('<ol start="3">', output)
        self.assertIn('href="#section-2"', output)
        self.assertNotIn('<script>', output)
        self.assertNotIn('<script src=', output)
        self.assertIn('if x &lt; 0:', output)

    def test_external_html_and_unsafe_urls_never_execute(self):
        body, _ = rh.render_markdown('# <script>alert(1)</script>\n\n[攻击](javascript:alert)\n\n<img src=x onerror=alert(1)>')
        self.assertNotIn('<script>', body)
        self.assertNotIn('<img src=x', body)
        self.assertIn('&lt;script&gt;', body)
        self.assertIn('href="#"', body)
        self.assertEqual(rh.safe_url('java\nscript:alert(1)'), '#')

    def test_incomplete_reports_fail_before_replacing_existing_html(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            (directory / "analysis.md").write_text("# 完整报告", encoding="utf-8")
            (directory / "solution.md").write_text("（待填写）", encoding="utf-8")
            (directory / "analysis.html").write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未完整"):
                rh.render_reports(directory, names=("analysis.md", "solution.md"), require_complete=True)
            self.assertEqual((directory / "analysis.html").read_text(), "old")
            with self.assertRaisesRegex(ValueError, "缺失"):
                rh.render_reports(directory, names=("fix-report.md",), require_complete=True)


if __name__ == "__main__":
    unittest.main()
