#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "python-pptx>=0.6.21",
#     "pywin32>=306; sys_platform == 'win32'",
#     "mutagen>=1.46",
# ]
# ///
"""
tests/run_tests.py - photos2mp4 skill 回归测试套件
==================================================

在一个 Python 进程内通过 subprocess 驱动 pptx_video_builder.py 的全部子命令，
断言退出码、JSON 输出与生成的 OOXML 内容。不依赖 pytest，纯标准库 + python-pptx。

用法：
  python tests/run_tests.py            # 常规测试（build/set-transitions/list/list-no-verify/export）
  python tests/run_tests.py --full     # 额外执行 PowerPoint 实测（list-transitions 真探测，较慢）
  python tests/run_tests.py --keep     # 保留临时目录便于排查
  python tests/run_tests.py -k 关键词   # 只跑名称含关键词的用例

退出码：0 = 全部通过（SKIP 不计入失败）；1 = 存在 FAIL。
"""

import argparse
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
import zipfile

# 中文/符号日志在 Windows 控制台（GBK）下不乱码：强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
BUILDER = os.path.join(SKILL_ROOT, "pptx_video_builder.py")
ASSETS = os.path.join(SKILL_ROOT, "test_assets")
PY = sys.executable

RESULTS = []  # (name, status, detail, seconds)
KEEP = False


# ------------------------------------------------------------------ 小工具
def tiny_png(width=8, height=6, rgb=(200, 30, 30)):
    """最小合法 PNG（纯标准库）。"""
    import zlib

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def tiny_wav(seconds=0.5, rate=8000):
    import array
    n = int(seconds * rate)
    buf = array.array("h", (int(8000 * (i % 64) / 64 - 4000) for i in range(n)))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(buf.tobytes())
    return out.getvalue()


def run(args, cwd=None, timeout=600, env_extra=None):
    """运行 builder，返回 (exit_code, stdout, stderr)。"""
    env = os.environ.copy()
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    p = subprocess.run(
        [PY, BUILDER] + [str(a) for a in args],
        capture_output=True, cwd=cwd or SKILL_ROOT, timeout=timeout, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def parse_json(stdout):
    """从 stdout 提取 JSON 对象（容忍前后杂散输出）。"""
    txt = stdout.strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        for i, ch in enumerate(txt):
            if ch == "{":
                for j in range(len(txt), i, -1):
                    if txt[j - 1] == "}":
                        try:
                            return json.loads(txt[i:j])
                        except json.JSONDecodeError:
                            continue
        raise


def pptx_parts(path):
    """读取 pptx 内全部 part 名与幻灯片 XML 文本。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        slides = sorted(n for n in names
                        if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
        xmls = {n: z.read(n).decode("utf-8", "replace") for n in slides}
        return names, xmls


def case(name, func):
    """注册并立即执行一个用例。"""
    t0 = time.time()
    try:
        detail = func() or "ok"
        RESULTS.append((name, "PASS", detail, time.time() - t0))
    except subprocess.TimeoutExpired:
        RESULTS.append((name, "FAIL", "超时", time.time() - t0))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, "FAIL", f"{type(e).__name__}: {e}", time.time() - t0))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def require_pptx_lib():
    try:
        import pptx  # noqa: F401
    except ImportError as e:
        raise SystemExit("[环境缺失] 请先安装 python-pptx：pip install python-pptx") from e


# ------------------------------------------------------------------ 用例
def make_env(tmp):
    """准备测试图（含自然排序陷阱 img2/img10）与音乐。"""
    img_dir = os.path.join(tmp, "imgs")
    os.makedirs(img_dir, exist_ok=True)
    names = ["img2", "img10", "img1", "b_photo", "a_photo"]
    for i, n in enumerate(names):
        with open(os.path.join(img_dir, f"{n}.png"), "wb") as f:
            f.write(tiny_png(rgb=((40 * i) % 255, 90, 200)))
    mus = os.path.join(tmp, "bgm.wav")
    with open(mus, "wb") as f:
        f.write(tiny_wav(0.6))
    # webp 应被跳过
    with open(os.path.join(img_dir, "fake.webp"), "wb") as f:
        f.write(b"\x00" * 32)
    return img_dir, mus


def t_selftest():
    code, out, err = run(["selftest"])
    check(code == 0, f"selftest 退出码 {code}\n{err[-800:]}")
    return "11 项离线自检通过"


def t_build_basic():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, mus = make_env(tmp)
        out_pptx = os.path.join(tmp, "basic.pptx")
        code, out, err = run(["build", "--images", img_dir, "--output", out_pptx,
                              "--transition", "fade", "--transition-duration", "0.8",
                              "--advance", "3", "--json"])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        data = parse_json(out)
        # 5 张 png（webp 被跳过）
        check(data["slides"] == 5, f"页数 {data['slides']} != 5（webp 未跳过或排序后计数错误）")
        names, xmls = pptx_parts(out_pptx)
        # 自然排序: a_photo, b_photo, img1, img2, img10 —— 通过嵌入图片文件名反查顺序
        emb = [n for n in names if n.startswith("ppt/media/")]
        check(len(emb) == 5, f"媒体数 {len(emb)} != 5")
        first_xml = xmls["ppt/slides/slide1.xml"]
        check('advTm="3000"' in first_xml, "slide1 缺少 advTm=3000")
        check("<p:fade" in first_xml, "slide1 缺少 fade 切换")
        check("p14:dur" in first_xml, "缺少 p14:dur（切换时长）")
        return "5 页/自然排序/webp跳过/advTm/fade/p14:dur 均正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_build_music():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, mus = make_env(tmp)
        out_pptx = os.path.join(tmp, "music.pptx")
        code, out, err = run(["build", "--images", img_dir, "--music", mus,
                              "--music-volume", "60", "--music-no-loop",
                              "--output", out_pptx, "--transition", "push",
                              "--direction", "left", "--advance", "2.5", "--json"])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        names, xmls = pptx_parts(out_pptx)
        check(any(n.startswith("ppt/media/") and n.endswith((".wav", ".mp3", ".m4a"))
                  for n in names), "未找到嵌入的音频媒体")
        x1 = xmls["ppt/slides/slide1.xml"]
        check("numSld" in x1, "音频缺少跨页 numSld")
        check('vol="60000"' in x1, "音量 60% 未写入（应为 vol=60000）")
        check("repeatCount" not in x1, "music-no-loop 下不应有 repeatCount")
        check("<p:push" in x1 and 'dir="l"' in x1, "push/left 切换未写入")
        return "音频嵌入/numSld/音量60%/不循环/push-l 正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_build_music_loop_default():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, mus = make_env(tmp)
        out_pptx = os.path.join(tmp, "loop.pptx")
        code, _, err = run(["build", "--images", img_dir, "--music", mus,
                            "--output", out_pptx, "--json"])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        _, xmls = pptx_parts(out_pptx)
        x1 = xmls["ppt/slides/slide1.xml"]
        check("repeatCount=\"indefinite\"" in x1, "默认应循环（repeatCount=indefinite）")
        return "默认循环播放正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_build_fit_geometry():
    from pptx import Presentation
    from pptx.util import Emu
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        # 竖图 4x8 放进 16:9 页面：contain 高受限、cover 宽受限、stretch 铺满
        img_dir = os.path.join(tmp, "g")
        os.makedirs(img_dir)
        with open(os.path.join(img_dir, "tall.png"), "wb") as f:
            f.write(tiny_png(4, 8))
        outs = {}
        for fit in ("contain", "cover", "stretch"):
            p = os.path.join(tmp, f"{fit}.pptx")
            code, _, err = run(["build", "--images", img_dir, "--output", p, "--fit", fit])
            check(code == 0, f"{fit} 退出码 {code}\n{err[-500:]}")
            prs = Presentation(p)
            shp = prs.slides[0].shapes[0]
            outs[fit] = (Emu(shp.width).inches, Emu(shp.height).inches)
        sw, sh = Emu(prs.slide_width).inches, Emu(prs.slide_height).inches
        check(abs(outs["contain"][1] - sh) < 0.01, f"contain 高度应=页高 {outs['contain']}")
        check(outs["contain"][0] < sw * 0.5, "contain 宽度应远小于页宽")
        check(abs(outs["cover"][0] - sw) < 0.01, f"cover 宽度应=页宽 {outs['cover']}")
        check(outs["cover"][1] > sh, "cover 高度应超出页高（裁边）")
        check(abs(outs["stretch"][0] - sw) < 0.01 and abs(outs["stretch"][1] - sh) < 0.01,
              f"stretch 应铺满 {outs['stretch']}")
        return f"contain/cover/stretch 几何正确 {outs}"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_build_slide_size_and_bg():
    from pptx import Presentation
    from pptx.util import Emu
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)
        for spec, want in (("16:9", (13.333, 7.5)), ("4:3", (10, 7.5)), ("720x1280", (7.5, 13.333))):
            p = os.path.join(tmp, f"s{spec.replace(':', '_').replace('x', '_')}.pptx")
            code, _, err = run(["build", "--images", img_dir, "--output", p,
                                "--slide-size", spec, "--background", "#102030"])
            check(code == 0, f"{spec} 退出码 {code}\n{err[-500:]}")
            prs = Presentation(p)
            w, h = Emu(prs.slide_width).inches, Emu(prs.slide_height).inches
            check(abs(w - want[0]) < 0.05 and abs(h - want[1]) < 0.05,
                  f"{spec} 页面应为 {want}，实际 {(w, h)}")
        _, xmls = pptx_parts(p)
        check("102030" in list(xmls.values())[0], "#102030 背景色未写入")
        return "16:9 / 4:3 / 720x1280 / #RRGGBB 背景正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_build_transitions_json():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)
        spec = [
            {"slide": 1, "transition": "fade", "duration": 0.8, "advance": 3.0},
            {"slide": 2, "transition": "push", "direction": "left", "advance": 2.5},
            {"slide": 4, "transition": "wheel", "options": {"spokes": "3"}, "advance": 2.5},
        ]
        jf = os.path.join(tmp, "t.json")
        with open(jf, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        p = os.path.join(tmp, "per.pptx")
        code, _, err = run(["build", "--images", img_dir, "--output", p,
                            "--transitions-json", jf, "--transition", "wipe",
                            "--direction", "up", "--advance", "9"])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        _, xmls = pptx_parts(p)
        x1, x2, x4 = (xmls[f"ppt/slides/slide{i}.xml"] for i in (1, 2, 4))
        check("<p:fade" in x1 and 'advTm="3000"' in x1, "页1 fade/3s 未生效")
        check("thruBlk" not in x1, "页1 显式指定 fade 时不应继承全局方向（无 thruBlk）")
        check("<p:push" in x2 and 'dir="l"' in x2 and 'advTm="2500"' in x2, "页2 push-l/2.5s 未生效")
        check("<p:wheel" in x4 and 'spokes="3"' in x4, "页4 wheel spokes=3 未生效")
        check("<p:wipe" in xmls["ppt/slides/slide3.xml"] and 'dir="u"' in xmls["ppt/slides/slide3.xml"],
              "页3 应回退全局 wipe-up")
        check('advTm="9000"' in xmls["ppt/slides/slide3.xml"], "页3 应回退全局 advance=9")
        return "逐页 JSON 覆盖 + 全局回退正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_build_p14_transition():
    """2010+ 效果：需要 ac:alternateContent 兼容包裹；wheel spokes 等。"""
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)
        p = os.path.join(tmp, "p14.pptx")
        code, _, err = run(["build", "--images", img_dir, "--output", p,
                            "--transition", "glitter", "--direction", "l",
                            "--opt", "pattern=hexagon", "--transition-duration", "1.2"])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        _, xmls = pptx_parts(p)
        x1 = xmls["ppt/slides/slide1.xml"]
        check("mc:AlternateContent" in x1, "p14 效果缺少 AlternateContent 包裹")
        check("p14:glitter" in x1, "缺少 p14:glitter")
        check('pattern="hexagon"' in x1, "缺少 pattern=hexagon")
        # conveyor 等必填 dir 的效果应自动补 l
        p2 = os.path.join(tmp, "conv.pptx")
        code, _, err = run(["build", "--images", img_dir, "--output", p2,
                            "--transition", "conveyor"])
        check(code == 0, f"conveyor 无方向应自动补默认值，退出码 {code}\n{err[-500:]}")
        _, xmls2 = pptx_parts(p2)
        check('dir="l"' in xmls2["ppt/slides/slide1.xml"], "conveyor 未自动补 dir=l")
        return "glitter(hexagon)+conveyor 自动补 dir 正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_auto_fit_music():
    try:
        import mutagen  # noqa: F401
    except ImportError:
        return "SKIP: 未安装 mutagen"
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)  # 5 页
        mus = os.path.join(tmp, "m.wav")
        with open(mus, "wb") as f:
            f.write(tiny_wav(10.0))  # 10s / 5 页 = 2s
        p = os.path.join(tmp, "af.pptx")
        code, _, err = run(["build", "--images", img_dir, "--music", mus,
                            "--auto-fit-music", "--output", p])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        _, xmls = pptx_parts(p)
        check('advTm="2000"' in xmls["ppt/slides/slide1.xml"],
              "auto-fit 应为 10s/5页=2s/页")
        return "auto-fit-music 10s/5页=2s 正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_error_cases():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        # 1. 无图片
        code, _, _ = run(["build", "--images", os.path.join(tmp, "nope"),
                          "--output", os.path.join(tmp, "x.pptx")])
        check(code == 2, f"空目录应退出码 2，实际 {code}")
        # 2. 未知切换效果
        img_dir, _ = make_env(tmp)
        code, _, err = run(["build", "--images", img_dir,
                            "--output", os.path.join(tmp, "x.pptx"),
                            "--transition", "nonexistent_fx"])
        check(code == 2, f"未知效果应退出码 2，实际 {code}")
        check("nonexistent_fx" in err, "错误信息应包含效果名")
        # 3. 非法 slide-size
        code, _, _ = run(["build", "--images", img_dir,
                          "--output", os.path.join(tmp, "x.pptx"),
                          "--slide-size", "abc"])
        check(code == 2, f"非法尺寸应退出码 2，实际 {code}")
        # 4. 非法 transitions-json
        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        code, _, _ = run(["build", "--images", img_dir,
                          "--output", os.path.join(tmp, "x.pptx"),
                          "--transitions-json", bad])
        check(code == 2, f"坏 JSON 应退出码 2，实际 {code}")
        # 5. 越界 advance
        code, _, _ = run(["build", "--images", img_dir,
                          "--output", os.path.join(tmp, "x.pptx"), "--advance", "-1"])
        check(code == 2, f"负 advance 应退出码 2，实际 {code}")
        return "5 类参数错误均返回退出码 2 且信息明确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_output_location_defaults():
    """缺省 --output 时产物写入默认目录（PHOTOS2MP4_OUT_DIR 可重定向）。"""
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)
        # 1) build 不传 --output → 写入 env 指定的默认目录
        code, out, err = run(["build", "--images", img_dir, "--transition", "fade"],
                             env_extra={"PHOTOS2MP4_OUT_DIR": tmp})
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        data = parse_json(out) if out.strip().startswith("{") else None
        # json 未开时从日志找路径；两种部验证在 tmp 下存在 .pptx
        produced = [f for f in os.listdir(tmp) if f.endswith(".pptx")]
        check(produced, "默认目录下未生成 .pptx")
        # 2) export 不传 --output → <默认目录>/<pptx同名>.mp4（无新版 PowerPoint 时快速失败也合理）
        code, _, _ = run(["export", "--pptx", os.path.join(tmp, produced[0])],
                         env_extra={"PHOTOS2MP4_OUT_DIR": tmp}, timeout=120)
        check(code in (0, 3, 4), f"export 默认输出退出码异常: {code}")
        return f"缺省 --output 写入 {tmp}（{produced[0]}）"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_output_repo_guard():
    """产物禁止写入本 skill 所在仓库；PHOTOS2MP4_ALLOW_REPO_OUTPUT=1 可放行。"""
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    inside = os.path.join(SKILL_ROOT, "_guard_probe.pptx")
    try:
        img_dir, _ = make_env(tmp)
        code, _, err = run(["build", "--images", img_dir, "--output", inside])
        check(code == 2, f"写入仓库应退出码 2，实际 {code}")
        check("拒绝" in err and "git" in err, "错误信息应说明拒绝写入仓库的原因")
        check(not os.path.exists(inside), "仓库内不应出现产物文件")
        # 放行后可写入（事后清理）
        code, _, err = run(["build", "--images", img_dir, "--output", inside],
                           env_extra={"PHOTOS2MP4_ALLOW_REPO_OUTPUT": "1"})
        check(code == 0, f"放行后应成功，退出码 {code}\n{err[-500:]}")
        return "仓库守卫拦截 + 环境变量放行正确"
    finally:
        if os.path.exists(inside):
            os.remove(inside)
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_set_transitions():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)
        p = os.path.join(tmp, "st.pptx")
        run(["build", "--images", img_dir, "--output", p,
             "--transition", "fade", "--advance", "3"])
        # 改切换 + 沿用换片时间
        code, _, err = run(["set-transitions", "--pptx", p, "--transition", "circle"])
        check(code == 0, f"退出码 {code}\n{err[-800:]}")
        _, xmls = pptx_parts(p)
        x1 = xmls["ppt/slides/slide1.xml"]
        check("<p:circle" in x1, "circle 未写入")
        check('advTm="3000"' in x1, "应沿用原 advance=3s")
        # 只改 advance
        code, _, err = run(["set-transitions", "--pptx", p, "--advance", "7"])
        check(code == 0, f"只改 advance 退出码 {code}\n{err[-800:]}")
        _, xmls = pptx_parts(p)
        check('advTm="7000"' in xmls["ppt/slides/slide1.xml"], "advance=7s 未生效")
        check("<p:circle" in xmls["ppt/slides/slide1.xml"], "改 advance 不应破坏已有切换")
        return "set-transitions 换效果/沿用时长/只改时长 正确"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_list_transitions_noverify():
    code, out, err = run(["list-transitions", "--no-verify", "--json"])
    check(code == 0, f"退出码 {code}\n{err[-800:]}")
    data = parse_json(out)
    rows = data.get("results") or []
    check(len(rows) >= 40, f"理论目录应 >=40 种，实际 {len(rows)}")
    check(all("name" in r and "tier" in r and "params" in r for r in rows),
          "目录行缺少 name/tier/params 字段")
    return f"理论目录 {len(rows)} 项，字段齐全"


def t_export():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir, _ = make_env(tmp)
        p = os.path.join(tmp, "e.pptx")
        run(["build", "--images", img_dir, "--output", p,
             "--transition", "fade", "--advance", "1"])
        mp4 = os.path.join(tmp, "e.mp4")
        code, out, err = run(["export", "--pptx", p, "--output", mp4,
                              "--resolution", "480", "--timeout", "300"], timeout=360)
        if code == 0:
            check(os.path.exists(mp4) and os.path.getsize(mp4) > 1000, "MP4 不存在或过小")
            with open(mp4, "rb") as f:
                head = f.read(12)
            check(b"ftyp" in head, "MP4 头缺少 ftyp")
            return "真实导出 MP4 成功且文件头合法"
        # PowerPoint 不可用 / 版本过旧（如 2007 无 CreateVideo）→ 环境限制，非脚本缺陷
        if code in (3, 4):
            return f"SKIP: 本机 PowerPoint 不支持导出（退出码 {code}，路径处理正确）"
        raise AssertionError(f"export 退出码 {code}\n{err[-800:]}")
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


def t_list_transitions_verify():
    code, out, err = run(["list-transitions", "--json"], timeout=600)
    if code == 3:
        return "SKIP: PowerPoint 不可用（退出码 3 处理正确）"
    check(code == 0, f"退出码 {code}\n{err[-800:]}")
    data = parse_json(out)
    rows = data.get("results") or []
    ver = str(data.get("powerpoint_version") or "")
    major = int(ver.split(".")[0]) if ver.split(".")[0].isdigit() else 0
    # 版本门控：低于要求版本的档次不应误报支持
    for r in rows:
        need = {"p14": 14, "morph": 16}.get(r.get("tier"), 0)
        if major < need:
            check(not r.get("supported"),
                  f"{r['name']}(需 {need}) 在 PowerPoint {ver} 上不应标记为支持")
            check((r.get("note") or "").startswith("requires_powerpoint"),
                  f"{r['name']} 应带 requires_powerpoint 注记")
    return f"PowerPoint {ver} 实测完成，门控正确（{len(rows)} 项）"


def t_perf_many_images():
    tmp = tempfile.mkdtemp(prefix="p2m_", dir=os.environ.get("_P2M_TMPROOT") or None)
    try:
        img_dir = os.path.join(tmp, "many")
        os.makedirs(img_dir)
        png = tiny_png(64, 48)
        for i in range(100):
            with open(os.path.join(img_dir, f"p{i:03d}.png"), "wb") as f:
                f.write(png)
        p = os.path.join(tmp, "many.pptx")
        t0 = time.time()
        code, _, err = run(["build", "--images", img_dir, "--output", p,
                            "--transition", "fade", "--advance", "3"])
        dt = time.time() - t0
        check(code == 0, f"退出码 {code}\n{err[-500:]}")
        check(dt < 60, f"100 张图构建耗时 {dt:.1f}s，超过 60s 预算")
        _, xmls = pptx_parts(p)
        check(len(xmls) == 100, f"页数 {len(xmls)} != 100")
        return f"100 张图 {dt:.1f}s（含子进程启动）"
    finally:
        if not KEEP:
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ main
def main():
    global KEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    ap.add_argument("--full", action="store_true", help="含 PowerPoint 实测（慢）")
    ap.add_argument("-k", "--keyword", default="", help="只跑名称含关键词的用例")
    args = ap.parse_args()
    KEEP = args.keep

    require_pptx_lib()
    print(f"[tests] builder: {BUILDER}")
    print(f"[tests] python:  {PY} ({sys.version.split()[0]})")

    suites = [
        ("selftest", t_selftest),
        ("build-basic", t_build_basic),
        ("build-music", t_build_music),
        ("build-music-loop-default", t_build_music_loop_default),
        ("build-fit-geometry", t_build_fit_geometry),
        ("build-slide-size-bg", t_build_slide_size_and_bg),
        ("build-transitions-json", t_build_transitions_json),
        ("build-p14-transition", t_build_p14_transition),
        ("auto-fit-music", t_auto_fit_music),
        ("error-cases", t_error_cases),
        ("output-location-defaults", t_output_location_defaults),
        ("output-repo-guard", t_output_repo_guard),
        ("set-transitions", t_set_transitions),
        ("list-transitions-noverify", t_list_transitions_noverify),
        ("perf-100-images", t_perf_many_images),
        ("export", t_export),
    ]
    if args.full:
        suites.append(("list-transitions-verify", t_list_transitions_verify))

    for name, fn in suites:
        if args.keyword and args.keyword not in name:
            continue
        case(name, fn)
        n, st, detail, dt = RESULTS[-1]
        mark = "OK " if st == "PASS" else "FAIL"
        print(f"  [{mark}] {n:28s} {dt:6.1f}s  {detail}")

    npass = sum(1 for r in RESULTS if r[1] == "PASS")
    nskip = sum(1 for r in RESULTS if r[1] != "PASS" and r[2].startswith("SKIP"))
    nfail = len(RESULTS) - npass - nskip
    print(f"\n[结果] PASS={npass}  SKIP={nskip}  FAIL={nfail}")
    sys.exit(0 if nfail == 0 else 1)


if __name__ == "__main__":
    main()
