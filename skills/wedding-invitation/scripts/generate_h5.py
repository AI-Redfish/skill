#!/usr/bin/env python3
"""generate_h5.py — 参数化生成动森(动物森友会)风格电子婚礼请柬 H5 单文件。

用途: 读取 scripts/templates/acnh.html 模板, 用新人信息渲染占位符,
      产出一个零依赖、可离线打开、微信可分享的单文件 HTML。
用法: python3 generate_h5.py --groom 王青 --bride 桃十九 --date 2026-10-03 \
        --time 12:08 --venue "西安 · 温德姆大酒店" --addr "陕西省西安市温德姆大酒店" \
        [--map-keyword XX] [--groom-avatar 🐻] [--out 路径] [--config config.json]
依赖: Python 3.9+ 纯标准库。
输出: JSON 到 stdout(status/path/size/fields)；日志到 stderr。
退出码: 0=成功 1=渲染错误 2=参数/输入错误。
"""
from __future__ import annotations
import argparse
import json
import sys
import datetime
from pathlib import Path

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
DEFAULTS = {
    "groom_avatar": "\U0001F43B",      # 🐻
    "bride_avatar": "\U0001F407",      # 🐰
    "groom_personality": "悠闲型",
    "bride_personality": "元气型",
    "groom_favor": "向日葵 \U0001F33B",
    "bride_favor": "桃子罐头 \U0001F351",
    "time": "12:08",
}

REQUIRED = ("groom", "bride", "date", "venue")


def err(msg: str, code: int = 2) -> None:
    json.dump({"status": "error", "error": {"message": msg}}, sys.stdout, ensure_ascii=False)
    sys.exit(code)


def parse_date(s: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        err(f"日期格式错误: {s!r}，应为 YYYY-MM-DD（如 2026-10-03）")


def build_fields(cfg: dict) -> dict:
    """由配置派生全部模板占位符。"""
    d = parse_date(cfg["date"])
    hh, mm = cfg["time"].split(":")
    time_cn = f"中午 {cfg['time']}" if int(hh) < 18 else f"晚上 {cfg['time']}"
    dialog = [
        "亲爱的岛民：", "",
        "攒了好久的里数，",
        "终于换到两张婚礼门票啦 \u2708\ufe0f", "",
        f"{d.year}年{d.month}月{d.day}日 · {WEEKDAY_CN[d.weekday()]}",
        "请空出这一天，",
        "带上好心情登岛 \U0001F3DD\ufe0f", "",
        f"我们在【{cfg['venue']}】",
        "等你一起见证重要时刻！", "",
        f"\u2014\u2014 {cfg['groom']} & {cfg['bride']}",
    ]
    return {
        "GROOM": cfg["groom"], "BRIDE": cfg["bride"],
        "GROOM_AVATAR": cfg.get("groom_avatar", DEFAULTS["groom_avatar"]),
        "BRIDE_AVATAR": cfg.get("bride_avatar", DEFAULTS["bride_avatar"]),
        "GROOM_PERSONALITY": cfg.get("groom_personality", DEFAULTS["groom_personality"]),
        "BRIDE_PERSONALITY": cfg.get("bride_personality", DEFAULTS["bride_personality"]),
        "GROOM_FAVOR": cfg.get("groom_favor", DEFAULTS["groom_favor"]),
        "BRIDE_FAVOR": cfg.get("bride_favor", DEFAULTS["bride_favor"]),
        "DATE_ISO": d.strftime("%Y-%m-%d"), "TIME": cfg["time"],
        "TIME_CN": time_cn, "TIME_MARK": "*", "TIME_HINT": "* 仪式时间可按实际调整（生成时用 --time 指定）",
        "YEAR": str(d.year), "MD": f"{d.month:02d}.{d.day:02d}",
        "WEEKDAY": WEEKDAY_CN[d.weekday()],
        "DATE_DOT": f"{d.year} . {d.month:02d} . {d.day:02d}",
        "VENUE_NAME": cfg["venue"], "VENUE_ADDR": cfg.get("addr") or cfg["venue"],
        "MAP_KEYWORD": cfg.get("map_keyword") or cfg["venue"].replace(" · ", ""),
        "DIALOG_JSON": json.dumps(dialog, ensure_ascii=False),
    }


def render(template: Path, fields: dict) -> str:
    html = template.read_text(encoding="utf-8")
    for k, v in fields.items():
        html = html.replace("{{" + k + "}}", v)
    import re
    left = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", html)))
    if left:
        err(f"模板存在未替换占位符: {left}", 1)
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="生成动森风格婚礼请柬 H5")
    ap.add_argument("--config", help="JSON 配置文件(键同命令行参数名)，与命令行叠加、命令行优先")
    ap.add_argument("--groom", help="新郎姓名(必填)")
    ap.add_argument("--bride", help="新娘姓名(必填)")
    ap.add_argument("--date", help="婚礼日期 YYYY-MM-DD(必填)")
    ap.add_argument("--venue", help="场地名称, 如 '西安 · 温德姆大酒店'(必填)")
    ap.add_argument("--addr", help="完整地址(复制/展示用, 缺省=venue)")
    ap.add_argument("--map-keyword", help="高德地图搜索词(缺省=venue 去分隔符)")
    ap.add_argument("--time", help="仪式时间 HH:MM, 默认 12:08")
    ap.add_argument("--groom-avatar", help="新郎护照头像 emoji, 默认 🐻")
    ap.add_argument("--bride-avatar", help="新娘护照头像 emoji, 默认 🐰")
    ap.add_argument("--out", help="输出 HTML 路径, 默认 ./婚礼请柬-<新郎><新娘>.html")
    a = ap.parse_args()

    cfg = dict(DEFAULTS)
    if a.config:
        cpath = Path(a.config)
        if not cpath.is_file():
            err(f"配置文件不存在: {a.config}")
        cfg.update(json.loads(cpath.read_text(encoding="utf-8")))
    for key in ("groom", "bride", "date", "venue", "addr", "map_keyword", "time",
                "groom_avatar", "bride_avatar"):
        val = getattr(a, key, None)
        if val:
            cfg[key] = val
    missing = [k for k in REQUIRED if not cfg.get(k)]
    if missing:
        err(f"缺少必填参数: {missing}（--groom/--bride/--date/--venue）")

    try:
        hh, mm = cfg["time"].split(":")
        assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except Exception:
        err(f"时间格式错误: {cfg['time']!r}，应为 HH:MM（如 12:08）")

    template = Path(__file__).parent / "templates" / "acnh.html"
    if not template.is_file():
        err(f"模板缺失: {template}", 1)
    fields = build_fields(cfg)
    html = render(template, fields)

    out = Path(a.out) if a.out else Path(f"婚礼请柬-{cfg['groom']}{cfg['bride']}.html")
    out.write_text(html, encoding="utf-8")
    json.dump({"status": "ok", "path": str(out.resolve()), "size": out.stat().st_size,
               "pages": 7, "fields": fields}, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
