#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.45"]
# ///
"""human.py — 拟人操作库（库模块，供本 skill 其他脚本 import；带 --selftest 自检）。

所有页面交互必须经过本模块，禁止直接 page.fill()/locator.click()（反检测红线）：
- 输入：逐字符键盘事件 + 随机延迟（fill 瞬时赋值可被事件时序识别）
- 点击：鼠标多段轨迹移动（带抖动）→ 按下/抬起有间隔（坐标直点可被轨迹识别）
- 节奏：动作间随机间隔；页面切换后等待网络空闲 + 随机余量

用法（自检）：uv run human.py --selftest   # 校验模块可加载与随机函数区间，不启动浏览器
退出码：0 正常；2 自检失败。
"""

from __future__ import annotations

import random
import sys
import time


def rand_sleep(lo: float = 0.3, hi: float = 1.2) -> float:
    delay = random.uniform(lo, hi)
    time.sleep(delay)
    return delay


def _center(page, locator, timeout: float = 15000.0) -> tuple[float, float]:
    locator.wait_for(state="visible", timeout=timeout)
    try:
        locator.scroll_into_view_if_needed(timeout=timeout)
    except Exception:
        pass  # 已在视口内或容器内滚动即可，不视为失败
    box = locator.bounding_box()
    if not box:
        raise RuntimeError("无法获取元素位置（元素不可见或被遮挡），已停止操作，请人工检查页面")
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    # 视口外保护：越界坐标的鼠标事件会静默落空（窗口过小时常见），必须快速失败
    try:
        vw, vh = page.evaluate("() => [window.innerWidth, window.innerHeight]")
        if not (0 <= x < vw and 0 <= y < vh):
            raise RuntimeError(
                f"目标元素中心 ({x:.0f},{y:.0f}) 在视口 ({vw}x{vh}) 之外（问题）；"
                "浏览器窗口过小导致元素被折出可视区（原因）；"
                "最大化浏览器窗口后重试（行动）"
            )
    except RuntimeError:
        raise
    except Exception:
        pass  # 视口尺寸拿不到时不拦截，由后续点击结果判断
    return x, y


def human_click(page, locator, timeout: float = 15000.0) -> None:
    """拟人点击：移动轨迹 → 瞄准（带抖动）→ 按下-抬起。"""
    x, y = _center(page, locator, timeout)
    jx = x + random.uniform(-3, 3)
    jy = y + random.uniform(-3, 3)
    page.mouse.move(jx + random.uniform(-40, 40), jy + random.uniform(-30, 30),
                    steps=random.randint(6, 12))
    rand_sleep(0.08, 0.2)
    page.mouse.move(jx, jy, steps=random.randint(3, 6))
    rand_sleep(0.05, 0.15)
    page.mouse.down()
    rand_sleep(0.04, 0.1)
    page.mouse.up()


def human_type(page, locator, text: str, timeout: float = 15000.0,
               clear_first: bool = False) -> None:
    """拟人输入：点击聚焦 → 逐字符输入（随机延迟 + 偶发停顿）。"""
    human_click(page, locator, timeout)
    if clear_first:
        page.keyboard.press("Control+a")
        rand_sleep(0.05, 0.12)
        page.keyboard.press("Delete")
        rand_sleep(0.1, 0.25)
    pause_every = random.randint(6, 10)
    for i, ch in enumerate(text):
        page.keyboard.type(ch)
        rand_sleep(0.04, 0.13)
        if i and i % pause_every == 0:
            rand_sleep(0.15, 0.4)  # 模拟思考停顿
    rand_sleep(0.3, 0.8)


def human_press(page, key: str, times: int = 1) -> None:
    for _ in range(max(1, times)):
        page.keyboard.press(key)
        rand_sleep(0.1, 0.3)


def human_scroll(page, delta_y: float = 600.0, steps: int = 4) -> None:
    """拟人滚动：分步 wheel，带随机增量。"""
    steps = max(1, steps)
    for _ in range(steps):
        page.mouse.wheel(0, delta_y / steps + random.uniform(-40, 40))
        rand_sleep(0.1, 0.3)


def settle(page, network_timeout: float = 15000.0) -> None:
    """页面切换后等待：domcontentloaded → 尽力 networkidle → 随机余量。"""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=network_timeout)
    except Exception:
        pass  # 长轮询页面永远不 idle，超时属预期
    rand_sleep(0.5, 1.2)


def _selftest() -> int:
    t0 = time.time()
    d = rand_sleep(0.05, 0.08)
    assert 0.03 <= d <= 0.12, f"rand_sleep 区间异常: {d}"
    elapsed = time.time() - t0
    assert 0.03 <= elapsed <= 0.5, f"rand_sleep 实际耗时异常: {elapsed}"
    assert callable(human_click) and callable(human_type) and callable(settle)
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        _selftest()
        print('{"status":"ok","detail":"human.py 自检通过"}')
        return 0
    print('{"status":"error","error":{"code":"NO_CLI","hint":"本模块作为库使用；自检请加 --selftest"}}')
    return 2


if __name__ == "__main__":
    sys.exit(main())
