#!/usr/bin/env python3
"""record_page.py — 用 Playwright(无头浏览器)自动翻页录制本地 HTML 页面为 webm。

用途: HTML→MP4 通用子流程的录制环节。自动探测 node/npm/浏览器，按需安装
      playwright-core，生成并运行 record.mjs：等待各页 → 自动翻页
      (window.go(n) 或点击选择器) → 输出 videos/record.webm + timeline.json
      (记录 BGM 起播点与每次翻页时刻, 供 synth_bgm.py 精确对齐)。
用法: python3 record_page.py --html 页面.html --workdir 导出工作目录 \
        [--stay "1500,5000,..."] [--nav-mode go|selector|none] \
        [--nav-selector ".next"] [--start-selector "#startBtn|none"] [--viewport 540x960]
依赖: Python 3.9+ 纯标准库；运行需 node+npm 与 Chrome/Edge（自动探测）。
输出: JSON 到 stdout(status/webm/timeline)；日志到 stderr。
退出码: 0=成功 1=录制/依赖失败 2=参数错误。
路径坑(固化): WSL 调 win-node.exe 时 /mnt/... 参数会被错误转换,
      因此所有路径写进生成的 .mjs 文件内, 运行时不传路径参数。
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MJS_TEMPLATE = r'''
import { chromium } from 'playwright-core';
import { pathToFileURL } from 'url';
import fs from 'fs';

const HTML = {{HTML}};
const BROWSER = {{BROWSER}};
const VIEWPORT = {{VIEWPORT}};
const STAY = {{STAY}};
const START_SEL = {{START_SEL}};   // 'none' 或 css 选择器
const NAV_MODE = '{{NAV_MODE}}';   // go | selector | none
const NAV_SEL = {{NAV_SEL}};

const browser = await chromium.launch({ executablePath: BROWSER, headless: true });
const context = await browser.newContext({
  viewport: { width: VIEWPORT[0], height: VIEWPORT[1] },
  recordVideo: { dir: 'videos', size: { width: VIEWPORT[0], height: VIEWPORT[1] } }
});
const page = await context.newPage();
const T0 = Date.now();

await page.addInitScript(() => {
  const s = document.createElement('style');
  s.textContent = '@media(min-width:520px){body{display:block!important}#app{height:100%!important;max-height:none!important;border-radius:0!important;box-shadow:none!important;max-width:100%!important}}';
  document.addEventListener('DOMContentLoaded', () => document.head.appendChild(s));
});

await page.goto(pathToFileURL(HTML).href);
console.error('loaded');

let clickAt = 0;
await page.waitForTimeout(STAY[0]);
if (START_SEL !== 'none') {
  try { await page.click(START_SEL, { timeout: 3000 }); } catch (e) { console.error('start click skipped'); }
}
clickAt = (Date.now() - T0) / 1000;
const blips = [clickAt];

for (let n = 1; n < STAY.length; n++) {
  await page.waitForTimeout(STAY[n]);
  blips.push((Date.now() - T0) / 1000);
  if (NAV_MODE === 'go') {
    await page.evaluate((i) => { if (window.go) window.go(i); }, n);
  } else if (NAV_MODE === 'selector') {
    await page.click(NAV_SEL, { timeout: 5000 });
  }
}
await page.waitForTimeout(Math.max(...STAY.slice(1), 1000));
const endAt = (Date.now() - T0) / 1000 + 0.3;

fs.writeFileSync('timeline.json', JSON.stringify({ music: clickAt, blips, end: endAt }));
const video = page.video();
await context.close();
await video.saveAs('videos/record.webm');
await browser.close();
console.error('SAVED videos/record.webm');
'''


def say(*a):
    print(*a, file=sys.stderr)


def detect_node() -> tuple[Path | None, bool]:
    """返回 (node 可执行文件, 是否 win 版)。"""
    n = shutil.which("node")
    if n:
        return Path(n), n.lower().endswith(".exe")
    pats = ["/mnt/*/develop/nvm/v*/node.exe", "/mnt/c/Program Files/nodejs/node.exe",
            "/mnt/c/Program Files (x86)/nodejs/node.exe", str(Path.home() / "AppData/Roaming/nvm/v*/node.exe")]
    for pat in pats:
        hits = sorted(glob.glob(pat))
        if hits:
            return Path(hits[-1]), True
    return None, False


def detect_browser() -> Path | None:
    cands = ["/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
             "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
             "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
             "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe"]
    for c in cands:
        if Path(c).is_file():
            return Path(c)
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        w = shutil.which(name)
        if w:
            return Path(w)
    return None


def to_node_path(p: Path, win: bool) -> str:
    s = str(p.resolve())
    if win:
        return s.replace("/mnt/", "").replace("/", ":/", 1).replace("/", "\\") \
            if s.startswith("/mnt/") else s.replace("/", "\\")
    return s


def ensure_playwright(node: Path, win: bool, workdir: Path) -> None:
    if (workdir / "node_modules" / "playwright-core" / "package.json").is_file():
        return
    npm_cli_candidates = [node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"]
    npm_cli = next((c for c in npm_cli_candidates if c.is_file()), None)
    if npm_cli is None:
        raise RuntimeError("未找到 npm-cli.js，请确认 node 安装完整")
    say("[info] installing playwright-core ...")
    cmd = [str(node), to_node_path(npm_cli, win), "install", "--prefix",
           str(workdir.resolve()), "playwright-core", "--no-fund", "--no-audit"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=900, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        pass  # npm 偶发挂起但已装完, 以下面存在性为准
    if not (workdir / "node_modules" / "playwright-core" / "package.json").is_file():
        raise RuntimeError("playwright-core 安装失败（网络受限？可设 npm 镜像后重试）")


def main() -> None:
    ap = argparse.ArgumentParser(description="Playwright 录制 HTML 为 webm")
    ap.add_argument("--html", required=True, help="本地 HTML 文件路径")
    ap.add_argument("--workdir", required=True, help="导出工作目录(产 videos/ 与 timeline.json)")
    ap.add_argument("--stay", default="1500,5000,6000,9000,6500,5500,4500",
                    help="逗号分隔的每页停留毫秒, 长度即页数")
    ap.add_argument("--nav-mode", choices=["go", "selector", "none"], default="go",
                    help="翻页方式: window.go(n) / 点击选择器 / 不翻页")
    ap.add_argument("--nav-selector", default=".next", help="nav-mode=selector 时的选择器")
    ap.add_argument("--start-selector", default="#startBtn",
                    help="首页入口按钮选择器, none 表示无入口直接开始")
    ap.add_argument("--viewport", default="540x960", help="录制视口, 如 540x960")
    a = ap.parse_args()

    html = Path(a.html)
    if not html.is_file():
        json.dump({"status": "error", "error": {"message": f"HTML 不存在: {a.html}"}},
                  sys.stdout, ensure_ascii=False)
        sys.exit(2)
    try:
        stay = [int(x) for x in a.stay.split(",") if x.strip()]
        assert len(stay) >= 2 and all(x > 0 for x in stay)
    except Exception:
        json.dump({"status": "error", "error": {
            "message": f"--stay 格式错误: {a.stay!r}",
            "action": "应为 ≥2 个正整数毫秒, 如 1500,5000,6000"}}, sys.stdout, ensure_ascii=False)
        sys.exit(2)
    try:
        w, h = (int(x) for x in a.viewport.lower().split("x"))
        assert w > 0 and h > 0
    except Exception:
        json.dump({"status": "error", "error": {"message": f"--viewport 格式错误: {a.viewport!r}"}},
                  sys.stdout, ensure_ascii=False)
        sys.exit(2)

    node, win = detect_node()
    if node is None:
        json.dump({"status": "error", "error": {
            "message": "未找到 node", "action": "安装 Node.js 或置于 PATH/nvm 常见路径"}},
            sys.stdout, ensure_ascii=False)
        sys.exit(1)
    browser = detect_browser()
    if browser is None:
        json.dump({"status": "error", "error": {
            "message": "未找到 Chrome/Edge", "action": "安装 Chrome 或 Edge"}},
            sys.stdout, ensure_ascii=False)
        sys.exit(1)

    workdir = Path(a.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        ensure_playwright(node, win, workdir)
    except RuntimeError as e:
        json.dump({"status": "error", "error": {"message": str(e)}}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    mjs = MJS_TEMPLATE.replace("{{HTML}}", json.dumps(to_node_path(html, win))) \
        .replace("{{BROWSER}}", json.dumps(to_node_path(browser, win))) \
        .replace("{{VIEWPORT}}", json.dumps([w, h])) \
        .replace("{{STAY}}", json.dumps(stay)) \
        .replace("{{START_SEL}}", json.dumps(a.start_selector)) \
        .replace("{{NAV_MODE}}", a.nav_mode) \
        .replace("{{NAV_SEL}}", json.dumps(a.nav_selector))
    script = workdir / "record.mjs"
    script.write_text(mjs, encoding="utf-8")

    t0 = time.time()
    r = subprocess.run([str(node), "record.mjs"], cwd=str(workdir),
                       capture_output=True, timeout=600)
    webm = workdir / "videos" / "record.webm"
    tl = workdir / "timeline.json"
    if r.returncode != 0 or not webm.is_file() or not tl.is_file():
        tail = (r.stderr or b"")[-800:].decode(errors="replace")
        json.dump({"status": "error", "error": {
            "message": "录制失败", "reason": tail or f"exit={r.returncode}",
            "action": "查看 stderr 日志；确认页面可加载、翻页选择器正确"}},
            sys.stdout, ensure_ascii=False)
        sys.exit(1)
    json.dump({"status": "ok", "webm": str(webm), "timeline": str(tl),
               "node": str(node), "browser": str(browser),
               "record_seconds": round(time.time() - t0, 1)},
              sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
