import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "crawler.py"
spec = importlib.util.spec_from_file_location("crawler", SCRIPT)
crawler = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = crawler
spec.loader.exec_module(crawler)


class CrawlerTests(unittest.TestCase):
    def test_reject_non_http_and_url_credentials(self):
        for value in ("file:///etc/passwd", "https://user:pass@example.com", "https://bad host/"):
            with self.subTest(value=value), self.assertRaises(crawler.InputError):
                crawler.url_checked(value)

    def test_same_origin_includes_scheme_host_and_port(self):
        self.assertEqual(crawler.origin("https://example.com/a"), crawler.origin("https://example.com/b"))
        self.assertNotEqual(crawler.origin("http://example.com"), crawler.origin("https://example.com"))
        self.assertNotEqual(crawler.origin("https://example.com"), crawler.origin("https://example.com:444"))

    def test_fields_and_duplicate_rejection(self):
        self.assertEqual(crawler.fields_checked(["title=h1::text"]), {"title": "h1::text"})
        with self.assertRaises(crawler.InputError):
            crawler.fields_checked(["a=h1", "a=h2"])
        with self.assertRaises(crawler.InputError):
            crawler.fields_checked(["_url=h1"])

    def test_serializers_handle_empty_and_formula_csv(self):
        self.assertIn("[]", crawler.serialize([], "json"))
        csv_text = crawler.serialize([{"name": "=1+1"}], "csv")
        self.assertIn("'=1+1", csv_text)
        xml = crawler.serialize([{"x&y": "<tag>"}], "xml")
        self.assertIn("&lt;tag&gt;", xml)
        self.assertIn("x&amp;y", xml)

    def test_output_refuses_overwrite_and_uses_workdir(self):
        class Args: pass
        with tempfile.TemporaryDirectory() as directory:
            args = Args(); args.workdir = Path(directory); args.output = None; args.format = "json"
            first = crawler.output_path(args)
            self.assertTrue(first.is_relative_to(Path(directory).resolve()))
            first.parent.mkdir(parents=True)
            first.write_text("sentinel", encoding="utf-8")
            args.output = str(first)
            with self.assertRaises(crawler.InputError):
                crawler.output_path(args)
            self.assertEqual(first.read_text(encoding="utf-8"), "sentinel")

    def test_cli_invalid_input_returns_json_and_code_2(self):
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with redirect_stdout(output):
            code = crawler.main(["fetch", "file:///etc/passwd"])
        self.assertEqual(code, 2)
        self.assertEqual(__import__("json").loads(output.getvalue())["status"], "error")


if __name__ == "__main__":
    unittest.main()
