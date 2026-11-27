#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.40"]
# ///
"""screenshot.py — product-design 原型三视口截图（响应式自查用，可选增强）。

用途: 用本机 Chrome/Edge（免装浏览器内核）对 HTML 原型按 375/768/1440 视口截图，
      输出 PNG 供 AI/用户核对响应式表现。
依赖: PEP 723 声明 playwright，`uv run` 自动隔离安装；浏览器按 channel 探测
      chrome → msedge → chromium（复用本机已装浏览器，无需 playwright install）。
用法:
  uv run screenshot.py --html pages/index.html --out shots
  uv run screenshot.py --html a.html --viewports 390,1440 --no-full-page
参数:
  --html       目标 HTML 文件（必需）
  --out        截图输出目录（默认与 HTML 同目录的 shots/）
  --viewports  逗号分隔宽度列表（默认 375,768,1440；高度固定 900）
  --no-full-page  只截首屏（默认整页截图）
  --wait       截图前稳定等待毫秒数（默认 900，等字体/动效就绪）
  --json       结果另存到指定文件路径
退出码: 0=全部成功 / 1=截图失败 / 2=参数错误
输出: stdout JSON {status, engine, shots:[{viewport,path}]}；日志到 stderr。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_VIEWPORTS = "375,768,1440"
VIEWPORT_HEIGHT = 900
CHANNELS = ["chrome", "msedge", "chromium"]


def main() -> int:
    ap = argparse.ArgumentParser(description="原型 HTML 三视口截图")
    ap.add_argument("--html", required=True, help="目标 HTML 文件")
    ap.add_argument("--out", default=None, help="输出目录（默认 <html目录>/shots）")
    ap.add_argument("--viewports", default=DEFAULT_VIEWPORTS, help=f"逗号分隔宽度（默认 {DEFAULT_VIEWPORTS}）")
    ap.add_argument("--no-full-page", action="store_true", help="只截首屏")
    ap.add_argument("--wait", type=int, default=900, help="截图前等待毫秒")
    ap.add_argument("--json", default=None, help="结果 JSON 另存路径")
    args = ap.parse_args()

    html = Path(args.html)
    if not html.is_file():
        print(json.dumps({"status": "error", "error": {
            "message": f"HTML 文件不存在：{html}",
            "hint": "检查路径；原型默认在 .agents/out/YYYYMMDD/product-design/<项目名>/pages/"}},
            ensure_ascii=False), file=sys.stderr)
        return 2
    try:
        widths = [int(w.strip()) for w in args.viewports.split(",") if w.strip()]
        if not widths or any(w < 200 or w > 4000 for w in widths):
            raise ValueError
    except ValueError:
        print(json.dumps({"status": "error", "error": {
            "message": f"--viewports 无效：{args.viewports}",
            "hint": "格式如 375,768,1440，每个宽度 200-4000"}}, ensure_ascii=False), file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else html.parent / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(json.dumps({"status": "error", "error": {
            "message": "playwright 未安装（直接 python 运行时缺依赖）",
            "hint": "用 `uv run screenshot.py ...` 触发 PEP 723 自动安装；或 pip install playwright"}},
            ensure_ascii=False), file=sys.stderr)
        return 1

    shots: list[dict] = []
    with sync_playwright() as p:
        engine = None
        browser = None
        last_err: Exception | None = None
        for channel in CHANNELS:
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                engine = channel
                break
            except Exception as exc:  # 逐个降级
                last_err = exc
        if browser is None:
            print(json.dumps({"status": "error", "error": {
                "message": f"无可用的 Chromium 内核浏览器（尝试过 {', '.join(CHANNELS)}）",
                "hint": f"本机需安装 Chrome 或 Edge；最后错误：{last_err}",
                "fallback": "跳过截图不阻塞交付，提醒用户自行在浏览器打开原型核对响应式"}},
                ensure_ascii=False), file=sys.stderr)
            return 1
        try:
            for w in widths:
                ctx = browser.new_context(
                    viewport={"width": w, "height": VIEWPORT_HEIGHT},
                    device_scale_factor=2, is_mobile=(w < 768),
                )
                page = ctx.new_page()
                page.goto(html.resolve().as_uri(), wait_until="load")
                page.wait_for_timeout(args.wait)
                dest = out_dir / f"{html.stem}-{w}.png"
                page.screenshot(path=str(dest), full_page=not args.no_full_page)
                shots.append({"viewport": w, "path": str(Path.absolute(dest))})
                ctx.close()
        finally:
            browser.close()

    result = {"status": "ok", "engine": engine, "shots": shots}
    out = json.dumps(result, ensure_ascii=False, indent=2)
    print(out)
    if args.json:
        Path(args.json).write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "error", "error": {
            "message": f"截图失败：{exc}",
            "hint": "页面 JS 报错或路径含特殊字符时可能失败；跳过截图不阻塞交付"}},
            ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
