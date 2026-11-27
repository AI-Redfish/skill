#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["mss", "opencv-python", "numpy", "pyautogui", "pillow"]
# ///
"""Boss直聘纯视觉投递（无痕模式）：屏幕截图定位 + OS 级鼠标仿真，零 CDP / 零浏览器连接。

原理：mss 截屏找卡片行与按钮（模板匹配），pyautogui 仿真真手移动/点击（isTrusted=true），
浏览器与风控无法区分脚本鼠标与真人。适用于风控激活期与日常 Chrome。

用法：
  uv run boss_apply_visual.py --calibrate          # 首次校准：框选按钮模板与列表布局
  uv run boss_apply_visual.py --dry-run --limit 3  # 只定位不点击，验证匹配
  uv run boss_apply_visual.py --label "杭州·实施"   # 正式投递当前屏可见卡片

节奏（均衡档）：卡间停顿 2.5~6s，每 8~12 张插入一次 8~15s 长停顿。
产物：.agents/out/YYYYMMDD/auto-browser-boss/apply-YYYYMMDD.jsonl（YYYYMMDD 为当天日期目录）（与接管模式共用，额度共享）。
安全阀：连续 2 张定位失败即停；鼠标甩到屏幕左上角可紧急中断（pyautogui FAILSAFE）。
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

# DPI 感知必须在截屏/鼠标/窗口库之前设置，保证坐标与像素一致
import ctypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2  # noqa: E402
import mss  # noqa: E402
import numpy as np  # noqa: E402
import pyautogui  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_common as bc  # noqa: E402

pyautogui.FAILSAFE = True   # 鼠标甩左上角 = 紧急停止
pyautogui.PAUSE = 0

TPL_DIR = bc.skill_root() / "assets" / "templates"
LAYOUT_JSON = TPL_DIR / "layout.json"
MATCH_TH = 0.82          # 模板匹配阈值
ROW_WHITE_LEVEL = 249    # 行检测：灰度 >= 此值算白色像素
ROW_WHITE_FRAC = 0.40    # 行检测：卡片行白色像素占比下限
ROW_MIN_H = 55           # 卡片行最小高度（px）
ROW_MAX_H = 220          # 卡片行最大高度（px）


# ---------------- 截屏 ----------------

def grab_bgr() -> np.ndarray:
    """主屏截屏，返回 BGR ndarray（物理像素）。"""
    with mss.mss() as sct:
        img = np.asarray(sct.grab(sct.monitors[1]))
    return img[:, :, :3].copy()


# ---------------- 模板匹配 ----------------

def match_tpl(screen_bgr, tpl_bgr, region=None, thresh=MATCH_TH):
    """在 screen（或 region=(x1,y1,x2,y2)）中找模板最佳命中，返回中心坐标+得分或 None。"""
    if region is None:
        img, ox, oy = screen_bgr, 0, 0
    else:
        x1, y1, x2, y2 = region
        img, ox, oy = screen_bgr[y1:y2, x1:x2], x1, y1
    th, tw = tpl_bgr.shape[:2]
    if img.shape[0] < th or img.shape[1] < tw:
        return None
    res = cv2.matchTemplate(img, tpl_bgr, cv2.TM_CCOEFF_NORMED)
    # 纯色零方差区域会产生 NaN/Inf，必须清零，否则污染最大值定位
    res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
    _, mv, _, ml = cv2.minMaxLoc(res)
    if mv < thresh:
        return None
    return {"x": ox + ml[0] + tw // 2, "y": oy + ml[1] + th // 2,
            "score": round(float(mv), 3)}


def load_tpl(name):
    p = TPL_DIR / name
    if not p.exists():
        return None
    tpl = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if tpl is None:
        return None
    # 零方差纯色模板会让 TM_CCOEFF_NORMED 恒返 1.0，必须在校准源头拦截
    std = float(cv2.meanStdDev(cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY))[1][0][0])
    if std < 2.0:
        print(f"错误：模板 {name} 几乎是纯色（std={std:.1f}），无法用于匹配，"
              "请重新 --calibrate 框准按钮（含文字）")
        sys.exit(1)
    return tpl


# ---------------- 卡片行检测 ----------------

def detect_card_rows(screen_bgr, layout):
    """列表 x 采样带内逐行统计白色像素占比，连续白色行段 = 卡片。

    返回 [(y1, y2), ...] 自上而下。卡片白底 vs 页面浅灰底（约 246）区分。
    """
    g = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    cx, cw = layout["card_cx"], layout["card_w"]
    x1 = max(0, cx - cw // 2 + 20)
    x2 = min(g.shape[1], cx + cw // 2 - 20)
    if x2 - x1 < 40:
        return []
    frac = (g[:, x1:x2] >= layout.get("row_white_level", ROW_WHITE_LEVEL)).mean(axis=1)
    thr = layout.get("row_white_frac", ROW_WHITE_FRAC)
    mask = frac >= thr
    if not mask.any():
        # 自适应兜底：阈值过硬时按分布降档重试一次
        thr2 = max(0.22, float(np.quantile(frac, 0.6)) + 0.02)
        mask = frac >= thr2
    segs, start = [], None
    for y, m in enumerate(mask):
        if m and start is None:
            start = y
        elif not m and start is not None:
            if ROW_MIN_H <= y - start <= ROW_MAX_H:
                segs.append([start, y])
            start = None
    if start is not None and ROW_MIN_H <= len(mask) - start <= ROW_MAX_H:
        segs.append([start, len(mask)])
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] <= 8:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [tuple(s) for s in merged if s[1] - s[0] <= ROW_MAX_H]


# ---------------- 拟人鼠标 ----------------

def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


def bezier_move(tx, ty):
    """三次贝塞尔曲线移动鼠标，随机控制点与时长。"""
    sx, sy = pyautogui.position()
    d = math.hypot(tx - sx, ty - sy)
    if d < 3:
        return
    steps = max(18, min(48, int(d / 18)))
    c1x = sx + (tx - sx) * random.uniform(0.2, 0.5) + random.uniform(-d * 0.08, d * 0.08)
    c1y = sy + (ty - sy) * random.uniform(0.2, 0.5) + random.uniform(-d * 0.08, d * 0.08)
    c2x = sx + (tx - sx) * random.uniform(0.55, 0.85)
    c2y = sy + (ty - sy) * random.uniform(0.55, 0.85)
    dur = random.uniform(0.45, 0.85)
    for i in range(1, steps + 1):
        t = i / steps
        pyautogui.moveTo(_cubic(sx, c1x, c2x, tx, t),
                         _cubic(sy, c1y, c2y, ty, t), _pause=False)
        time.sleep(dur / steps * random.uniform(0.6, 1.4))
    pyautogui.moveTo(tx + random.uniform(-2, 2), ty + random.uniform(-2, 2), _pause=False)


def human_click(x, y):
    """拟人点击：贝塞尔移动 → 短停 → 按下-随机间隔-抬起，落点带抖动。"""
    bezier_move(x + random.uniform(-3, 3), y + random.uniform(-3, 3))
    time.sleep(random.uniform(0.08, 0.2))
    pyautogui.mouseDown(_pause=False)
    time.sleep(random.uniform(0.04, 0.09))
    pyautogui.mouseUp(_pause=False)


class Rhythm:
    """均衡档节奏：卡间 2.5~6s，每 8~12 张插入一次 8~15s 长停顿（模拟被打断）。"""

    def __init__(self):
        self.n = 0
        self.next_long = random.randint(8, 12)

    def wait(self):
        self.n += 1
        if self.n >= self.next_long:
            t = random.uniform(8, 15)
            self.next_long = self.n + random.randint(8, 12)
        else:
            t = random.uniform(2.5, 6)
        print(f"    停顿 {t:.1f}s")
        time.sleep(t)


# ---------------- tkinter 框选器（校准用） ----------------

def pick_region(screen_bgr, hint):
    """全屏显示截图，用户拖拽框选；返回屏幕坐标 (x1,y1,x2,y2) 或 None（ESC）。"""
    from PIL import Image, ImageTk
    import tkinter as tk
    H, W = screen_bgr.shape[:2]
    pil = Image.fromarray(cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2RGB))
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{W}x{H}+0+0")
    root.attributes("-topmost", True)
    cv = tk.Canvas(root, cursor="crosshair", highlightthickness=0)
    cv.pack(fill="both", expand=True)
    tkimg = ImageTk.PhotoImage(pil)
    cv.create_image(0, 0, image=tkimg, anchor="nw")
    cv.create_rectangle(0, 0, W, 60, fill="#1a1a5e", outline="")
    cv.create_text(20, 30, anchor="w", text=f"{hint}   拖拽框选，按 ESC 取消",
                   fill="white", font=("Microsoft YaHei", 14))
    st = {"x0": 0, "y0": 0, "rect": None, "result": None}

    def on_press(e):
        st["x0"], st["y0"] = e.x, e.y

    def on_move(e):
        if st["rect"]:
            cv.delete(st["rect"])
        st["rect"] = cv.create_rectangle(st["x0"], st["y0"], e.x, e.y,
                                         outline="#ff3333", width=2)

    def on_release(e):
        x1, y1, x2, y2 = st["x0"], st["y0"], e.x, e.y
        if abs(x2 - x1) >= 8 and abs(y2 - y1) >= 8:
            st["result"] = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        root.destroy()

    root.bind("<Escape>", lambda e: root.destroy())
    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_move)
    cv.bind("<ButtonRelease-1>", on_release)
    root.focus_force()
    root.mainloop()
    return st["result"]


# ---------------- 校准 ----------------

def gui_ask(msg):
    """弹窗提示并等待用户点确定（支持非交互终端代跑，如 AI 调用）。"""
    import tkinter as tk
    from tkinter import messagebox
    r = tk.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    messagebox.showinfo("Boss 投递校准", msg, parent=r)
    r.destroy()


def cmd_calibrate():
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    print("== 校准开始（共 4 步，均在日常 Chrome 的 Boss 页面上操作）==\n")

    # 步骤 1：列表页布局
    gui_ask("步骤 1/4：在 Chrome 打开 Boss 搜索结果列表页\n（确保首屏卡片可见、窗口最大化），\n准备好后点【确定】。")
    shot = grab_bgr()
    r1 = pick_region(shot, "① 框选【第一张职位卡片】整卡")
    if not r1:
        return print("已取消。")
    r2 = pick_region(shot, "② 框选【第二张职位卡片】整卡")
    if not r2:
        return print("已取消。")
    row_h = r2[1] - r1[1]
    card_w = r1[2] - r1[0]
    if not (50 <= row_h <= 300 and card_w >= 200):
        return print(f"框选结果异常（行高 {row_h}px / 卡宽 {card_w}px），请重跑校准。")
    layout = {"card_cx": (r1[0] + r1[2]) // 2, "card_w": card_w, "row_h": row_h,
              "screen": [shot.shape[1], shot.shape[0]],
              "row_white_level": ROW_WHITE_LEVEL, "row_white_frac": ROW_WHITE_FRAC,
              "date": time.strftime("%Y-%m-%d")}
    rows = detect_card_rows(shot, layout)
    print(f"  行检测自检：框选行高 {row_h}px，检出 {len(rows)} 张卡片行"
          f"（首屏通常 10~15 张；若为 0，运行时把 layout.json 的 row_white_frac 调低到 0.3 再试）")

    # 步骤 2：立即沟通按钮
    gui_ask("步骤 2/4：点开任意一个职位\n（右侧出现详情面板和【立即沟通】按钮），\n点【确定】后开始框选。")
    shot2 = grab_bgr()
    r = pick_region(shot2, "③ 框选【立即沟通】按钮（详情面板里的蓝色按钮）")
    if not r:
        return print("已取消。")
    cv2.imwrite(str(TPL_DIR / "t_chat_btn.png"), shot2[r[1]:r[3], r[0]:r[2]])
    print("  已保存 t_chat_btn.png")

    # 步骤 3：发送按钮（可选）
    gui_ask("步骤 3/4：点击刚才的【立即沟通】。\n若弹出确认/打招呼弹窗：点【确定】后框选【发送】按钮。\n若无弹窗（直接发送）：点【确定】后按 ESC 跳过。")
    shot3 = grab_bgr()
    r = pick_region(shot3, "④ 框选弹窗里的【发送】按钮（无弹窗则按 ESC 跳过）")
    if r:
        cv2.imwrite(str(TPL_DIR / "t_send_btn.png"), shot3[r[1]:r[3], r[0]:r[2]])
        print("  已保存 t_send_btn.png")
    else:
        print("  跳过 t_send_btn（运行时按按钮态变化判定投递结果）")

    # 步骤 4：继续沟通按钮（可选）
    gui_ask("步骤 4/4：找一个【已投过】的职位点开详情\n（面板按钮变【继续沟通】），点【确定】后框选。\n没有已投职位：点【确定】后按 ESC 跳过。")
    shot4 = grab_bgr()
    r = pick_region(shot4, "⑤ 框选【继续沟通】按钮（灰色已投按钮，无则 ESC 跳过）")
    if r:
        cv2.imwrite(str(TPL_DIR / "t_chatted_btn.png"), shot4[r[1]:r[3], r[0]:r[2]])
        print("  已保存 t_chatted_btn.png")
    else:
        print("  跳过 t_chatted_btn（运行时未命中【立即沟通】即按已投跳过）")

    gui_ask("按 ESC 关闭详情面板，然后点【确定】完成校准。")
    LAYOUT_JSON.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n校准完成：{LAYOUT_JSON}\n模板目录：{TPL_DIR}\n"
          "建议先跑 --dry-run --limit 3 验证定位，再正式投递。")
    gui_ask("校准完成！可以开始投递了。")


# ---------------- 投递主流程 ----------------

def load_env_all():
    if not LAYOUT_JSON.exists():
        print("缺少校准数据：请先运行 uv run boss_apply_visual.py --calibrate")
        sys.exit(1)
    layout = json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))
    screen_now = pyautogui.size()
    if [screen_now.width, screen_now.height] != layout.get("screen"):
        print(f"警告：当前分辨率 {screen_now.width}x{screen_now.height} 与校准时不一致，"
              "定位可能失败，建议重新 --calibrate")
    return (layout, load_tpl("t_chat_btn.png"), load_tpl("t_send_btn.png"),
            load_tpl("t_chatted_btn.png"))


def cmd_apply(args):
    layout, t_chat, t_send, t_chatted = load_env_all()
    if t_chat is None:
        print("缺少 t_chat_btn.png，请先 --calibrate")
        sys.exit(1)

    done = bc.today_count("apply")
    env = bc.load_env()
    quota = args.limit if args.limit else int(env["BOSS_DAILY_LIMIT"]) - done
    if quota <= 0:
        print(f"今日已投 {done}，达到上限 {env['BOSS_DAILY_LIMIT']}，停止。")
        return
    print(f"今日已投 {done}，本次额度 {quota}（上限 {env['BOSS_DAILY_LIMIT']}）。"
          f"模式：{'dry-run（只定位不点击）' if args.dry_run else '正式投递'}\n"
          "提醒：脚本将接管鼠标；紧急停止 = 鼠标甩到屏幕左上角或 Ctrl+C。")

    screen = grab_bgr()
    H, W = screen.shape[:2]
    rows = detect_card_rows(screen, layout)
    print(f"行检测：当前屏 {len(rows)} 张卡片")
    if not rows:
        print("未检出卡片：确认 Chrome 列表页在前台且未被遮挡；"
              "若页面正常，把 layout.json 的 row_white_frac 降到 0.3 重试。")
        return

    rhythm = Rhythm()
    applied = skipped = unknown_streak = 0
    label = args.label or ""
    for i, (y1, y2) in enumerate(rows):
        if applied >= quota:
            break
        cy = (y1 + y2) // 2
        card_cx = layout["card_cx"]
        band = (0, max(0, y1 - 25), W, min(H, y2 + 25))
        print(f"[{i + 1}/{len(rows)}] 卡片 y={y1}~{y2}")

        # 1) hover 卡片，找快捷【立即沟通】
        bezier_move(card_cx, cy)
        time.sleep(random.uniform(0.4, 0.7))
        m = match_tpl(grab_bgr(), t_chat, region=band)
        how = "hover" if m else None

        # 2) 未命中：已投判定 / fallback 详情链路
        if not m:
            if t_chatted is not None and match_tpl(grab_bgr(), t_chatted, region=band):
                print("    已投（快捷按钮=继续沟通）→ 跳过")
                skipped += 1
                rhythm.wait()
                continue
            print("    无快捷按钮 → fallback 点开详情面板")
            if not args.dry_run:
                human_click(card_cx, cy)
                time.sleep(random.uniform(1.2, 2.0))
            shot2 = grab_bgr()
            m = match_tpl(shot2, t_chat)
            if m:
                how = "detail"
            elif t_chatted is not None and match_tpl(shot2, t_chatted):
                print("    已投（详情按钮=继续沟通）→ 跳过并关面板")
                skipped += 1
                pyautogui.press("esc")
                rhythm.wait()
                continue
            else:
                unknown_streak += 1
                pyautogui.press("esc")
                print(f"    详情面板未找到按钮 → 记未知（连续 {unknown_streak}/2）")
                if unknown_streak >= 2:
                    print("连续 2 张定位失败，停止。请人工检查页面/重跑校准。")
                    break
                rhythm.wait()
                continue

        # 3) 点击立即沟通
        print(f"    命中【立即沟通】({how}, score={m['score']})")
        if not args.dry_run:
            human_click(m["x"], m["y"])
        time.sleep(random.uniform(1.0, 1.8))

        # 4) 结果判定：弹窗发送按钮 / 按钮态变化
        ok = None
        shot3 = grab_bgr()
        if t_send is not None:
            ms = match_tpl(shot3, t_send)
            if ms:
                print(f"    弹窗【发送】命中 (score={ms['score']})")
                if not args.dry_run:
                    human_click(ms["x"], ms["y"])
                time.sleep(random.uniform(0.8, 1.5))
                ok = match_tpl(grab_bgr(), t_send) is None
                if not ok:
                    pyautogui.press("esc")
            else:
                ok = True  # 无弹窗 = 可能直投成功，结合按钮态复核
        if ok is None or ok:
            m2 = match_tpl(grab_bgr(), t_chat)
            if m2 and abs(m2["y"] - m["y"]) < 15:
                ok = False  # 按钮原位仍在 = 未变化
            elif ok is None:
                ok = True
        if ok:
            applied += 1
            unknown_streak = 0
            print(f"    ✓ 投递成功（累计 {applied}/{quota}）")
            if not args.dry_run:
                bc.append_jsonl(f"apply-{time.strftime('%Y%m%d')}.jsonl", {
                    "ts": time.strftime("%H:%M:%S"), "label": label,
                    "idx": i + 1, "action": "apply", "how": how,
                    "score": m["score"], "x": m["x"], "y": m["y"]})
        else:
            unknown_streak += 1
            pyautogui.press("esc")
            print(f"    ? 点击后页面未变化 → 记未知（连续 {unknown_streak}/2）")
            if unknown_streak >= 2:
                print("连续 2 次点击无效果，停止。请人工检查页面/重跑校准。")
                break
        rhythm.wait()

    total = bc.today_count("apply")
    print(f"\n本屏结果：投递 {applied}，跳过 {skipped}；今日累计 {total}。"
          "翻页/换组合后再次运行即可继续（额度自动接续）。")


def main():
    ap = argparse.ArgumentParser(description="Boss直聘纯视觉投递（无痕模式）")
    ap.add_argument("--calibrate", action="store_true", help="首次校准：框选模板与布局")
    ap.add_argument("--dry-run", action="store_true", help="只定位与 hover，不点击")
    ap.add_argument("--limit", type=int, help="本次投递上限（默认取当日剩余额度）")
    ap.add_argument("--label", default="", help="组合标签，写入投递记录（如 杭州·实施）")
    args = ap.parse_args()
    if args.calibrate:
        cmd_calibrate()
    else:
        cmd_apply(args)


if __name__ == "__main__":
    main()
