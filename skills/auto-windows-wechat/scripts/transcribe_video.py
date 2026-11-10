#!/usr/bin/env python3
"""transcribe_video.py — 本地语音转写（faster-whisper，uv --with 按需拉起，无 API key）。

用法:
    uv run --with faster-whisper scripts/transcribe_video.py <video.mp4> \
        [--model small] [--language zh] [-o 输出目录] [--name 自定义文件名]

产物: <stem>.txt（逐段纯文本）与 <stem>.srt（带时间轴），默认与视频同目录。
stdout 末行 JSON {"output": {"ok": true, "txt": ..., "srt": ..., "audio_sec": ...}}；
进度诊断 stderr（[asr] 前缀）。

模型: tiny/base/small/medium/large-v3，默认 small（中文质量/速度平衡点；
追求更准用 medium，CPU 明显变慢）。模型首次使用时从 HuggingFace 下载并缓存
（small≈460MB），之后离线可用。依赖包由 uv --with 自动解析安装，无需预装。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

LOG = "[asr]"

# 管道输出统一 UTF-8：Windows 下 Python 写管道默认 ANSI 代码页，中文会乱码。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fail(error: str) -> int:
    print(json.dumps({"output": {"ok": False, "error": error}}, ensure_ascii=False))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="视频/音频本地转写（faster-whisper）")
    ap.add_argument("video", help="视频或音频文件路径")
    ap.add_argument("--model", default="small",
                    choices=["tiny", "base", "small", "medium", "large-v3"])
    ap.add_argument("--language", default="zh",
                    help="语言代码（zh/en/…），传 auto 则自动检测")
    ap.add_argument("-o", "--outdir", help="输出目录（默认与视频同目录）")
    ap.add_argument("--name", help="输出文件名主干（默认与视频同名）")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.is_file():
        return fail(f"文件不存在: {video}")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return fail("缺少 faster-whisper；请用 uv run --with faster-whisper 运行本脚本")

    outdir = Path(args.outdir) if args.outdir else video.parent
    outdir.mkdir(parents=True, exist_ok=True)
    stem = args.name or video.stem
    txt_path = outdir / f"{stem}.txt"
    srt_path = outdir / f"{stem}.srt"

    t0 = time.time()
    print(f"{LOG} 加载模型 {args.model}（首次使用会下载并缓存）…", file=sys.stderr)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print(f"{LOG} 转写中：{video.name}", file=sys.stderr)
    segments, info = model.transcribe(
        str(video),
        language=None if args.language in ("auto", "", None) else args.language,
        vad_filter=True,
    )

    n = 0
    srt_idx = 0
    with txt_path.open("w", encoding="utf-8") as ft, \
            srt_path.open("w", encoding="utf-8") as fs:
        for seg in segments:
            n += 1
            text = seg.text.strip()
            if not text:
                continue
            srt_idx += 1
            ft.write(text + "\n")
            fs.write(f"{srt_idx}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{text}\n\n")
            if srt_idx % 20 == 0:
                print(f"{LOG} 已转写 {srt_idx} 段（音频 {seg.end:.0f}/{info.duration:.0f} 秒）",
                      file=sys.stderr)

    print(f"{LOG} 完成：{srt_idx} 段 / 音频 {info.duration:.0f} 秒 / "
          f"耗时 {time.time() - t0:.0f}s", file=sys.stderr)
    print(json.dumps({"output": {
        "ok": True, "txt": str(txt_path), "srt": str(srt_path),
        "segments": srt_idx, "audio_sec": round(info.duration, 1),
        "model": args.model, "elapsed_sec": round(time.time() - t0, 1),
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
