#!/usr/bin/env python3
"""export_mp4.py — HTML→MP4 导出总编排(录制 webm + 合成音轨 + ffmpeg 混流转码)。

用途: 把本地 H5 页面(如动森请柬)自动翻页录制并导出为竖屏 MP4(默认 1080x1920,
      H.264+AAC, faststart)。串联 ensure_ffmpeg.py → record_page.py →
      synth_bgm.py → ffmpeg, 逐步校验, 失败给三要素错误。
用法: python3 export_mp4.py --html 请柬.html [--out 视频.mp4] \
        [--stay "1500,5000,..."] [--viewport 540x960] [--out-size 1080x1920] \
        [--no-bgm] [--nav-mode go|selector|none] [--nav-selector .next] \
        [--start-selector "#startBtn|none"] [--keep-temp]
依赖: Python 3.9+ 纯标准库；需 node+Chrome/Edge(录制), ffmpeg 自动获取。
输出: JSON 到 stdout(status/out/duration_s/resolution/has_audio/steps)。
退出码: 0=成功 1=执行失败 2=参数错误。
工作目录: <html 同目录>/<html主名>-export/(videos/、bgm.wav、timeline.json)，默认用后即删。
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent


def out_json(obj: dict, code: int = 0) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.exit(code)


def run_step(name: str, cmd: list[str], timeout: int) -> dict:
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        out_json({"status": "error", "error": {
            "message": f"步骤 {name} 失败",
            "reason": (r.stderr or b"")[-600:].decode(errors="replace") or f"exit={r.returncode}",
            "action": "按原因排查后重试；可加 --keep-temp 保留中间产物"}},
            1)
    try:
        return json.loads(r.stdout.decode(errors="replace"))
    except json.JSONDecodeError:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser(description="HTML→MP4 全流程导出")
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", help="输出 MP4 路径, 默认 <html主名>.mp4")
    ap.add_argument("--stay", default="1500,5000,6000,9000,6500,5500,4500")
    ap.add_argument("--viewport", default="540x960")
    ap.add_argument("--out-size", default="1080x1920", help="输出分辨率, 如 1080x1920")
    ap.add_argument("--no-bgm", action="store_true", help="不加背景音乐(纯静音视频)")
    ap.add_argument("--nav-mode", choices=["go", "selector", "none"], default="go")
    ap.add_argument("--nav-selector", default=".next")
    ap.add_argument("--start-selector", default="#startBtn")
    ap.add_argument("--keep-temp", action="store_true", help="保留导出工作目录")
    a = ap.parse_args()

    html = Path(a.html)
    if not html.is_file():
        out_json({"status": "error", "error": {"message": f"HTML 不存在: {a.html}"}}, 2)
    try:
        ow, oh = (int(x) for x in a.out_size.lower().split("x"))
        vw, vh = (int(x) for x in a.viewport.lower().split("x"))
    except Exception:
        out_json({"status": "error", "error": {"message": "尺寸格式错误, 应如 1080x1920"}}, 2)

    export_dir = html.parent / f"{html.stem}-export"
    export_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = Path(a.out) if a.out else html.with_suffix(".mp4")
    steps: dict[str, dict] = {}

    ff = run_step("ensure_ffmpeg", ["python3", str(SCRIPTS / "ensure_ffmpeg.py"),
                                     "--workdir", str(Path.home())], 600)
    ffmpeg = Path(ff["path"])
    steps["ensure_ffmpeg"] = {"path": str(ffmpeg), "source": ff.get("source")}

    rec = run_step("record_page", ["python3", str(SCRIPTS / "record_page.py"),
                                    "--html", str(html), "--workdir", str(export_dir),
                                    "--stay", a.stay, "--viewport", a.viewport,
                                    "--nav-mode", a.nav_mode, "--nav-selector", a.nav_selector,
                                    "--start-selector", a.start_selector], 900)
    webm, timeline = Path(rec["webm"]), Path(rec["timeline"])
    steps["record_page"] = {"webm": str(webm)}

    has_audio = not a.no_bgm
    wav = export_dir / "bgm.wav"
    if has_audio:
        bg = run_step("synth_bgm", ["python3", str(SCRIPTS / "synth_bgm.py"),
                                     "--timeline", str(timeline), "--out", str(wav)], 300)
        steps["synth_bgm"] = {"wav": str(wav), "duration_s": bg.get("duration_s")}

    # 比例不一致时等比缩放+黑边, 一致时直接整数倍放大
    if abs(vw / vh - ow / oh) < 0.02:
        vf = f"scale={ow}:{oh}:flags=lanczos,format=yuv420p"
    else:
        vf = (f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,"
              f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2,format=yuv420p")
    cmd = [str(ffmpeg), "-y", "-i", str(webm)]
    if has_audio:
        cmd += ["-i", str(wav)]
    cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-movflags", "+faststart", str(out_mp4)]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0 or not out_mp4.is_file():
        out_json({"status": "error", "error": {
            "message": "ffmpeg 转码失败",
            "reason": r.stderr.decode(errors="replace")[-600:],
            "action": "检查 webm/wav 是否完整; 可加 --keep-temp 排查"}}, 1)

    probe = subprocess.run([str(ffmpeg), "-i", str(out_mp4)], capture_output=True)
    meta = probe.stderr.decode(errors="replace")
    dur = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", meta)
    res = re.search(r"Video:.*?(\d{3,4}x\d{3,4})", meta)
    duration_s = round(sum(float(x) * m for x, m in zip(dur.groups(), (3600, 60, 1))), 2) if dur else None
    resolution = res.group(1) if res else None
    if not a.keep_temp:
        subprocess.run(["rm", "-rf", str(export_dir)], capture_output=True)

    out_json({"status": "ok", "out": str(out_mp4.resolve()), "size": out_mp4.stat().st_size,
              "duration_s": duration_s, "resolution": resolution,
              "has_audio": has_audio, "steps": steps})


if __name__ == "__main__":
    main()
