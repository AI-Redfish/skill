#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_test_assets.py - 生成测试素材（零依赖，纯 Python 标准库）

在 ./test_assets/ 下生成：
  images/  6 张不同尺寸/颜色的 PNG（用于测试 contain/cover/stretch 与排序）
  bgm.wav  约 26 秒的简单旋律（WAV，用于测试背景音乐跨页循环）
  （transitions.json 由 AI 直接提供，不在此生成）

用法：  python make_test_assets.py
"""

import array
import math
import os
import struct
import wave
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_assets")


# ---------------------------------------------------------------- PNG 生成
def _png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def make_pattern_png(width, height, base, accent):
    """垂直渐变 + 中部白色横带，返回 PNG 字节。"""
    band_top = int(height * 0.45)
    band_h = max(8, height // 12)
    raw_rows = []
    for y in range(height):
        t = y / max(1, height - 1)
        rgb = tuple(int(base[c] + (accent[c] - base[c]) * t) for c in range(3))
        if band_top <= y < band_top + band_h:
            rgb = (246, 246, 246)
        raw_rows.append(b"\x00" + bytes(rgb) * width)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows), 6))
            + _png_chunk(b"IEND", b""))


IMAGES = [
    # (文件名,            宽,    高,   渐变起始色,      渐变结束色)
    ("img1_red_1280x720.png",    1280,  720, (120, 10, 10),  (220, 60, 50)),
    ("img2_green_800x600.png",    800,  600, (10, 100, 30),  (60, 200, 90)),
    ("img3_blue_500x500.png",     500,  500, (15, 40, 130),  (70, 120, 230)),
    ("img4_orange_1920x1080.png", 1920, 1080, (180, 90, 0),  (250, 180, 40)),
    ("img5_purple_600x1000.png",  600, 1000, (80, 20, 120),  (170, 90, 220)),
    ("img6_teal_1600x900.png",   1600,  900, (0, 90, 95),    (50, 190, 190)),
]


# ---------------------------------------------------------------- WAV 生成
def make_melody_wav(path, note_sec=0.4, rate=22050, loops=4):
    """简单五声音阶旋律（每音符带淡入淡出防爆音）。"""
    notes = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 880.00, 783.99,
             659.25, 587.33, 523.25, 659.25, 783.99, 1046.50, 783.99, 659.25]
    fade = max(1, int(0.03 * rate))
    frames = array.array("h")
    for freq in notes * loops:
        n = int(rate * note_sec)
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            frames.append(int(9000 * env * math.sin(2 * math.pi * freq * i / rate)))
    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(frames.tobytes())
    w.close()
    return len(frames) / rate


def main():
    img_dir = os.path.join(OUT_DIR, "images")
    os.makedirs(img_dir, exist_ok=True)
    for name, w, h, base, accent in IMAGES:
        p = os.path.join(img_dir, name)
        with open(p, "wb") as f:
            f.write(make_pattern_png(w, h, base, accent))
        print(f"[OK] {p}")

    wav_path = os.path.join(OUT_DIR, "bgm.wav")
    dur = make_melody_wav(wav_path)
    print(f"[OK] {wav_path}  ({dur:.1f}s)")

    print(f"\n素材已就绪。下一步示例：")
    print(f'  python pptx_video_builder.py selftest')
    print(f'  python pptx_video_builder.py build --images "{img_dir}" '
          f'--music "{wav_path}" --output "{OUT_DIR}\\demo.pptx" '
          f'--transition fade --transition-duration 0.8 --advance 3')


if __name__ == "__main__":
    main()
