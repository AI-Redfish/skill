"""安卓手机控制基本脚本（uiautomator2 冒烟/MVP）。

前置（手机）：开启开发者选项 + USB 调试；小米/红米另需开启「USB 调试（安全设置）」。
前置（电脑）：USB 连接手机并授权；执行 `uv run python -m uiautomator2 init` 完成初始化。

用法（本目录内执行）:
  uv run android_ctl.py info                          # 查看当前前台应用
  uv run android_ctl.py shot [输出.png]                # 截图，默认 screen.png
  uv run android_ctl.py dump [输出.xml]                # 导出页面元素树，默认 dump.xml
  uv run android_ctl.py tap --text "设置"              # 按文本点击
  uv run android_ctl.py tap --res com.xxx:id/btn      # 按 resource-id 点击
  uv run android_ctl.py input --res com.xxx:id/et --text "你好"  # 向输入框写入文本
  uv run android_ctl.py swipe up                      # 滑动: up/down/left/right

WiFi 连接（可选）: 加 --host 手机IP（需先 adb tcpip 5555 && adb connect IP:5555）。
"""

from __future__ import annotations

import argparse
import sys


def connect(host: str | None):
    import uiautomator2 as u2

    target = host or "USB 自动发现"
    print(f"[connect] 目标: {target}")
    try:
        d = u2.connect(host) if host else u2.connect()
    except Exception as e:  # noqa: BLE001 - 给出可操作的排错提示
        print(f"[error] 连接失败: {e}", file=sys.stderr)
        print("排查: 1) 手机已开 USB 调试并授权本机  2) adb devices 可见设备  "
              "3) 已执行 `uv run python -m uiautomator2 init`", file=sys.stderr)
        raise SystemExit(2)
    print(f"[connect] 成功: {d.serial or target}")
    return d


def cmd_info(d):
    info = d.app_current()
    print(f"当前前台应用: package={info.get('package')} activity={info.get('activity')}")


def cmd_shot(d, out: str):
    d.screenshot(out)
    print(f"截图已保存: {out}")


def cmd_dump(d, out: str):
    xml = d.dump_hierarchy()
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"元素树已保存: {out}（可直接阅读定位 text / resource-id）")


def cmd_tap(d, args):
    if args.text:
        el = d(text=args.text)
    else:
        el = d(resourceId=args.res)
    if not el.wait(timeout=5):
        key = args.text or args.res
        print(f"[error] 未找到元素: {key}（可先 dump 查看页面实际内容）", file=sys.stderr)
        raise SystemExit(3)
    el.click()
    print(f"已点击: {args.text or args.res}")


def cmd_input(d, args):
    el = d(resourceId=args.res)
    if not el.wait(timeout=5):
        print(f"[error] 未找到输入框: {args.res}", file=sys.stderr)
        raise SystemExit(3)
    el.set_text(args.text)
    print(f"已输入到 {args.res}: {args.text}")


def cmd_swipe(d, direction: str):
    d.swipe_ext(direction)
    print(f"已滑动: {direction}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="安卓控制基本脚本",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", help="WiFi 模式设备地址（如 192.168.1.5），默认 USB")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="当前前台应用")
    ps = sub.add_parser("shot", help="截图")
    ps.add_argument("out", nargs="?", default="screen.png")
    pd = sub.add_parser("dump", help="导出页面元素树 XML")
    pd.add_argument("out", nargs="?", default="dump.xml")
    pt = sub.add_parser("tap", help="点击元素")
    g = pt.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="按可见文本定位")
    g.add_argument("--res", dest="resource_id", help="按 resource-id 定位")
    pi = sub.add_parser("input", help="向输入框写入文本")
    pi.add_argument("--res", dest="resource_id", required=True)
    pi.add_argument("--text", required=True)
    pw = sub.add_parser("swipe", help="滑动")
    pw.add_argument("direction", choices=["up", "down", "left", "right"])

    args = p.parse_args()
    d = connect(args.host)
    {"info": lambda: cmd_info(d),
     "shot": lambda: cmd_shot(d, args.out),
     "dump": lambda: cmd_dump(d, args.out),
     "tap": lambda: cmd_tap(d, args),
     "input": lambda: cmd_input(d, args),
     "swipe": lambda: cmd_swipe(d, args.direction)}[args.cmd]()


if __name__ == "__main__":
    main()
