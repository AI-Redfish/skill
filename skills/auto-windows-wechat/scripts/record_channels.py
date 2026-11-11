#!/usr/bin/env python3
"""视频号视频录屏重制工具：ffmpeg gdigrab 画面 + soundcard loopback 系统声音 → 合成 mp4。

子命令:
  record       同时录制主屏画面(screen.mkv)与系统声音(audio.wav)，到时或 Ctrl+C 停止
  merge        画面 + 音频合成 mp4（可选对音频裁剪）
  detect-voice 输出音频语音区间（silencedetect，用于画面/语音对齐）

依赖:
  - ffmpeg 在 PATH（或 --ffmpeg 指定路径）
  - soundcard 仅 record 录音时需要。建议独立 venv：
      uv venv .venv && uv pip install --python .venv/Scripts/python.exe soundcard
    不要用 `uv run` 长时包装本脚本：uv 父进程被回收时会连带杀掉录制子进程
    （实测见 references/troubleshooting.md §11）。

用法示例:
  python record_channels.py record --seconds 600 --dir D:/tmp/rec [--no-audio] [--device-substr Realtek]
  python record_channels.py detect-voice --audio D:/tmp/rec/audio.wav [--raw --samplerate 48000]
  python record_channels.py merge --video D:/tmp/rec/screen.mkv --audio D:/tmp/rec/audio.wav \
      --audio-start 246 --audio-end 326 -o out.mp4

输出契约: stdout 末行固定 JSON {"output": {...}}；诊断信息走 stderr 前缀 [channels_rec]。
适用范围: Windows 10/11 + ffmpeg；背景与实测依据见同目录 SKILL.md 与 references/troubleshooting.md §10-11。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

TAG = "[channels_rec]"


def _log(msg: str) -> None:
    print(f"{TAG} {msg}", file=sys.stderr)


def _finish(payload: dict) -> int:
    print(json.dumps({"output": payload}, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def _ffmpeg_path(explicit: str | None) -> str:
    path = explicit or shutil.which("ffmpeg")
    if not path:
        raise SystemExit(f"{TAG} 未找到 ffmpeg：请安装或用 --ffmpeg 指定路径")
    return path


def _pick_loopback(substr: str):
    try:
        import soundcard as sc
    except ImportError:
        return None
    mics = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    if not mics:
        return None
    return next((m for m in mics if substr in m.name), mics[0])


def cmd_record(args) -> int:
    ff = _ffmpeg_path(args.ffmpeg)
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "screen.mkv"
    audio_path = out_dir / "audio.wav"

    ffmpeg_cmd = [
        ff, "-y", "-f", "gdigrab", "-framerate", str(args.fps),
        "-offset_x", str(args.x), "-offset_y", str(args.y),
        "-video_size", f"{args.width}x{args.height}", "-i", "desktop",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-t", str(args.seconds), str(video_path),
    ]
    _log(f"启动 ffmpeg 录制主屏 {args.width}x{args.height} @ {args.fps}fps，上限 {args.seconds}s")
    ff_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    mic = None if args.no_audio else _pick_loopback(args.device_substr)
    if not args.no_audio and mic is None:
        _log("未找到 loopback 设备或未安装 soundcard，退化为只录画面")
    stop_flag = threading.Event()

    audio_holder: dict = {"audio": str(audio_path) if mic is not None else None, "audio_sec": 0.0}
    if mic is not None:
        def record_audio() -> None:
            sr, ch = args.samplerate, 2
            frames = 0
            try:
                with mic.recorder(samplerate=sr, channels=ch) as rec, \
                        wave.open(str(audio_path), "wb") as wf:
                    wf.setnchannels(ch)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    while not stop_flag.is_set():
                        data = rec.record(numframes=sr // 10)
                        wf.writeframes((data * 32767).astype("<i2").tobytes())
                        frames += len(data)
                audio_holder["audio_sec"] = round(frames / args.samplerate, 1)
            except Exception as exc:  # noqa: BLE001
                _log(f"录音线程异常退出: {exc}")
        t = threading.Thread(target=record_audio, daemon=True)
        t.start()
        _log(f"loopback 录音设备: {mic.name}")
    else:
        audio_path.unlink(missing_ok=True)

    reason = "timeout"
    try:
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            time.sleep(0.5)
            if ff_proc.poll() is not None:
                reason = "ffmpeg_exit"
                break
    except KeyboardInterrupt:
        reason = "interrupted"
        _log("收到中断，正在停止…")
    stop_flag.set()
    if ff_proc.poll() is None:
        ff_proc.terminate()
    try:
        ff_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        ff_proc.kill()
    if mic is not None:
        time.sleep(1.0)  # 等录音线程写完最后一块

    result = {
        "ok": video_path.exists() and video_path.stat().st_size > 0,
        "mode": "record",
        "video": str(video_path),
        "stop_reason": reason,
        **audio_holder,
        "audio_enabled": mic is not None,
    }
    if mic is not None and not audio_path.exists():
        result["ok"] = False
        result["error"] = "audio.wav 未生成"
    return _finish(result)


def cmd_detect_voice(args) -> int:
    ff = _ffmpeg_path(args.ffmpeg)
    cmd = [ff, "-hide_banner", "-nostats"]
    if args.raw:
        cmd += ["-f", "s16le", "-ar", str(args.samplerate), "-ac", str(args.channels)]
    cmd += ["-i", args.audio, "-af", f"silencedetect=noise=-{args.threshold}dB:d={args.min_silence}", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", proc.stderr)]
    # 文件总长：silencedetect 的最后一个 silence_end 即文件尾（末段若为有声则无该标记，此时用有声区间推）
    total = max(ends) if ends else None
    # 有声区间 = 全长减去静音区间
    silences = list(zip(starts, ends))
    voiced, cursor = [], 0.0
    for s, e in silences:
        if s > cursor:
            voiced.append({"start": round(cursor, 2), "end": round(s, 2)})
        cursor = e
    if total and cursor < total:
        voiced.append({"start": round(cursor, 2), "end": round(total, 2)})
    return _finish({
        "ok": True,
        "mode": "detect-voice",
        "audio": args.audio,
        "duration_sec": total,
        "voiced_segments": voiced,
    })


def cmd_merge(args) -> int:
    ff = _ffmpeg_path(args.ffmpeg)
    cmd = [ff, "-y"]
    if args.audio_start is not None:
        cmd += ["-ss", str(args.audio_start)]
    if args.audio_end is not None:
        cmd += ["-to", str(args.audio_end)]
    cmd += ["-i", args.audio]
    if args.video_start is not None:
        cmd += ["-ss", str(args.video_start)]
    if args.video_end is not None:
        cmd += ["-to", str(args.video_end)]
    cmd += ["-i", args.video, "-map", "1:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-c:a", "aac", "-b:a", "128k"]
    if args.shortest:
        cmd += ["-shortest"]
    cmd += [args.out]
    _log("合成: " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = Path(args.out)
    ok = proc.returncode == 0 and out.exists() and out.stat().st_size > 0
    if not ok:
        return _finish({"ok": False, "mode": "merge", "error": (proc.stderr or "")[-400:]})
    return _finish({"ok": True, "mode": "merge", "output": str(out), "bytes": out.stat().st_size})


def main() -> int:
    p = argparse.ArgumentParser(description="视频号录屏重制：画面 + 系统声音 → mp4")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="同时录制画面与系统声音")
    r.add_argument("--seconds", type=int, default=900, help="录制时长上限（秒）")
    r.add_argument("--dir", required=True, help="输出目录（生成 screen.mkv / audio.wav）")
    r.add_argument("--no-audio", action="store_true", help="只录画面")
    r.add_argument("--device-substr", default="Realtek", help="loopback 设备名匹配子串")
    r.add_argument("--samplerate", type=int, default=48000)
    r.add_argument("--fps", type=int, default=20)
    r.add_argument("--x", type=int, default=0)
    r.add_argument("--y", type=int, default=0)
    r.add_argument("--width", type=int, default=1920)
    r.add_argument("--height", type=int, default=1080)
    r.add_argument("--ffmpeg", default=None)
    r.set_defaults(func=cmd_record)

    d = sub.add_parser("detect-voice", help="输出语音有声区间")
    d.add_argument("--audio", required=True)
    d.add_argument("--raw", action="store_true", help="输入为 s16le 裸 PCM（否则按容器自动识别）")
    d.add_argument("--samplerate", type=int, default=48000)
    d.add_argument("--channels", type=int, default=2)
    d.add_argument("--threshold", type=int, default=35, help="静音判定阈值（dB，数值越小越灵敏）")
    d.add_argument("--min-silence", type=float, default=2.0, help="最短静音时长（秒）")
    d.add_argument("--ffmpeg", default=None)
    d.set_defaults(func=cmd_detect_voice)

    m = sub.add_parser("merge", help="画面 + 音频合成 mp4")
    m.add_argument("--video", required=True)
    m.add_argument("--audio", required=True)
    m.add_argument("-o", "--out", required=True)
    m.add_argument("--audio-start", type=float, default=None)
    m.add_argument("--audio-end", type=float, default=None)
    m.add_argument("--video-start", type=float, default=None)
    m.add_argument("--video-end", type=float, default=None)
    m.add_argument("--shortest", action="store_true", help="以最短流为准")
    m.add_argument("--ffmpeg", default=None)
    m.set_defaults(func=cmd_merge)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
