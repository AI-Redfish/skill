#!/usr/bin/env python3
"""_common.py — auto-browser-invoice 共享工具库（纯标准库，无 CLI，被其他脚本 import）。

提供：
- setup_utf8()：Windows GBK 控制台下强制 UTF-8 输出，防中文乱码
- log()/emit_json()：日志到 stderr、JSON 到 stdout 的统一输出
- parse_env()/load_env()：读取 <workdir>/.agents/.env（与 skill-creator-plus env_utils.py 同格式）
- find_browser()：探测本机 Chrome/Edge 可执行文件（Chrome 优先）
- cdp_url()/cdp_alive()：CDP 调试端口探测
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

ENV_REL = Path(".agents") / ".env"

DEFAULT_ETAX_URL = "https://etax.hubei.chinatax.gov.cn:8443/"

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg: str) -> None:
    print(f"[auto-browser-invoice] {msg}", file=sys.stderr)


def emit_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def fail(code: str, message: str, hint: str) -> dict:
    return {"status": "error", "error": {"code": code, "message": message, "hint": hint}}


def parse_env(text: str) -> dict:
    """解析 .env 文本：一行一个 键=值，# 注释，成对双引号包裹会被剥离。"""
    result: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        i = line.find("=")
        if i <= 0:
            continue
        key, value = line[:i].strip(), line[i + 1:].strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        result[key] = value
    return result


def load_env(workdir: str | Path = ".") -> dict:
    p = Path(workdir) / ENV_REL
    if not p.is_file():
        return {}
    return parse_env(p.read_text(encoding="utf-8-sig", errors="replace"))


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
    return f"http://127.0.0.1:{port}"


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
    """端口三态：cdp=可用 CDP 会话；busy=TCP 在监听但不是健康 CDP（如被用户日常
    Chrome/RPA 工具占用，或 DevTools 被限制只回 404）；free=空闲可直接绑定。"""
    if cdp_alive(port) is not None:
        return "cdp"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return "busy" if s.connect_ex(("127.0.0.1", port)) == 0 else "free"
    finally:
        s.close()
