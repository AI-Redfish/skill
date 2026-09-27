#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""photo_order.py — 内容感知的照片智能排序（配合 pptx_video_builder.py 使用）

分析照片的 EXIF 拍摄时间、色彩分布（HSV 色相直方图）、亮度、感知哈希（dHash）
与横竖构图，把照片划分为"场景"（同一时间段/同机位的连拍），再按视觉相似度
编排场景先后顺序，使幻灯片视频的相邻照片切换具备色彩与叙事上的衔接性，
避免突兀跳变。

流程:
  1. 提取特征: EXIF 时间 / dHash / 12 桶色相分布 / 亮度 / 饱和度 / 横竖构图
  2. 场景划分: 按拍摄时间排序, 时间间隔 > --time-gap 秒即切分为新场景
     （连拍/同场景照片天然保持时间顺序, 保证组内衔接）
  3. 场景编排: 以"开场分"（亮度×饱和度×分辨率）选起始场景, 之后贪心最近邻
     串联其余场景（距离 = 场景间边界照片的色相差 + 亮度差 + dHash 汉明距离,
     并对横竖构图跳变施加轻微惩罚）
  4. 输出顺序 JSON; 可选 --staging-dir 生成 NNN_前缀 硬链接/副本目录
     （pptx_video_builder.py 对图片强制自然排序, 用暂存目录即可精确控制顺序）;
     可选 --contact-sheet-dir 输出带编号缩略图拼版, 供人工/AI 复核内容

用法:
  uv run photo_order.py --images <照片目录> --json
  uv run photo_order.py --images <照片目录> --staging-dir <目录> --json
  uv run photo_order.py --images <照片目录> --contact-sheet-dir <目录> --json

产物约定与 pptx_video_builder.py 一致: 不指定输出目录时不写任何文件;
--staging-dir/--contact-sheet-dir 按用户指定路径创建。
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def log(msg):
    print(f"[信息] {msg}", file=sys.stderr)


def natural_key(s):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def collect_images(root):
    if os.path.isfile(root):
        return [root]
    out = []
    for name in sorted(os.listdir(root), key=natural_key):
        p = os.path.join(root, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in IMAGE_EXTS:
            out.append(p)
    return out


def dhash(im, size=8):
    g = im.convert("L").resize((size + 1, size))
    px = list(g.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (1 if px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] else 0)
    return bits


def exif_time(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = getattr(im, "_getexif", lambda: None)() or {}
            for tag in (36867, 36868, 306):  # DateTimeOriginal / DateTimeDigitized / DateTime
                v = ex.get(tag)
                if v:
                    return datetime.strptime(v[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    return None


def extract_features(paths):
    from PIL import Image
    feats = []
    for p in paths:
        try:
            with Image.open(p) as im:
                im.load()
                w, h = im.size
                small = im.convert("RGB").resize((64, 64))
                hsv = small.convert("HSV")
                data = list(hsv.getdata())
                dh = dhash(small)
        except Exception as e:
            log(f"[警告] 跳过无法读取的图片 {p}: {e}")
            continue
        n = len(data)
        hue = [0] * 12
        sat_sum = val_sum = 0
        for H, S, V in data:
            if S > 30:
                hue[H * 12 // 256] += 1
            sat_sum += S
            val_sum += V
        t = exif_time(p)
        feats.append({
            "path": p,
            "file": os.path.basename(p),
            "time": t,
            "orient": "L" if w >= h else "P",
            "w": w,
            "h": h,
            "dhash": dh,
            "hue": [x / n for x in hue],
            "brightness": val_sum / n / 255,
            "saturation": sat_sum / n / 255,
        })
    return feats


def hamming(a, b):
    return bin((a or 0) ^ (b or 0)).count("1")


def photo_dist(a, b, orient_penalty=0.5):
    hue_l1 = sum(abs(x - y) for x, y in zip(a["hue"], b["hue"]))  # 0~2
    bright = abs(a["brightness"] - b["brightness"])               # 0~1
    dh = hamming(a["dhash"], b["dhash"]) / 64.0                   # 0~1
    orient = 0.0 if a["orient"] == b["orient"] else orient_penalty
    return hue_l1 + bright + dh + orient


def scene_dist(sa, sb):
    """场景间距离 = 边界照片两两距离的最小值（衔接的是相邻两张）"""
    return min(photo_dist(a, b) for a in sa for b in sb)


def split_scenes(feats, time_gap):
    scenes = [[feats[0]]]
    for prev, cur in zip(feats, feats[1:]):
        gap_ok = prev["time"] and cur["time"] and (cur["time"] - prev["time"]).total_seconds() <= time_gap
        if gap_ok:
            scenes[-1].append(cur)
        else:
            scenes.append([cur])
    return scenes


def order_scenes(scenes):
    def opener_score(s):
        return sum(f["brightness"] * 0.6 + f["saturation"] * 0.4 for f in s) / len(s)

    remaining = list(range(len(scenes)))
    start = max(remaining, key=lambda i: opener_score(scenes[i]))
    chain = [start]
    remaining.remove(start)
    while remaining:
        last = chain[-1]
        nxt = min(remaining, key=lambda i: scene_dist(scenes[last], scenes[i]))
        chain.append(nxt)
        remaining.remove(nxt)
    return chain


def build_sheets(feats, order, out_dir, per_sheet=22, cols=6, cell=300):
    from PIL import Image, ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    items = [next(f for f in feats if f["file"] == name) for name in order]
    for si in range(0, len(items), per_sheet):
        chunk = items[si:si + per_sheet]
        rows_n = (len(chunk) + cols - 1) // cols
        board = Image.new("RGB", (cols * cell, rows_n * (cell + 26)), (20, 20, 20))
        d = ImageDraw.Draw(board)
        for k, f in enumerate(chunk):
            im = Image.open(f["path"]).convert("RGB")
            im.thumbnail((cell - 6, cell - 6))
            x, y = (k % cols) * cell, (k // cols) * (cell + 26)
            board.paste(im, (x + 3, y + 3))
            d.text((x + 8, y + cell - 2), f"#{si + k + 1} {f['file'][:24]}", fill=(255, 255, 80))
        board.save(os.path.join(out_dir, f"order_sheet{si // per_sheet + 1}.jpg"), quality=88)


def main():
    ap = argparse.ArgumentParser(description="内容感知的照片智能排序")
    ap.add_argument("--images", required=True, help="照片目录或单个文件")
    ap.add_argument("--time-gap", type=float, default=300.0,
                    help="场景切分的时间间隔阈值（秒），默认 300")
    ap.add_argument("--staging-dir", help="输出 NNN_前缀 硬链接/副本目录（供 pptx_video_builder 精确按此顺序构建）")
    ap.add_argument("--contact-sheet-dir", help="输出带最终顺序编号的缩略图拼版目录")
    ap.add_argument("--from-order", help="跳过自动分析，按给定顺序文件构建（JSON 数组，或含 order 字段的对象；"
                                              "典型用法：先自动分析生成 order，人工/AI 复核拼版微调后再传入）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果到 stdout")
    args = ap.parse_args()

    if not os.path.exists(args.images):
        print(f"[错误] 路径不存在: {args.images}", file=sys.stderr)
        sys.exit(2)

    paths = collect_images(args.images)
    if not paths:
        print("[错误] 未找到图片", file=sys.stderr)
        sys.exit(2)
    log(f"共 {len(paths)} 张图片, 提取特征中...")
    feats = extract_features(paths)
    if not feats:
        print("[错误] 没有可用的图片特征", file=sys.stderr)
        sys.exit(1)

    if args.from_order:
        with open(args.from_order, encoding="utf-8") as fh:
            data = json.load(fh)
        order = data if isinstance(data, list) else data["order"]
        known = {f["file"] for f in feats}
        missing = [x for x in order if x not in known]
        if missing:
            print(f"[错误] 顺序文件中包含不存在的图片: {missing[:5]}", file=sys.stderr)
            sys.exit(2)
        result = {"count": len(order), "order": order, "from_order": args.from_order}
    else:
        # 组内时间排序（EXIF 缺失时保持自然文件名顺序）
        have_time = [f for f in feats if f["time"]]
        if len(have_time) >= len(feats) * 0.8:
            feats.sort(key=lambda f: (f["time"] or datetime.max, natural_key(f["file"])))
        scenes = split_scenes(feats, args.time_gap)
        log(f"按拍摄时间划分出 {len(scenes)} 个场景: {[len(s) for s in scenes]}")
        chain = order_scenes(scenes)
        log(f"场景编排顺序: {' -> '.join(str(i + 1) for i in chain)}")

        order = []
        for rank, si in enumerate(chain, 1):
            for f in scenes[si]:
                order.append(f["file"])

        result = {
            "count": len(order),
            "scenes": [{"seq": rank, "files": [f["file"] for f in scenes[si]]}
                       for rank, si in enumerate(chain, 1)],
            "order": order,
        }

    if args.staging_dir:
        os.makedirs(args.staging_dir, exist_ok=True)
        by_file = {f["file"]: f["path"] for f in feats}
        made = 0
        for i, name in enumerate(order, 1):
            dst = os.path.join(args.staging_dir, f"{i:03d}_{name}")
            if os.path.exists(dst):
                os.remove(dst)
            try:
                os.link(by_file[name], dst)
            except OSError:
                shutil.copy2(by_file[name], dst)
            made += 1
        result["staging_dir"] = os.path.abspath(args.staging_dir)
        result["staged"] = made
        log(f"已生成暂存目录: {args.staging_dir}（{made} 张, NNN_ 前缀保序）")

    if args.contact_sheet_dir:
        build_sheets(feats, order, args.contact_sheet_dir)
        result["contact_sheet_dir"] = os.path.abspath(args.contact_sheet_dir)
        log(f"已生成缩略图拼版: {args.contact_sheet_dir}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for i, name in enumerate(order, 1):
            print(f"{i:03d}  {name}")


if __name__ == "__main__":
    main()
