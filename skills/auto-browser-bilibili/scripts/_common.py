#!/usr/bin/env python3
"""_common.py — auto-browser-bilibili 共享工具库（纯标准库，无 CLI，被其他脚本 import）。

提供：
- setup_utf8()：Windows GBK 控制台下强制 UTF-8 输出，防中文乱码
- log()/emit_json()/fail()：日志到 stderr、JSON 到 stdout 的统一输出
- find_browser()：探测本机 Chrome/Edge 可执行文件（Chrome 优先）
- cdp_url()/cdp_alive()/port_state()：CDP 调试端口探测
- slugify()/local_date_str()/now_stamp()：输出目录与时间戳工具
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg: str) -> None:
    print(f"[auto-browser-bilibili] {msg}", file=sys.stderr)


def emit_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def fail(code: str, message: str, hint: str) -> dict:
    return {"status": "error", "error": {"code": code, "message": message, "hint": hint}}


def find_browser() -> str | None:
    """返回第一个存在的浏览器可执行路径；都没有返回 None。"""
    for cand in BROWSER_CANDIDATES:
        try:
            if cand and os.path.isfile(cand):
                return cand
        except OSError:
            continue
    return None


def cdp_url(port: int) -> str:
    # Chrome 155+ 的 DevTools HTTP 端点仅接受 Host: localhost，拒绝 127.0.0.1
    return f"http://localhost:{port}"


def cdp_alive(port: int, timeout: float = 2.0) -> dict | None:
    """探测 CDP 调试端口；存活且可用的 /json/version 返回解析后的 dict，否则 None。"""
    try:
        req = urllib.request.Request(
            f"{cdp_url(port)}/json/version", headers={"Connection": "close"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def port_state(port: int) -> str:
    """端口三态：cdp=可用 CDP 会话；busy=TCP 在监听但不是健康 CDP；free=空闲。"""
    if cdp_alive(port) is not None:
        return "cdp"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return "busy" if s.connect_ex(("127.0.0.1", port)) == 0 else "free"
    finally:
        s.close()


def slugify(title: str) -> str:
    """标题转目录名：去非法字符，空白换连字符，截断 30 字符。"""
    bad = '\\/:*?"<>|'
    s = "".join(ch for ch in (title or "") if ch not in bad and not ord(ch) < 0x20)
    s = "-".join(s.split()).strip("-")[:30]
    return s or "video"


def local_date_str(d: datetime | None = None) -> str:
    """本地时区日期 YYYYMMDD，避免 toISOString 的 UTC 偏移导致跨天错位。"""
    d = d or datetime.now()
    return d.strftime("%Y%m%d")


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
