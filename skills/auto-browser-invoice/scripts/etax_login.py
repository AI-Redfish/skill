#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.45"]
# ///
"""etax_login.py — 电子税务局登录建立与登录态检查（人工登录，脚本辅助）。

流程：确保 CDP 会话（复用/启动真实 Chrome，browser_session.py）→ 打开电子税务局首页
→ 检测登录态（页头是否存在可见的「登录」入口）→ 未登录且非 --check-only 时拟人点击
「登录」并等待用户在浏览器窗口人工完成登录（扫码/账号/短信）→ 轮询确认登录成功。

合规红线：登录凭据与验证码一律人工输入，本脚本绝不读取/填写密码与验证码；
出现滑块/验证码/短信验证即转人工，不做任何自动化绕过。

用法：
  uv run etax_login.py [--check-only] [--timeout 300] [--port 9333]
                       [--profile-dir PATH] [--url URL] [--workdir D]

参数：
  --check-only   只打开首页并报告登录态，不点击「登录」、不等待人工登录
  --timeout      等待人工登录的最长秒数（默认 300）
  --url          电子税务局首页（默认读 .env 的 ETAX_URL，再默认湖北站点）

输出：JSON 到 stdout（status/logged_in/url/action/hint 或 error），日志到 stderr。
退出码：0 成功（含 check-only 完成）；2 浏览器/会话失败；3 等待人工登录超时；
4 登录态无法判定；5 页面导航失败。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402
import browser_session as bs  # noqa: E402
import human  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402  (PEP 723 提供)

LOGIN_TEXT = "登录"
HOME_MARKER = "电子税务局"
POLL_INTERVAL_SEC = 2.0


def detect_login_state(page) -> dict:
    """检测登录态。

    判定依据（保守，宁可 unknown 不误报）：
    - 页面上存在可见的、文本恰为「登录」的元素 → 未登录（登录页/首页未登录都有）
    - URL 含 login → 未登录
    - 两者皆否 → 已登录
    - DOM 查询异常 → unknown（站点改版/页面未就绪）
    """
    evidence: list[str] = []
    try:
        url = page.url
    except Exception as exc:
        return {"logged_in": None, "evidence": [f"page_closed_or_error: {exc}"]}
    evidence.append(f"url={url}")
    on_login_page = "login" in url.lower()
    try:
        loc = page.get_by_text(LOGIN_TEXT, exact=True)
        cnt = loc.count()
        visible = 0
        for i in range(min(cnt, 8)):
            try:
                if loc.nth(i).is_visible():
                    visible += 1
            except Exception:
                continue
        evidence.append(f"visible_exact_{LOGIN_TEXT}={visible}")
    except Exception as exc:
        evidence.append(f"locator_error={exc}")
        return {"logged_in": None, "evidence": evidence}

    if visible > 0 or on_login_page:
        return {"logged_in": False, "evidence": evidence}
    # 防 WAF 质询页误判：质询页没有「登录」入口，也没有首页标识 → 必须判 unknown
    try:
        marker = HOME_MARKER in page.title() or HOME_MARKER in page.locator("body").inner_text(timeout=8000)[:2000]
    except Exception as exc:
        evidence.append(f"marker_error={exc}")
        return {"logged_in": None, "evidence": evidence}
    evidence.append(f"home_marker={marker}")
    if not marker:
        return {"logged_in": None, "evidence": evidence}
    return {"logged_in": True, "evidence": evidence}


def _goto_home(page, url: str) -> None:
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            c.log(f"打开首页（第 {attempt} 次）：{url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            human.settle(page, network_timeout=15000)
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=8000)[:600]
            except Exception:
                pass
            if HOME_MARKER in body or HOME_MARKER in (page.title() or ""):
                return
            # 可能是 WAF 质询页：等它自动放行后重载一次
            c.log("页面未见「电子税务局」标识（疑似 WAF 质询页），等待后重试")
            page.wait_for_timeout(4000)
            page.reload(wait_until="domcontentloaded", timeout=60000)
            human.settle(page, network_timeout=10000)
            return
        except Exception as exc:
            last_exc = exc
            time.sleep(3)
    raise RuntimeError(f"打开首页失败（问题）；{last_exc}（原因）；检查网络与 URL 后重试（行动）")


def main() -> int:
    parser = argparse.ArgumentParser(description="电子税务局登录建立/登录态检查")
    parser.add_argument("--check-only", action="store_true", help="只检查登录态，不进入登录流程")
    parser.add_argument("--timeout", type=int, default=300, help="等待人工登录秒数（默认 300）")
    parser.add_argument("--port", type=int, default=bs.DEFAULT_PORT)
    parser.add_argument("--profile-dir", default=str(bs.DEFAULT_PROFILE))
    parser.add_argument("--url", default=None, help="覆盖电子税务局首页 URL")
    parser.add_argument("--workdir", default=".", help="读取 <workdir>/.agents/.env")
    args = parser.parse_args()
    c.setup_utf8()

    env = c.load_env(args.workdir)
    url = (args.url or env.get("ETAX_URL") or c.DEFAULT_ETAX_URL).strip()
    host = urlparse(url).netloc or "etax"

    try:
        session = bs.ensure_session(args.port, Path(args.profile_dir))
    except RuntimeError as exc:
        c.emit_json(c.fail("BROWSER_SESSION", str(exc), "按 message 行动项处理"))
        return 2

    t0 = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(c.cdp_url(args.port))
            if browser.contexts:
                ctx = browser.contexts[0]
            else:
                ctx = browser.new_context()
            # 复用该站点已打开的标签页；没有则新开一个
            page = next((pg for pg in ctx.pages if host in pg.url), None) or ctx.new_page()

            try:
                _goto_home(page, url)
            except RuntimeError as exc:
                c.emit_json(c.fail("NAVIGATION", str(exc), "按 message 行动项处理"))
                return 5

            state = detect_login_state(page)
            if state["logged_in"] is None:
                c.emit_json(
                    c.fail(
                        "LOGIN_STATE_UNKNOWN",
                        "无法判定登录态（问题）；页面结构未就绪或站点改版（原因）；"
                        "截图确认页面后重试（行动）",
                        "不盲试，先人工确认",
                    )
                    | {"evidence": state["evidence"]}
                )
                return 4

            if state["logged_in"]:
                c.emit_json({
                    "status": "ok",
                    "logged_in": True,
                    "action": "already_logged_in",
                    "url": page.url,
                    "browser": session["action"],
                    "elapsed_sec": round(time.time() - t0, 1),
                    "hint": "已登录，登录态在专用 profile 中持久复用",
                })
                return 0

            if args.check_only:
                c.emit_json({
                    "status": "ok",
                    "logged_in": False,
                    "action": "check_only",
                    "url": page.url,
                    "browser": session["action"],
                    "elapsed_sec": round(time.time() - t0, 1),
                    "hint": "当前未登录；去掉 --check-only 重新运行即可进入人工登录流程",
                })
                return 0

            # 完整流程：拟人点击「登录」，等待人工完成
            try:
                page.bring_to_front()  # 确保窗口前台，用户可直接接管扫码
            except Exception:
                pass
            try:
                loc = page.get_by_text(LOGIN_TEXT, exact=True).first
                c.log(f"点击「{LOGIN_TEXT}」入口…")
                human.human_click(page, loc)
            except Exception as exc:
                c.emit_json(c.fail(
                    "LOGIN_ENTRY",
                    f"找不到或点不动「{LOGIN_TEXT}」入口（问题）；{exc}（原因）；"
                    "站点可能改版，截图确认后更新 playbook（行动）",
                    "先人工确认页面",
                ))
                return 4

            c.log(f"请在浏览器窗口中人工完成登录（扫码/账号/短信），最长等待 {args.timeout}s…")
            deadline = time.time() + args.timeout
            while time.time() < deadline:
                time.sleep(POLL_INTERVAL_SEC)
                st = detect_login_state(page)
                if st["logged_in"] is True:
                    time.sleep(2)  # 二次确认，避免瞬时误判
                    st = detect_login_state(page)
                    if st["logged_in"] is True:
                        c.emit_json({
                            "status": "ok",
                            "logged_in": True,
                            "action": "manual_login_confirmed",
                            "url": page.url,
                            "browser": session["action"],
                            "elapsed_sec": round(time.time() - t0, 1),
                            "hint": "人工登录成功，登录态已保存在专用 profile",
                        })
                        return 0
                elif st["logged_in"] is None and "page_closed" in str(st["evidence"]):
                    c.emit_json(c.fail(
                        "WINDOW_CLOSED",
                        "登录页被关闭（问题）；人工操作中窗口关闭（原因）；"
                        "重新运行本脚本再登录一次（行动）",
                        "等待期间不要关闭浏览器窗口",
                    ))
                    return 2
            c.emit_json(c.fail(
                "LOGIN_TIMEOUT",
                f"等待人工登录超过 {args.timeout}s（问题）；登录未完成（原因）；"
                "确认用户在场后加大 --timeout 重跑（行动）",
                "登录中途的进度不会丢失",
            ))
            return 3
    except SystemExit:
        raise
    except Exception as exc:
        c.emit_json(c.fail("UNEXPECTED", f"未预期错误（问题）；{exc}（原因）；查看 stderr 日志定位（行动）"))
        return 2


if __name__ == "__main__":
    sys.exit(main())
