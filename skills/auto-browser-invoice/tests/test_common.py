#!/usr/bin/env python3
"""test_common.py — _common.py 纯标准库部分的单测（不依赖浏览器/网络）。

运行：python -m unittest discover -s tests -v   （在 skill 目录下）
或：  uv run tests/test_common.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _common as c  # noqa: E402


class TestParseEnv(unittest.TestCase):
    def test_basic_and_comments(self):
        text = "# 注释\n\nA=1\n  B = spaced = ok \n"
        env = c.parse_env(text)
        self.assertEqual(env, {"A": "1", "B": "spaced = ok"})

    def test_quoted_and_empty(self):
        text = 'T="hello world"\nE=\nURL=https://etax.hubei.chinatax.gov.cn:8443/\n'
        env = c.parse_env(text)
        self.assertEqual(env["T"], "hello world")
        self.assertEqual(env["E"], "")
        self.assertIn(":8443/", env["URL"])

    def test_invalid_lines_ignored(self):
        env = c.parse_env("没有等号\n=开头\n#C=注释\nOK=1")
        self.assertEqual(env, {"OK": "1"})


class TestLoadEnv(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(c.load_env(d), {})

    def test_reads_utf8_with_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".agents" / ".env"
            p.parent.mkdir()
            p.write_text("ETAX_URL=https://etax.hubei.chinatax.gov.cn:8443/\n", encoding="utf-8-sig")
            env = c.load_env(d)
            self.assertEqual(env["ETAX_URL"], "https://etax.hubei.chinatax.gov.cn:8443/")


class TestFindBrowser(unittest.TestCase):
    def test_returns_none_when_missing(self):
        old = list(c.BROWSER_CANDIDATES)
        c.BROWSER_CANDIDATES = [r"D:\definitely\not\exist\chrome.exe", ""]
        try:
            self.assertIsNone(c.find_browser())
        finally:
            c.BROWSER_CANDIDATES = old

    def test_returns_first_existing(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake = f.name
        try:
            old = list(c.BROWSER_CANDIDATES)
            c.BROWSER_CANDIDATES = [r"D:\definitely\not\exist\chrome.exe", fake]
            try:
                self.assertEqual(c.find_browser(), fake)
            finally:
                c.BROWSER_CANDIDATES = old
        finally:
            os.unlink(fake)


class TestCdpHelpers(unittest.TestCase):
    def test_cdp_url(self):
        self.assertEqual(c.cdp_url(9222), "http://127.0.0.1:9222")

    def test_cdp_alive_returns_none_on_unused_port(self):
        # 用一个大概率未监听的端口；不可达时必须返回 None 而不是抛异常
        self.assertIsNone(c.cdp_alive(59999, timeout=0.5))


if __name__ == "__main__":
    unittest.main(verbosity=2)
