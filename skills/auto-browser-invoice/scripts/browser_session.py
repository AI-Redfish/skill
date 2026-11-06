#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.45"]
# ///
"""browser_session.py — 管理本机真实浏览器的 CDP 调试会话（反检测方案 A，详见
references/anti-detection.md）。

职责：启动/复用真实 Chrome/Edge（专用 profile + --remote-debugging-port），
供 Playwright connect_over_cdp 附着。绝不注入 --enable-automation 等自动化标记，
绝不使用 headless。

用法：
  uv run browser_session.py ensure [--port 9222] [--profile-dir PATH] [--browser PATH]
  uv run browser_session.py status [--port 9222] [--profile-dir PATH]
  uv run browser_session.py close  [--port 9222] [--profile-dir PATH]

输出：JSON 到 stdout（status/data/error），日志到 stderr。
退出码：0 成功；2 失败（浏览器缺失/启动超时/端口被非 CDP 进程占用）。

行为约定：
- 端口已有 CDP 会话 → 直接复用（action=attached），不重复启动
- 复用会话的 profile 可能与本 skill 的不同：原样报告，由调用方决定是否 close 重开
- 本脚本启动的浏览器 PID 记录在 <profile-dir>/.cdp-session.json；
  close 只关闭本脚本启动的实例，绝不杀用户自己开的浏览器
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

DEFAULT_PORT = 9333
SESSION_FILE = ".cdp-session.json"
CDP_WAIT_SEC = 60

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = SKILL_DIR / "profiles" / "chrome"


def _session_path(profile_dir: Path) -> Path:
    return profile_dir / SESSION_FILE


def _read_session(profile_dir: Path) -> dict | None:
    p = _session_path(profile_dir)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _write_session(profile_dir: Path, data: dict) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    _session_path(profile_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _clear_session(profile_dir: Path) -> None:
    try:
        _session_path(profile_dir).unlink(missing_ok=True)
    except OSError:
        pass


def ensure_session(port: int, profile_dir: Path, browser: str | None = None) -> dict:
    """确保 CDP 会话可用：复用或启动。返回描述 dict，含 action/action_detail。

    抛出 RuntimeError 表示失败（message/hint 面向调用方与用户）。
    """
    state = c.port_state(port)
    if state == "busy":
        raise RuntimeError(
            f"端口 {port} 已被其他进程占用且不是健康 CDP 会话（问题）；"
            "常见于被用户日常浏览器或 RPA 工具占用（原因）；"
            f"换一个端口重试，如 --port {port + 1}（行动）"
        )
    if state == "cdp":
        alive = c.cdp_alive(port)
        session = _read_session(profile_dir) or {}
        return {
            "action": "attached",
            "action_detail": "端口已有 CDP 会话，直接复用",
            "endpoint": c.cdp_url(port),
            "browser": session.get("browser") or alive.get("Browser", "unknown"),
            "pid": session.get("pid"),
            "profile_dir": str(profile_dir),
            "own_session": bool(session),
            "version": alive,
        }

    exe = browser or c.find_browser()
    if not exe:
        raise RuntimeError(
            "未找到本机 Chrome/Edge（问题）；候选路径均不存在（原因）；"
            "安装 Chrome 后重试，或 --browser 指定可执行文件路径（行动）"
        )

    profile_dir.mkdir(parents=True, exist_ok=True)
    # 反检测关键：真实浏览器 + 最小参数，不加任何自动化标记（--enable-automation 等）
    cmd = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
    ]
    c.log(f"启动真实浏览器：{exe}（profile={profile_dir}，port={port}）")
    proc = subprocess.Popen(cmd)
    _write_session(
        profile_dir,
        {
            "pid": proc.pid,
            "port": port,
            "browser": exe,
            "profile_dir": str(profile_dir),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    deadline = time.time() + CDP_WAIT_SEC
    while time.time() < deadline:
        alive = c.cdp_alive(port, timeout=1.0)
        if alive:
            break
        time.sleep(0.5)
    else:
        _clear_session(profile_dir)
        raise RuntimeError(
            f"浏览器已启动但 CDP 端口 {port} 未就绪（问题）；"
            f"启动超时 {CDP_WAIT_SEC}s，或端口被抢注/被安全软件拦截（原因）；"
            f"换 --port 重试并检查杀软日志（行动）"
        )

    # 用 playwright 验证可附着（附着即断开，浏览器保持运行）
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(c.cdp_url(port))
            b.close()
    except Exception as exc:  # pragma: no cover - 环境相关
        raise RuntimeError(
            f"Playwright 无法附着 CDP 端口 {port}（问题）；{exc}（原因）；"
            "确认 playwright 已安装（uv run 会自动装）后重试（行动）"
        )

    return {
        "action": "launched",
        "action_detail": "新启动真实浏览器并已验证可附着",
        "endpoint": c.cdp_url(port),
        "browser": exe,
        "pid": proc.pid,
        "profile_dir": str(profile_dir),
        "own_session": True,
        "version": alive,
    }


def cmd_ensure(args: argparse.Namespace) -> int:
    try:
        info = ensure_session(args.port, Path(args.profile_dir), args.browser)
    except RuntimeError as exc:
        c.setup_utf8()
        c.emit_json(c.fail("BROWSER_SESSION", str(exc), "按 message 中的行动项处理"))
        return 2
    c.setup_utf8()
    c.emit_json({"status": "ok", **info})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    c.setup_utf8()
    alive = c.cdp_alive(args.port)
    session = _read_session(Path(args.profile_dir))
    if alive:
        c.emit_json(
            {
                "status": "ok",
                "cdp_alive": True,
                "endpoint": c.cdp_url(args.port),
                "own_session": bool(session),
                "pid": session.get("pid") if session else None,
                "version": alive,
            }
        )
        return 0
    c.emit_json(
        {
            "status": "ok",
            "cdp_alive": False,
            "own_session": False,
            "hint": "无 CDP 会话；运行 ensure 子命令启动/复用浏览器",
        }
    )
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    c.setup_utf8()
    session = _read_session(Path(args.profile_dir))
    if not session or not session.get("pid"):
        if c.cdp_alive(args.port):
            c.emit_json(
                c.fail(
                    "EXTERNAL_SESSION",
                    "端口有 CDP 会话但非本脚本启动（问题）；没有 PID 记录（原因）；"
                    "若确认要关闭请在浏览器窗口手动退出，或用 --profile-dir 指向启动时的 profile（行动）",
                    "不动用户自己开的浏览器",
                )
            )
            return 2
        c.emit_json({"status": "ok", "closed": False, "detail": "无会话，无需关闭"})
        return 0
    pid = int(session["pid"])
    c.log(f"关闭本脚本启动的浏览器 PID={pid}")
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    time.sleep(1.0)
    _clear_session(Path(args.profile_dir))
    still = c.cdp_alive(args.port)
    c.emit_json(
        {
            "status": "ok",
            "closed": not still,
            "pid": pid,
            "detail": "已关闭" if not still else "PID 已终止但端口仍有响应，请人工检查",
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="管理本机真实浏览器 CDP 会话")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ensure", help="确保 CDP 会话可用（复用或启动）")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    p.add_argument("--browser", default=None, help="浏览器可执行路径（默认自动探测）")

    p = sub.add_parser("status", help="查看 CDP 会话状态")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))

    p = sub.add_parser("close", help="关闭本脚本启动的浏览器实例")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))

    args = parser.parse_args()
    return {"ensure": cmd_ensure, "status": cmd_status, "close": cmd_close}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
