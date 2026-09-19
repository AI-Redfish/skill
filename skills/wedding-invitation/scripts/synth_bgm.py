#!/usr/bin/env python3
"""synth_bgm.py — 为 H5 演示视频合成动森风背景音乐音轨(wav)。

用途: 纯标准库复刻页面 WebAudio 合成逻辑(木琴主旋律+三角波贝斯+hi-hat+翻页 blip),
      与 record_page.py 产出的 timeline.json 对齐, 供 ffmpeg 混流。
用法: python3 synth_bgm.py --timeline timeline.json --out bgm.wav
      python3 synth_bgm.py --music-start 2.0 --blips 2.0,7,13 --duration 39 --out bgm.wav
依赖: Python 3.9+ 纯标准库。
输出: JSON 到 stdout(status/path/duration_s/peak)；日志到 stderr。
退出码: 0=成功 1=写入失败 2=参数错误。
"""
from __future__ import annotations
import argparse
import json
import math
import struct
import sys
import wave
from pathlib import Path

SR = 44100
MELODY = [76,79,84,79, 76,79,0,0,  81,76,72,76, 81,0,79,0,
          77,81,84,81, 77,81,0,0,  79,83,86,83, 79,0,76,0,
          76,79,84,79, 81,79,76,74, 72,76,81,79, 76,74,72,0,
          77,79,81,79, 83,0,86,0,   84,0,0,0,   72,74,76,79]
BASS = [[48,55],[45,52],[41,48],[43,50]] * 2


def midi_f(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


class Mixer:
    """事件驱动的采样叠加器。"""

    def __init__(self, total: float):
        self.n = int(SR * total)
        self.buf = [0.0] * self.n

    def _add(self, t0: float, freq: float, vol: float, dur: float,
             wave_type: str) -> None:
        i0, n = int(t0 * SR), int(dur * SR)
        if i0 >= self.n:
            return
        n = min(n, self.n - i0)
        two_pi_f = 2 * math.pi * freq
        for i in range(n):
            t = i / SR
            ph = two_pi_f * t
            if wave_type == "sine":
                s = math.sin(ph)
            elif wave_type == "tri":
                s = (2 / math.pi) * math.asin(math.sin(ph))
            else:
                s = 1.0 if math.sin(ph) >= 0 else -1.0
            env = vol * (t / 0.006) if t < 0.006 else vol * math.exp(-5.5 * (t - 0.006))
            self.buf[i0 + i] += s * env

    def marimba(self, t: float, midi: int, vol: float = 0.15) -> None:
        self._add(t, midi_f(midi), vol, 0.60, "sine")
        self._add(t, midi_f(midi) * 3.01, vol * 0.13, 0.13, "sine")

    def bass(self, t: float, midi: int) -> None:
        self._add(t, midi_f(midi), 0.13, 0.55, "tri")

    def hat(self, t: float) -> None:
        self._add(t, 7200, 0.016, 0.035, "square")

    def blip(self, t: float) -> None:
        self._add(t, 1046, 0.12, 0.06, "sine")
        self._add(t + 0.055, 1568, 0.12, 0.10, "sine")


def render(total: float, music_start: float, blips: list[float],
           fade_from: float, tempo: int, volume: float) -> tuple[list[int], float]:
    mx = Mixer(total)
    eighth = 60 / tempo / 2
    t0 = music_start
    while t0 < fade_from:
        for i in range(64):
            t = t0 + i * eighth
            if t >= fade_from:
                break
            bar, pos = divmod(i, 8)
            if MELODY[i]:
                mx.marimba(t, MELODY[i])
            if pos == 0:
                mx.bass(t, BASS[bar][0])
            if pos == 4:
                mx.bass(t, BASS[bar][1])
            if pos % 2 == 0:
                mx.hat(t)
        t0 += 64 * eighth
    for b in blips:
        mx.blip(b)
    fi = int(fade_from * SR)
    for i in range(fi, mx.n):
        mx.buf[i] *= max(0.0, 1 - (i - fi) / max(1, mx.n - fi))
    peak = max((abs(x) for x in mx.buf), default=1.0) or 1.0
    gain = volume / max(peak, volume)
    return [int(max(-1.0, min(1.0, x * gain)) * 32767) for x in mx.buf], peak


def main() -> None:
    ap = argparse.ArgumentParser(description="合成动森风 BGM wav")
    ap.add_argument("--timeline", help="record_page.py 产出的 timeline.json")
    ap.add_argument("--music-start", type=float, default=2.0, help="BGM 起播秒(默认 2.0)")
    ap.add_argument("--blips", default="", help="逗号分隔的翻页音效秒, 如 2.3,7.4")
    ap.add_argument("--duration", type=float, default=39.0, help="总时长秒(默认 39)")
    ap.add_argument("--tempo", type=int, default=108)
    ap.add_argument("--volume", type=float, default=0.9)
    ap.add_argument("--out", default="bgm.wav")
    a = ap.parse_args()

    music_start, blips, total = a.music_start, [], a.duration
    fade_from = max(0.0, total - 1.0)
    if a.timeline:
        tp = Path(a.timeline)
        if not tp.is_file():
            json.dump({"status": "error", "error": {"message": f"timeline 不存在: {a.timeline}"}},
                      sys.stdout, ensure_ascii=False)
            sys.exit(2)
        tl = json.loads(tp.read_text(encoding="utf-8"))
        music_start = float(tl.get("music", music_start))
        blips = [float(x) for x in tl.get("blips", [])]
        total = float(tl.get("end", total)) + 1.2
        fade_from = max(0.0, float(tl.get("end", total)) - 0.5)
    if a.blips:
        blips = [float(x) for x in a.blips.split(",") if x.strip()]

    samples, peak = render(total, music_start, blips, fade_from, a.tempo, a.volume)
    try:
        with wave.open(a.out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(struct.pack("<%dh" % len(samples), *samples))
    except OSError as e:
        json.dump({"status": "error", "error": {"message": f"wav 写入失败: {e}"}},
                  sys.stdout, ensure_ascii=False)
        sys.exit(1)
    json.dump({"status": "ok", "path": str(Path(a.out).resolve()),
               "duration_s": round(len(samples) / SR, 2), "peak": round(peak, 3)},
              sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
