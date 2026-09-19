#!/usr/bin/env python3
"""test_scripts.py — wedding-invitation 各脚本单元测试（unittest, 纯标准库）。

覆盖: generate_h5(正常/边界/错误)、synth_bgm(正常/边界)、ensure_ffmpeg(纯函数)、
record_page(纯函数/参数校验)、export_mp4(参数校验)。
运行: cd <skill_dir> && python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_h5  # noqa: E402
import synth_bgm  # noqa: E402
import ensure_ffmpeg  # noqa: E402
import record_page  # noqa: E402


def run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, timeout=120)


class TestGenerateH5(unittest.TestCase):
    BASE = ["-u", str(SCRIPTS / "generate_h5.py"), "--groom", "测郎", "--bride", "测娘",
            "--date", "2026-10-03", "--venue", "测试 · 大酒店"]

    def test_normal(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "a.html"
            r = run_cli(self.BASE + ["--out", str(out)])
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["status"], "ok")
            html = out.read_text(encoding="utf-8")
            self.assertNotIn("{{", html)                       # 无占位符残留
            self.assertIn("测郎", html)
            self.assertIn("星期六", html)                        # 2026-10-03
            self.assertIn("2026-10-03T12:08", html)             # 默认时间

    def test_weekday_boundary(self):
        f = generate_h5.build_fields({"groom": "a", "bride": "b", "date": "2025-01-01", "time": "12:08", "venue": "v"})
        self.assertEqual(f["WEEKDAY"], "星期三")                # 2025-01-01
        f2 = generate_h5.build_fields({"groom": "a", "bride": "b", "date": "2024-02-29", "time": "12:08", "venue": "v"})
        self.assertEqual(f2["WEEKDAY"], "星期四")                # 闰日边界

    def test_bad_date(self):
        r = run_cli(self.BASE[:-2] + ["--date", "2026/1/1", "--venue", "v"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("日期格式", json.loads(r.stdout)["error"]["message"])

    def test_missing_required(self):
        r = run_cli(["-u", str(SCRIPTS / "generate_h5.py"), "--groom", "a"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("缺少必填", json.loads(r.stdout)["error"]["message"])

    def test_bad_time(self):
        r = run_cli(self.BASE[:-1] + ["--time", "25:00"])
        self.assertEqual(r.returncode, 2)

    def test_dialog_json_valid(self):
        f = generate_h5.build_fields({"groom": "g", "bride": "b", "date": "2026-10-03", "time": "12:08", "venue": "v"})
        lines = json.loads(f["DIALOG_JSON"])
        self.assertIsInstance(lines, list)
        self.assertTrue(any("g" in x for x in lines))


class TestSynthBgm(unittest.TestCase):
    def test_cli_normal(self):
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "b.wav"
            r = run_cli(["-u", str(SCRIPTS / "synth_bgm.py"), "--music-start", "0.5",
                         "--blips", "0.5,2", "--duration", "3", "--out", str(wav)])
            self.assertEqual(r.returncode, 0, r.stderr)
            with wave.open(str(wav)) as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getframerate(), 44100)
                self.assertAlmostEqual(w.getnframes() / 44100, 3, delta=0.1)

    def test_timeline_fallback(self):
        samples, peak = synth_bgm.render(2.0, 0.3, [0.3], 1.5, 108, 0.9)
        self.assertGreater(len(samples), 80000)
        self.assertGreater(peak, 0.0)

    def test_missing_timeline(self):
        r = run_cli(["-u", str(SCRIPTS / "synth_bgm.py"), "--timeline", "/nonexistent.json"])
        self.assertEqual(r.returncode, 2)


class TestEnsureFfmpeg(unittest.TestCase):
    def test_parse_wheel_linux(self):
        html = ('<a href="../../packages/aa/bb/imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl#sha256=x">'
                '<a href="../../packages/cc/dd/imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl#sha256=y">')
        urls = ensure_ffmpeg.parse_wheel_urls(html)
        self.assertEqual(len(urls), 1)
        self.assertIn("manylinux", urls[0])

    def test_run_ok_missing(self):
        self.assertFalse(ensure_ffmpeg.run_ok(Path("/nonexistent/ffmpeg")))

    def test_platform_choice(self):
        self.assertIsInstance(ensure_ffmpeg.want_windows_binary(), bool)


class TestRecordPage(unittest.TestCase):
    def test_to_node_path(self):
        self.assertIn("\\", record_page.to_node_path(Path("/mnt/d/x/y.html"), True))
        self.assertEqual(record_page.to_node_path(Path("/tmp/a b.html"), False), "/tmp/a b.html")

    def test_mjs_render_modes(self):
        js = record_page.MJS_TEMPLATE
        js2 = js.replace("{{NAV_MODE}}", "selector").replace("{{STAY}}", "[1000,1000]") \
                .replace("{{HTML}}", '"x"').replace("{{BROWSER}}", '"y"') \
                .replace("{{VIEWPORT}}", "[540,960]").replace("{{START_SEL}}", '"none"') \
                .replace("{{NAV_SEL}}", '".next"')
        self.assertIn("NAV_MODE === 'selector'", js2)
        self.assertIn("NAV_MODE === 'go'", js2)

    def test_bad_stay(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.html"
            p.write_text("<html></html>")
            r = run_cli(["-u", str(SCRIPTS / "record_page.py"), "--html", str(p),
                         "--workdir", td, "--stay", "abc"])
            self.assertEqual(r.returncode, 2)

    def test_html_missing(self):
        r = run_cli(["-u", str(SCRIPTS / "record_page.py"), "--html", "/nope.html",
                     "--workdir", "/tmp"])
        self.assertEqual(r.returncode, 2)


class TestExportMp4(unittest.TestCase):
    def test_html_missing(self):
        r = run_cli(["-u", str(SCRIPTS / "export_mp4.py"), "--html", "/nope.html"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("不存在", json.loads(r.stdout)["error"]["message"])

    def test_bad_size(self):
        p = None
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.html"
            p.write_text("<html></html>")
            r = run_cli(["-u", str(SCRIPTS / "export_mp4.py"), "--html", str(p),
                         "--out-size", "1080x"])
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
