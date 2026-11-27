#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright"]
# ///
# -*- coding: utf-8 -*-
"""auto-browser-boss 公共模块：Chrome/CDP 管理、配置、风控检测、产物写入。

被 boss_apply.py / boss_reply.py 引用，不直接运行。
依赖（由调用脚本 PEP 723 声明）：playwright
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CDP_URL = "http://127.0.0.1:9222"
ZHIPIN_HOME = "https://www.zhipin.com/"
CHAT_URL = "https://www.zhipin.com/web/geek/chat"
JOBS_URL = "https://www.zhipin.com/web/geek/jobs"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
RISK_URL_PATTERNS = ("ka=bticket", "/web/user/?ka=", "web/common/security-check")


def skill_root() -> Path:
    """skill 目录（scripts/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def workspace_root() -> Path:
    """运行时工作空间根：cwd 含 .agents 时用 cwd，否则用 skill 所在工作空间。"""
    cwd = Path.cwd()
    if (cwd / ".agents").exists():
        return cwd
    ws = skill_root().parent.parent.parent.parent  # skills/<name>/scripts -> workspace
    if (ws / ".agents").exists():
        return ws
    raise SystemExit("未找到工作空间根（无 .agents/ 目录），请在工作空间内运行")


def out_dir(sub: str = "") -> Path:
    d = workspace_root() / ".agents" / "out" / "auto-browser-boss"
    if sub:
        d = d / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def day_dir() -> Path:
    """当日产物目录：.agents/out/YYYYMMDD/auto-browser-boss/（日期目录，超 15 天可提示清理）。"""
    d = workspace_root() / ".agents" / "out" / time.strftime("%Y%m%d") / "auto-browser-boss"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------- .env 配置 ----------------

ENV_KEYS = {
    "BOSS_QUERY": None,        # 搜索关键词，如 实施工程师
    "BOSS_CITY_CODE": "101210100",  # Boss 城市代码，默认杭州
    "BOSS_SALARY": None,       # 薪资筛选 boss 编码值（可空=不过滤）
    "BOSS_EXPERIENCE": None,   # 经验筛选编码值（可空）
    "BOSS_DEGREE": None,       # 学历筛选编码值（可空）
    "BOSS_DAILY_LIMIT": "50",  # 每日投递上限
    "BOSS_GREETING": "",       # 投递后追加招呼语（空=只用 Boss 默认问候）
    "BOSS_CDP_PORT": "9222",
    "BOSS_DELAY_MIN": "3",     # 动作间最小延时（秒）
    "BOSS_DELAY_MAX": "8",     # 动作间最大延时（秒）
}


def load_env() -> dict:
    """读取工作空间 .agents/.env 的 BOSS_* 键；返回配置 dict（含默认值）。"""
    env = dict(ENV_KEYS)
    f = workspace_root() / ".agents" / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k in env:
                env[k] = v
    return env


def write_env(updates: dict) -> Path:
    """把 BOSS_* 配置写入 .agents/.env（保留其他行，键已存在则替换）。"""
    f = workspace_root() / ".agents" / ".env"
    f.parent.mkdir(parents=True, exist_ok=True)
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    for k, v in updates.items():
        if not k.startswith("BOSS_"):
            continue
        pat = f"{k}="
        hit = False
        for i, line in enumerate(lines):
            if line.strip().startswith(pat):
                lines[i] = f"{k}={v}"
                hit = True
                break
        if not hit:
            lines.append(f"{k}={v}")
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


# ---------------- Chrome / CDP ----------------

def chrome_cmd() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("未找到 Chrome，请修改 boss_common.CHROME_CANDIDATES")


def start_chrome(profile: Path | None = None) -> bool:
    """启动调试模式 Chrome（带占位标签防 window.close 退出）。返回是否新启动。"""
    import urllib.request
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
        return False  # 已在运行
    except Exception:
        pass
    profile = profile or out_dir() / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome_cmd(),
        f"--remote-debugging-port={load_env().get('BOSS_CDP_PORT', '9222')}",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "about:blank",  # 占位标签：防止唯一标签被关导致浏览器退出
        ZHIPIN_HOME,
    ]
    subprocess.Popen(cmd, creationflags=0x00000008)  # DETACHED_PROCESS
    for _ in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
            return True
        except Exception:
            continue
    raise SystemExit("Chrome 启动超时（CDP 无响应）")


def connect():
    """connect_over_cdp 并返回 (browser, zhipin_page)。page 可能为 None。"""
    from playwright.sync_api import sync_playwright

    class _Ctx:
        pass

    holder = _Ctx()
    pw = sync_playwright().start()
    holder.pw = pw
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    holder.browser = browser

    page = find_zhipin_page(browser)
    if page is None:
        ctx = browser.contexts[0]
        page = next((x for x in ctx.pages if x.url == "about:blank"), None) or ctx.new_page()
        page.add_init_script("window.close = function(){};")
        page.goto(ZHIPIN_HOME, wait_until="domcontentloaded", timeout=30000)
    holder.page = page
    return holder


def find_zhipin_page(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "zhipin.com" in pg.url:
                return pg
    return None


def risk_check(page) -> str:
    """风控状态检测。返回 ok | login | kicked | unknown。
    login: bticket 重新验证；kicked: 聊天页被跳走（仅聊天流程使用）。"""
    url = page.url
    if any(p in url for p in RISK_URL_PATTERNS):
        return "login"
    if "/web/geek/chat" in url or "/web/chat" in url:
        return "ok"
    if "zhipin.com" not in url:
        return "unknown"
    return "navigated"  # zhipin 页面但不是聊天页（供聊天流程判断 kicked）


def ev(page, js, retries=4, wait=3000):
    """evaluate 重试包装：防 SPA 渲染竞争导致的 context destroyed。"""
    last = None
    for _ in range(retries):
        try:
            return page.evaluate(js)
        except Exception as e:  # noqa: BLE001
            last = e
            page.wait_for_timeout(wait)
    raise RuntimeError(f"evaluate 失败: {last}")


# ---------------- 产物写入 ----------------

def append_jsonl(name: str, record: dict):
    f = day_dir() / name
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def today_count(name_prefix: str) -> int:
    """当日 jsonl 记录数（按文件名日期后缀）。"""
    d = day_dir()
    ts = time.strftime("%Y%m%d")
    f = d / f"{name_prefix}-{ts}.jsonl"
    if not f.exists():
        return 0
    return sum(1 for _ in f.open(encoding="utf-8"))


def rand_delay(a: float = 8.0, b: float = 20.0):
    import random
    time.sleep(random.uniform(a, b))
