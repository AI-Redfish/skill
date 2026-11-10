#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.45"]
# ///
"""browser_session.py — 管理本机真实浏览器的 CDP 调试会话。

职责：启动/复用真实 Chrome/Edge（专用 profile + --remote-debugging-port），
供 Playwright connect_over_cdp 附着。绝不注入 --enable-automation 等自动化标记，
绝不使用 headless。Chrome 136+ 在默认 profile 下静默禁用调试端口，
故必须使用独立 user-data-dir（本脚本用 <skill>/profiles/chrome）。

用法：
  uv run browser_session.py ensure [--port 9342] [--profile-dir PATH] [--browser PATH]
  uv run browser_session.py status [--port 9342]
  uv run browser_session.py close  [--port 9342] [--profile-dir PATH]

输出：JSON 到 stdout，日志到 stderr。
退出码：0 成功；2 失败（浏览器缺失/启动超时/端口被非 CDP 进程占用）。

行为约定：
- 端口已有健康 CDP 会话 → 直接复用（action=attached），不重复启动
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

DEFAULT_PORT = 9342
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
    """确保 CDP 会话可用：复用或启动。失败抛 RuntimeError。"""
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
            "browser": session.get("browser") or (alive or {}).get("Browser", "unknown"),
            "pid": session.get("pid"),
            "profile_dir": str(profile_dir),
            "own_session": bool(session),
        }

    exe = browser or c.find_browser()
    if not exe:
        raise RuntimeError(
            "未找到本机 Chrome/Edge（问题）；候选路径均不存在（原因）；"
            "安装 Chrome 后重试，或 --browser 指定可执行文件路径（行动）"
        )

    profile_dir.mkdir(parents=True, exist_ok=True)
    # 反检测关键：真实浏览器 + 最小参数，不加任何自动化标记
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
    _write_session(profile_dir, {
        "pid": proc.pid,
        "browser": exe,
        "port": port,
        "started_at": c.now_stamp(),
    })

    deadline = time.time() + CDP_WAIT_SEC
    while time.time() < deadline:
        if c.cdp_alive(port) is not None:
            return {
                "action": "started",
                "action_detail": "已启动新浏览器实例",
                "endpoint": c.cdp_url(port),
                "browser": exe,
                "pid": proc.pid,
                "profile_dir": str(profile_dir),
                "own_session": True,
            }
        time.sleep(1.0)
    raise RuntimeError(
        f"浏览器已启动但调试端口 {port} 在 {CDP_WAIT_SEC}s 内不可用（问题）；"
        "可能是启动缓慢或被安全软件拦截（原因）；重试或换端口（行动）"
    )


def status_session(port: int, profile_dir: Path) -> dict:
    alive = c.cdp_alive(port)
    session = _read_session(profile_dir) or {}
    return {
        "port": port,
        "state": c.port_state(port),
        "endpoint": c.cdp_url(port) if alive else None,
        "browser": session.get("browser"),
        "pid": session.get("pid"),
        "started_at": session.get("started_at"),
        "own_session": bool(session),
        "version": alive,
    }


def close_session(port: int, profile_dir: Path) -> dict:
    session = _read_session(profile_dir)
    if not session:
        return {"action": "noop", "action_detail": "无本脚本启动的会话记录，未做任何操作"}
    pid = session.get("pid")
    detail = {"action": "closed", "pid": pid, "port": port}
    if pid:
        try:
            if sys.platform == "win32":
                # /T 连子进程一起关（Chrome 多进程）
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, check=False)
            else:
                import signal
                import os as _os
                _os.kill(pid, signal.SIGTERM)
        except OSError as e:
            detail["action_detail"] = f"结束进程失败（进程可能已退出）：{e}"
    _clear_session(profile_dir)
    return detail


def main() -> int:
    c.setup_utf8()
    ap = argparse.ArgumentParser(description="小红书沉淀用浏览器 CDP 会话管理")
    ap.add_argument("action", choices=["ensure", "status", "close"])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    ap.add_argument("--browser", default=None, help="浏览器可执行文件路径")
    args = ap.parse_args()
    profile_dir = Path(args.profile_dir).expanduser()
    try:
        if args.action == "ensure":
            data = ensure_session(args.port, profile_dir, args.browser)
        elif args.action == "status":
            data = status_session(args.port, profile_dir)
        else:
            data = close_session(args.port, profile_dir)
    except RuntimeError as e:
        c.emit_json(c.fail("session-error", str(e), "按 message 中的（行动）处理"))
        return 2
    c.emit_json({"status": "ok", **data})
    return 0


if __name__ == "__main__":
    sys.exit(main())
