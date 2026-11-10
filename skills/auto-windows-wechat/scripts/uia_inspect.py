#!/usr/bin/env python3
"""uia_inspect.py — 微信窗口 UIA 树侦察器（只读不点击，零第三方依赖）。

为 GUI 自动化开发做结构侦察：聊天窗口里视频号卡片的控件形态、视频号播放器
（WeChatAppEx / Chromium）窗口结构、搜索下拉结构等。侦察结论请沉淀进
references/troubleshooting.md。UIA 失明（元素数=1）时本工具会轮询等待，
超时输出 NOT_READY——按排障手册重启微信客户端后重试。

用法:
    uv run scripts/uia_inspect.py --list            # 列出可见顶层窗口（找目标）
    uv run scripts/uia_inspect.py                   # 默认 dump 微信主窗口
    uv run scripts/uia_inspect.py --title 视频号    # 按标题子串选窗口
    uv run scripts/uia_inspect.py --class Chrome_WidgetWin_0
    uv run scripts/uia_inspect.py --hwnd 198296 --depth 16 --budget 8000

stdout：每行一个控件的紧凑 JSON（d=深度 t=类型 n=名称 c=类名 id=AutomationId
r=矩形 x,y w×h），末行 {"output": {...}} 汇总；诊断 stderr（[uia_probe] 前缀）。
仅 Windows；Python 3.10+。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
from ctypes import wintypes

LOG = "[uia_probe]"

# 管道输出统一 UTF-8：Windows 下 Python 写管道默认用 ANSI 代码页（cp936），
# 中文会变乱码（同发送脚本错误表「中文变 ?????」的根因）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

MAIN_WINDOW_CLASSES = {"WeChatMainWndForPC", "Qt51514QWindowIcon", "mmui::MainWindow"}

_PS_TEMPLATE = r'''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$win = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]::new(__HWND__))
if (-not $win) { Write-Output 'NO_WINDOW'; exit 1 }
# 就绪轮询：Qt/Chromium 的 UIA 树可能失明（元素极少或 Name 全空），同发送脚本经验。
$deadline = (Get-Date).AddSeconds(10)
while ($true) {
    $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $named = 0
    foreach ($a in $all) { if ($a.Current.Name) { $named++; if ($named -ge 3) { break } } }
    if ($all.Count -gt 10 -and $named -ge 3) { break }
    if ((Get-Date) -ge $deadline) { Write-Output 'NOT_READY'; exit 1 }
    Start-Sleep -Milliseconds 500
}
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$budget = __BUDGET__
$maxDepth = __DEPTH__
$stack = New-Object System.Collections.Stack
$stack.Push(@($win, 0))
function Esc([string]$s) {
    if (-not $s) { return '' }
    $s = $s -replace '\\', '\\\\' -replace '"', '\"'
    $s = $s -replace "`t", ' ' -replace "`r", ' ' -replace "`n", ' '
    if ($s.Length -gt 80) { $s = $s.Substring(0, 80) }
    return $s
}
$count = 0
while ($stack.Count -gt 0 -and $count -lt $budget) {
    $item = $stack.Pop()
    $e = $item[0]; $d = $item[1]
    if ($d -gt $maxDepth) { continue }
    $c = $e.Current
    $t = ''
    try { $t = $c.ControlType.ProgrammaticName -replace '^ControlType\.', '' } catch {}
    $r = ''
    try {
        $rc = $c.BoundingRectangle
        if (-not $rc.IsEmpty) { $r = ('{0:F0},{1:F0} {2:F0}x{3:F0}' -f $rc.X, $rc.Y, $rc.Width, $rc.Height) }
    } catch {}
    Write-Output ('{"d":' + $d + ',"t":"' + (Esc $t) + '","n":"' + (Esc $c.Name) +
        '","c":"' + (Esc $c.ClassName) + '","id":"' + (Esc $c.AutomationId) +
        '","r":"' + $r + '"}')
    $count++
    $kids = @()
    $child = $walker.GetFirstChild($e)
    while ($child) { $kids += @($child); $child = $walker.GetNextSibling($child) }
    for ($i = $kids.Length - 1; $i -ge 0; $i--) { $stack.Push(@($kids[$i], ($d + 1))) }
}
Write-Output ('DONE ' + $count)
'''


def _list_windows() -> list[dict]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    out: list[dict] = []

    def on_window(h, _l):
        if not user32.IsWindowVisible(h):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(h, buf, 512)
        cls = buf.value
        user32.GetWindowTextW(h, buf, 512)
        title = buf.value
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        w, hgt = r.right - r.left, r.bottom - r.top
        if (cls or title) and w >= 60 and hgt >= 60:
            out.append({"hwnd": int(h), "class": cls, "title": title,
                        "rect": [r.left, r.top, w, hgt]})
        return True

    user32.EnumWindows(proto(on_window), 0)
    return out


def pick_window(windows: list[dict], args) -> dict | None:
    if args.hwnd:
        return next((w for w in windows if w["hwnd"] == args.hwnd), None)
    if args.class_name:
        return next((w for w in windows if w["class"] == args.class_name), None)
    if args.title:
        t = args.title.lower()
        return next((w for w in windows if t in w["title"].lower()), None)
    return next((w for w in windows if w["class"] in MAIN_WINDOW_CLASSES), None)


def main() -> int:
    ap = argparse.ArgumentParser(description="微信窗口 UIA 树侦察器（只读）")
    ap.add_argument("--list", action="store_true", help="列出可见顶层窗口")
    ap.add_argument("--title", help="按窗口标题子串选窗口")
    ap.add_argument("--class-name", help="按窗口类名选窗口")
    ap.add_argument("--hwnd", type=int, help="直接指定窗口句柄")
    ap.add_argument("--depth", type=int, default=14, help="最大遍历深度（默认 14）")
    ap.add_argument("--budget", type=int, default=5000, help="最多输出的控件数（默认 5000）")
    args = ap.parse_args()

    windows = _list_windows()
    if args.list:
        for w in windows[:40]:
            print(f"{LOG} hwnd={w['hwnd']:<9} {w['class']:<24} "
                  f"{w['rect'][2]}x{w['rect'][3]}  {w['title'][:40]}", file=sys.stderr)
        print(json.dumps({"output": {"ok": True, "windows": windows[:40]}},
                         ensure_ascii=False))
        return 0

    win = pick_window(windows, args)
    if not win:
        print(f"{LOG} 未找到目标窗口（用 --list 查看）", file=sys.stderr)
        print(json.dumps({"output": {"ok": False,
                                     "error": "未找到目标窗口；先 --list 查看 hwnd/标题"}},
                         ensure_ascii=False))
        return 1
    print(f"{LOG} 目标：hwnd={win['hwnd']} class={win['class']} title={win['title'][:40]}",
          file=sys.stderr)

    ps = (_PS_TEMPLATE
          .replace("__HWND__", str(win["hwnd"]))
          .replace("__DEPTH__", str(args.depth))
          .replace("__BUDGET__", str(args.budget)))
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True)
    lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
    elements, done, truncated = [], None, False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line == "NO_WINDOW":
            print(json.dumps({"output": {"ok": False, "error": "UIA 打不开该窗口"}},
                             ensure_ascii=False))
            return 1
        if line == "NOT_READY":
            print(json.dumps({"output": {"ok": False,
                                         "error": "UIA 失明未就绪；按排障手册重启微信客户端后重试"}},
                             ensure_ascii=False))
            return 1
        if line.startswith("DONE "):
            done = int(line.split()[1])
            continue
        try:
            elements.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"{LOG} [跳过异常行] {line[:80]}", file=sys.stderr)
    if done is None:
        print(json.dumps({"output": {"ok": False,
                                     "error": f"PowerShell 未正常完成：{proc.stderr.decode('utf-8', errors='replace')[:200]}"}},
                         ensure_ascii=False))
        return 1
    truncated = done >= args.budget
    # 逐行输出控件树（每行一个紧凑 JSON），末行才是汇总 —— 符合 skill 的 stdout 约定
    for el in elements:
        print(json.dumps(el, ensure_ascii=False))
    print(f"{LOG} 共输出 {done} 个控件（budget={args.budget}，depth={args.depth}）",
          file=sys.stderr)
    print(json.dumps({"output": {"ok": True, "hwnd": win["hwnd"],
                                 "class": win["class"], "title": win["title"],
                                 "elements": done, "truncated": truncated}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
