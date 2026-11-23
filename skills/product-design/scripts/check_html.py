#!/usr/bin/env python3
"""check_html.py — product-design 原型 HTML 静态校验（反 AI 味 + 结构规范）。

用途: 对生成的原型 HTML 做确定性检查，error 级必须修复，warning 逐条自查。
      检查项：charset/viewport/标签配平/响应式断点/纯黑/禁字体/emoji 图标/
      Lorem 占位/AI 陈词滥调/编造指标/100vh/外链资源/填充文案。
依赖: Python 3.9+ 纯标准库，无第三方依赖（python 直跑或 uv run 均可）。
用法:
  uv run check_html.py --html pages/index.html --json
  uv run check_html.py --html a.html b.html --dir pages
参数:
  --html   一个或多个 HTML 文件路径
  --dir    目录模式：扫描目录下全部 *.html（与 --html 可叠加，结果去重）
  --json   结果另存到指定文件路径
退出码: 0=全部通过(无 error) / 1=存在 error / 2=参数或文件错误
输出: stdout JSON {status, files:[{file, errors[], warnings[], stats}]}；日志到 stderr。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}

# ---------- 规则定义（id, 级别, 说明） ----------

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u26FF\u2B00-\u2BFF\uFE0F]")
PURE_BLACK_RE = re.compile(r"#[0-9a-fA-F]{0,2}\b000000\b|(?<![\w#])#000(?![\w])")
BANNED_FONTS = ["Inter", "Times New Roman", "Georgia", "Garamond", "Palatino"]
CLICHES_EN = ["Elevate", "Seamless", "Unleash", "Next-Gen", "Revolutionize",
              "Scroll to explore", "Discover more below"]
CLICHES_ZH = ["赋能", "极致体验", "颠覆式", "引领未来", "重新定义", "向下滚动探索"]
FAKE_METRIC_RE = re.compile(r"99\.9+%|uptime|SLA\s*\d|正常运行率", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"lorem\s+ipsum|占位内容|placeholder\s+text", re.IGNORECASE)
TODO_RE = re.compile(r"TODO[:：]|FIXME|待补充", re.IGNORECASE)
EXTERNAL_RES_RE = re.compile(
    r"""(?:<script[^>]+src=["']https?://|<link[^>]+href=["']https?://|<img[^>]+src=["']https?://)""",
    re.IGNORECASE)
MEDIA_RE = re.compile(r"@media[^{]*\{")
VIEWPORT_RE = re.compile(r"""<meta[^>]+name=["']viewport["'][^>]*content=["'][^"']*width=device-width""", re.IGNORECASE)
VH_RE = re.compile(r"(?:height|min-height)\s*:\s*100vh|h-screen(?=[\s\"'])")


class BalanceParser(HTMLParser):
    """跟踪标签配平（忽略 void 标签与自闭合）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            # 错位闭合：弹出直到匹配
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"标签错位闭合：<{self.stack.pop()}> 未闭合就被 </{tag}> 关闭")
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append(f"多余的闭合标签 </{tag}>")


def check_one(path: Path) -> dict:
    item: dict = {"file": str(path), "errors": [], "warnings": [], "stats": {}}
    if not path.is_file():
        item["errors"] = [f"文件不存在：{path}"]
        item["stats"]["读取"] = "失败"
        return item
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        item["errors"].append("E001 文件不是 UTF-8 编码：请以 UTF-8 保存（问题：编码不符；原因：原型要求跨环境可打开；行动：重存为 UTF-8）")
        return item
    item["stats"]["行数"] = text.count("\n") + 1
    item["stats"]["大小KB"] = round(len(raw) / 1024, 1)

    lower = text.lower()
    # E001 charset
    if "<meta" not in lower or "charset" not in lower:
        item["errors"].append("E001 缺少 <meta charset=\"utf-8\">：无 charset 声明（行动：在 <head> 首行补上）")
    # E002 viewport
    if not VIEWPORT_RE.search(text):
        item["errors"].append("E002 缺少 viewport meta 或不含 width=device-width（行动：<head> 内补 <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">）")
    # E010 标签配平
    parser = BalanceParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        parser.errors.append(f"HTML 解析失败：{exc}")
    for leftover in parser.stack:
        parser.errors.append("标签未闭合：<" + leftover + "> 缺少对应闭合标签")
    if parser.errors:
        item["errors"].append("E010 标签配平问题：" + "；".join(dict.fromkeys(parser.errors[:5])))
    # E020 Lorem/占位
    m = PLACEHOLDER_RE.search(text)
    if m:
        item["errors"].append(f"E020 发现占位文本「{m.group(0)}」：原型必须用真实感内容填充（行动：替换为符合业务的示例内容）")
    # E030 响应式
    media_count = len(MEDIA_RE.findall(text))
    item["stats"]["media查询数"] = media_count
    if media_count == 0:
        item["errors"].append("E030 未发现任何 @media 响应式断点：响应式是硬要求（行动：至少覆盖 ≤768px 单列断点，参考 DESIGN.md 第 6 节）")

    # W001 纯黑
    if PURE_BLACK_RE.search(text):
        item["warnings"].append("W001 疑似纯黑 #000000：应改用 Off-Black/深灰（如 #18181B），纯黑显得生硬")
    # W002 禁字体
    for font in BANNED_FONTS:
        if re.search(rf"(?<![\w-]){re.escape(font)}(?![\w-])", text, re.IGNORECASE):
            item["warnings"].append(f"W002 使用了禁用字体 {font}：中文原型用系统栈（PingFang SC/MiSans/Microsoft YaHei），英文数字用 Geist/Outfit 等替代")
            break
    # W003 emoji 图标
    emojis = EMOJI_RE.findall(text)
    if emojis:
        item["warnings"].append(f"W003 检测到 {len(emojis)} 处 emoji/装饰符号（如 {emojis[0]}）：图标应使用内联 SVG，emoji 仅限用户明确要求的内容文本")
    # W004 AI 陈词滥调
    hits = [c for c in CLICHES_EN + CLICHES_ZH if c.lower() in lower or c in text]
    if hits:
        item["warnings"].append(f"W004 AI 陈词滥调文案：{('、'.join(dict.fromkeys(hits)))}（行动：改为具体、有信息量的表达）")
    # W005 编造指标
    m = FAKE_METRIC_RE.search(text)
    if m:
        item["warnings"].append(f"W005 可疑编造指标「{m.group(0)}」：未经用户提供的统计/SLA 数据需替换为示例占位或真实数据")
    # W006 100vh
    if VH_RE.search(text):
        item["warnings"].append("W006 使用 height:100vh：移动端地址栏会导致跳动，应改 min-height:100dvh")
    # W007 外链资源
    ext = EXTERNAL_RES_RE.findall(text)
    item["stats"]["外链资源数"] = len(ext)
    if ext:
        item["warnings"].append(f"W007 存在 {len(ext)} 处外网资源（script/link/img 引用 http(s) 链接）：断网环境不可用，应内联 CSS/SVG 或用纯 CSS 占位图形")
    # W008 TODO
    m = TODO_RE.search(text)
    if m:
        item["warnings"].append(f"W008 发现未完成标记「{m.group(0)}」：交付前应完成或移除")
    return item


def main() -> int:
    ap = argparse.ArgumentParser(description="product-design 原型 HTML 静态校验")
    ap.add_argument("--html", nargs="+", default=[], help="HTML 文件路径（可多个）")
    ap.add_argument("--dir", default=None, help="扫描目录下全部 *.html")
    ap.add_argument("--json", default=None, help="结果 JSON 另存路径")
    args = ap.parse_args()

    files: list[Path] = []
    seen: set[str] = set()
    for h in args.html:
        p = Path(h)
        if str(p) not in seen:
            files.append(p)
            seen.add(str(p))
    if args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            print(json.dumps({"status": "error", "error": {
                "message": f"--dir 不存在或不是目录：{args.dir}",
                "hint": "检查路径；产物默认在 .agents/out/product-design/<项目名>/pages/"}},
                ensure_ascii=False), file=sys.stderr)
            return 2
        for p in sorted(d.glob("*.html")):
            if str(p) not in seen:
                files.append(p)
                seen.add(str(p))
    if not files:
        print(json.dumps({"status": "error", "error": {
            "message": "未指定任何待检文件",
            "hint": "用 --html <file> 指定文件，或 --dir <pages目录> 扫描整个目录"}},
            ensure_ascii=False), file=sys.stderr)
        return 2

    results = [check_one(p) for p in files]
    has_error = any(r["errors"] for r in results)
    total_w = sum(len(r["warnings"]) for r in results)
    payload = {
        "status": "fail" if has_error else "pass",
        "summary": {"files": len(results), "errors": sum(len(r["errors"]) for r in results),
                    "warnings": total_w},
        "files": results,
    }
    out = json.dumps(payload, ensure_ascii=False, indent=2)
    print(out)
    if args.json:
        Path(args.json).write_text(out, encoding="utf-8")
    for r in results:
        print(f"[check] {r['file']}: errors={len(r['errors'])} warnings={len(r['warnings'])}",
              file=sys.stderr)
    return 1 if has_error else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "error", "error": {
            "message": f"校验执行失败：{exc}",
            "hint": "确认文件路径正确且可读；重复出现时用单文件模式定位"}}, ensure_ascii=False),
            file=sys.stderr)
        sys.exit(1)
