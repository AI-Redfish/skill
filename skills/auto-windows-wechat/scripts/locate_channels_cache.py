#!/usr/bin/env python3
"""locate_channels_cache.py — 视频号视频缓存目录定位器（差分法，零第三方依赖）。

原理：微信播放视频号视频时会把媒体缓存到本地，4.x 没有公开固定路径。本工具
对候选根目录做文件系统差分：播放前后「新增或变大且 >=50KB」的文件即缓存候选，
按目录聚合、按新增字节排序；命中含 finder/video/cache/radium 等关键词的目录时
自动记录到 .agents/channels_cache_dir.json，供抓取脚本复用。

子命令:
    watch [--seconds 900] [--interval 5] [--add-root P]...   基线→轮询→报告
                                                             （Ctrl+C 提前出报告）
    snapshot [--add-root P]...     手动两阶段：拍基线（然后去播放视频）
    diff [--add-root P]...         手动两阶段：与最近基线比对
    known                          打印已记录的缓存目录

用法:
    uv run scripts/locate_channels_cache.py watch --seconds 900
    uv run scripts/locate_channels_cache.py snapshot   # 然后去播放视频
    uv run scripts/locate_channels_cache.py diff

注意：若该视频此前已完整播放过（缓存已存在），差分法看不到新增——先换一个
没看过的视频定位目录，或清掉该目录后重试。

stdout 末行 JSON {"output": {...}}；诊断日志 stderr（[channels_probe] 前缀）。
Python 3.10+ 仅标准库；仅 Windows（配合本机微信客户端）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

LOG = "[channels_probe]"

# 管道输出统一 UTF-8：Windows 下 Python 写管道默认 ANSI 代码页，中文会乱码。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

MIN_SIZE = 50 * 1024  # 小于 50KB 视为噪声（缩略图 / 索引 / 心跳文件）
TEMP_DEPTH = 2        # %TEMP% 只扫到根下第 2 层
PRUNE_DIRS = {
    "log", "logs", "crash", "crashpad", "crashinfo", "Backup", "backup",
    "db_storage", "mmkv", "codecache", "GPUCache", "GrShaderCache",
    "ShaderCache", "blob_storage", "Local Storage", "Session Storage",
    "Network", "apm_record", "WmpfCache", "login", "head_imgs",
}
GUESS_KEYS = ("finder", "channels", "video", "media", "radium", "xwechat", "download")

AGENT_DIR = Path(__file__).resolve().parent.parent / ".agents"
BASELINE_FILE = AGENT_DIR / "cache_probe_baseline.json"
FOUND_FILE = AGENT_DIR / "channels_cache_dir.json"


def candidate_roots(extra: list[str]) -> list[tuple[Path, bool]]:
    """返回 [(根目录, 是否限深)]；bool=True 表示按 %TEMP% 规则限深扫描。"""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    temp = Path(os.environ.get("TEMP", home / "AppData" / "Local" / "Temp"))
    roots: list[tuple[Path, bool]] = [
        (Path("D:/program/WeChat/xwechat_files"), False),  # 本机实测数据目录
        (home / "Documents" / "xwechat_files", False),     # 4.x 默认数据目录
        (appdata / "Tencent" / "xwechat", False),          # WeChatAppEx / radium
        (appdata / "Tencent" / "WeChat" / "radium", False),
        (temp, True),                                      # 播放器可能先落临时目录
    ]
    for p in extra:
        pp = Path(p)
        if pp.is_dir():
            roots.append((pp, False))
    return [r for r in roots if r[0].is_dir()]


def _under(d: Path, root: Path) -> bool:
    try:
        d.relative_to(root)
        return True
    except ValueError:
        return False


def scan_root(root: Path, limited: bool) -> dict[str, tuple[int, int]]:
    """scandir 递归扫单根；Windows 上 DirEntry.stat 零额外系统调用，遍历开销低。"""
    out: dict[str, tuple[int, int]] = {}
    stack: list[tuple[str, int]] = [(str(root), 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = os.scandir(d)
        except OSError:
            continue
        with entries:
            for e in entries:
                name = e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if name in PRUNE_DIRS:
                            continue
                        if limited and depth >= TEMP_DEPTH:
                            continue
                        stack.append((e.path, depth + 1))
                    else:
                        st = e.stat(follow_symlinks=False)
                        if st.st_size >= MIN_SIZE:
                            out[e.path] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    continue
    return out


def scan_all(roots: list[tuple[Path, bool]]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for root, limited in roots:
        out.update(scan_root(root, limited))
    return out


def diff(baseline: dict, current: dict) -> list[tuple[str, int, int]]:
    """返回 [(path, 新增字节数, mtime)]：新增文件算全量，已存在的算增量。"""
    changes = []
    for p, (mt, sz) in current.items():
        old = baseline.get(p)
        if old is None:
            changes.append((p, sz, mt))
        elif sz > old[1]:
            changes.append((p, sz - old[1], mt))
    return changes


def group(changes: list[tuple[str, int, int]]) -> list[dict]:
    groups: dict[str, dict] = {}
    for p, delta, mt in changes:
        d = str(Path(p).parent)
        g = groups.setdefault(
            d, {"dir": d, "new_bytes": 0, "files": 0, "sample": [], "newest": 0}
        )
        g["new_bytes"] += delta
        g["files"] += 1
        if mt > g["newest"]:
            g["newest"] = mt
        if len(g["sample"]) < 3:
            g["sample"].append(p)
    return sorted(groups.values(), key=lambda g: -g["new_bytes"])


def report(groups: list[dict]) -> None:
    if not groups:
        print(f"{LOG} 未发现新增/变大的 >=50KB 文件", file=sys.stderr)
        print(f"{LOG} 提示：若该视频此前已完整播放过，缓存早已存在，差分法看不到；"
              f"请换一个没看过的视频，或清缓存后重试", file=sys.stderr)
        return
    print(f"{LOG} 缓存候选目录（按新增字节排序，Top 15）：", file=sys.stderr)
    for g in groups[:15]:
        print(f"{LOG}  +{g['new_bytes'] / 1048576:.1f}MB  {g['files']} 个文件  {g['dir']}",
              file=sys.stderr)
        for s in g["sample"]:
            print(f"{LOG}      e.g. {Path(s).name}", file=sys.stderr)


def save_guess(groups: list[dict]) -> dict | None:
    """命中关键词目录时记录到 FOUND_FILE；返回被记录的组。"""
    for g in groups:
        low = g["dir"].lower().replace("\\", "/")
        if any(k in low for k in GUESS_KEYS):
            AGENT_DIR.mkdir(parents=True, exist_ok=True)
            FOUND_FILE.write_text(json.dumps({
                "dir": g["dir"],
                "new_bytes": g["new_bytes"],
                "files": g["files"],
                "sample": g["sample"],
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{LOG} 已记录缓存目录 → {FOUND_FILE}", file=sys.stderr)
            return g
    return None


def top_payload(groups: list[dict], n: int = 5) -> list[dict]:
    return [
        {"dir": g["dir"], "new_bytes": g["new_bytes"], "files": g["files"],
         "sample": [Path(s).name for s in g["sample"]]}
        for g in groups[:n]
    ]


def cmd_watch(args) -> int:
    roots = candidate_roots(args.add_root)
    print(f"{LOG} 监听 {args.seconds}s（间隔 {args.interval}s），根目录：", file=sys.stderr)
    for r, _ in roots:
        print(f"{LOG}  {r}", file=sys.stderr)
    print(f"{LOG} >>> 现在去微信里播放目标视频号视频，播完后等本工具汇总 <<<", file=sys.stderr)
    base = scan_all(roots)
    print(f"{LOG} 基线：{len(base)} 个文件（>=50KB）", file=sys.stderr)
    seen: dict[str, dict] = {}
    t0 = time.time()
    try:
        while time.time() - t0 < args.seconds:
            time.sleep(args.interval)
            cur = scan_all(roots)
            for g in group(diff(base, cur)):
                if g["dir"] not in seen:
                    seen[g["dir"]] = g
                    print(f"{LOG} [新信号] +{g['new_bytes'] / 1048576:.1f}MB  {g['dir']}",
                          file=sys.stderr)
            print(f"{LOG} …已监听 {time.time() - t0:.0f}s，信号目录 {len(seen)} 个",
                  file=sys.stderr)
    except KeyboardInterrupt:
        print(f"{LOG} 手动中断，立即汇总", file=sys.stderr)
    groups = sorted(seen.values(), key=lambda g: -g["new_bytes"])
    report(groups)
    saved = save_guess(groups)
    print(json.dumps({"output": {
        "ok": True, "mode": "watch", "elapsed_sec": round(time.time() - t0, 1),
        "candidates": len(groups), "top": top_payload(groups),
        "saved_dir": saved["dir"] if saved else None,
    }}, ensure_ascii=False))
    return 0


def cmd_snapshot(args) -> int:
    roots = candidate_roots(args.add_root)
    base = scan_all(roots)
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps({
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "data": base,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{LOG} 基线已保存（{len(base)} 个文件）→ {BASELINE_FILE}", file=sys.stderr)
    print(f"{LOG} >>> 现在去播放视频，播完后运行 diff <<<", file=sys.stderr)
    print(json.dumps({"output": {"ok": True, "mode": "snapshot", "files": len(base),
                                 "baseline": str(BASELINE_FILE)}}, ensure_ascii=False))
    return 0


def cmd_diff(args) -> int:
    if not BASELINE_FILE.is_file():
        print(json.dumps({"output": {"ok": False,
                                     "error": "没有基线，先运行 snapshot 或 watch"}},
                         ensure_ascii=False))
        return 1
    base = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["data"]
    cur = scan_all(candidate_roots(args.add_root))
    groups = group(diff(base, cur))
    report(groups)
    saved = save_guess(groups)
    print(json.dumps({"output": {"ok": True, "mode": "diff",
                                 "candidates": len(groups), "top": top_payload(groups),
                                 "saved_dir": saved["dir"] if saved else None}},
                     ensure_ascii=False))
    return 0


def cmd_known(_args) -> int:
    if FOUND_FILE.is_file():
        data = json.loads(FOUND_FILE.read_text(encoding="utf-8"))
        print(f"{LOG} 已记录缓存目录：{data['dir']}（{data['saved_at']}）", file=sys.stderr)
        print(json.dumps({"output": {"ok": True, "dir": data["dir"],
                                     "sample": data.get("sample", [])}},
                         ensure_ascii=False))
    else:
        print(json.dumps({"output": {"ok": False,
                                     "error": "尚未定位过缓存目录，先运行 watch/diff"}},
                         ensure_ascii=False))
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="视频号视频缓存目录定位器（差分法）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="基线→轮询→报告")
    w.add_argument("--seconds", type=int, default=900)
    w.add_argument("--interval", type=float, default=5.0)
    w.add_argument("--add-root", action="append", default=[], metavar="P")
    w.set_defaults(fn=cmd_watch)

    s = sub.add_parser("snapshot", help="手动两阶段：拍基线")
    s.add_argument("--add-root", action="append", default=[], metavar="P")
    s.set_defaults(fn=cmd_snapshot)

    d = sub.add_parser("diff", help="手动两阶段：与基线比对")
    d.add_argument("--add-root", action="append", default=[], metavar="P")
    d.set_defaults(fn=cmd_diff)

    k = sub.add_parser("known", help="打印已记录的缓存目录")
    k.set_defaults(fn=cmd_known)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
