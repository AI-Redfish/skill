#!/usr/bin/env python3
"""report_html.py — 测试报告 Markdown → 自包含 HTML + 自动打开。

用途: 测试模式⑤步生成 report.md 后调用：同目录生成 <report>.html（内嵌样式、
      无外部依赖、PASS/FAIL 状态标色），并自动用系统浏览器打开。
依赖: Python 3.9+ 纯标准库。
用法:
  python3 report_html.py <report.md> [--no-open]
  --no-open 只生成不打开（CI / 无界面场景）
支持: 标题 / 表格(含对齐与状态标色) / 围栏代码块 / 列表 / 引用 / 粗体斜体 /
      行内代码 / 链接 / 水平线（report.md 所用语法子集）
输出: JSON（status/data），退出码 0=ok 1=错误
"""
from __future__ import annotations
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

# 表格单元格中的结果取值标色（对账报告常用）
_STATUS_COLORS = {
    "PASS": "#1a7f37",        # 绿
    "FAIL": "#cf222e",        # 红
    "BLOCKED": "#bc4c00",     # 橙
    "MANUAL": "#57606a",      # 灰
    "SKIPPED": "#57606a",
    "SKIPPED-降级": "#57606a",
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         max-width: 980px; margin: 0 auto; padding: 24px 32px; color: #1f2328;
         background: #fff; line-height: 1.65; }}
  h1 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 8px; }}
  h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 6px; margin-top: 28px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; }}
  th {{ background: #f6f8fa; }}
  pre {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
        padding: 12px; overflow-x: auto; font-size: 13px; }}
  code {{ background: #f6f8fa; border-radius: 4px; padding: 1px 5px; font-size: 90%; }}
  pre code {{ padding: 0; background: none; }}
  blockquote {{ border-left: 4px solid #d0d7de; margin: 12px 0; padding: 4px 14px;
               color: #57606a; background: #f6f8fa; }}
  a {{ color: #0969da; }}
  hr {{ border: none; border-top: 1px solid #d0d7de; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_inline(text: str) -> str:
    """行内元素：行内代码（先保护）→ 粗体 → 斜体 → 链接 → 还原。"""
    text = html.escape(text, quote=False)
    stash: list[str] = []

    def _keep(m: re.Match) -> str:
        stash.append(m.group(1))
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _keep, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: f"<code>{stash[int(m.group(1))]}</code>", text)


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    s = s.replace("\\|", "\x01")
    return [c.strip().replace("\x01", "|") for c in s.split("|")]


def _parse_align(sep: str) -> list[str]:
    out = []
    for c in _split_row(sep):
        left, right = c.startswith(":"), c.endswith(":")
        out.append("center" if left and right else "right" if right else "left")
    return out


def _render_cell(cell: str) -> str:
    key = cell.strip()
    if key in _STATUS_COLORS:
        color = _STATUS_COLORS[key]
        return f'<span style="color:{color};font-weight:600">{render_inline(cell)}</span>'
    return render_inline(cell)


def render_table(header: list[str], aligns: list[str], body: list[list[str]]) -> str:
    def _row(cells: str, tag: str) -> str:
        tds = []
        for j, c in enumerate(cells):
            style = ""
            if j < len(aligns) and aligns[j] != "left":
                style = f' style="text-align:{aligns[j]}"'
            tds.append(f"<{tag}{style}>{_render_cell(c)}</{tag}>")
        return f"<tr>{''.join(tds)}</tr>"

    parts = ["<table>", "<thead>", _row(header, "th"), "</thead>", "<tbody>"]
    parts += [_row(r, "td") for r in body]
    parts += ["</tbody>", "</table>"]
    return "".join(parts)


def _is_table_sep(line: str) -> bool:
    s = line.strip()
    return bool(s) and bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", s))


def render_markdown(md_text: str) -> str:
    """块级状态机渲染（report.md 所用语法子集）。"""
    lines = md_text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("```"):                       # 围栏代码块
            code: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)          # 标题
        if m:
            lv = len(m.group(1))
            out.append(f"<h{lv}>{render_inline(m.group(2))}</h{lv}>")
            i += 1
            continue
        if re.fullmatch(r"-{3,}", stripped):                  # 水平线
            out.append("<hr>")
            i += 1
            continue
        if "|" in stripped and i + 1 < n and _is_table_sep(lines[i + 1]):  # 表格
            header, aligns = _split_row(stripped), _parse_align(lines[i + 1])
            i += 2
            body = []
            while i < n and lines[i].strip() and "|" in lines[i].strip():
                body.append(_split_row(lines[i]))
                i += 1
            out.append(render_table(header, aligns, body))
            continue
        if stripped.startswith(">"):                          # 引用
            quote: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]).strip())
                i += 1
            out.append(f"<blockquote>{render_inline(' '.join(quote))}</blockquote>")
            continue
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):  # 列表
            ordered = bool(re.match(r"^\d+\.", stripped))
            items: list[str] = []
            while i < n:
                s = lines[i].strip()
                m_ul = re.match(r"^[-*]\s+(.*)$", s)
                m_ol = re.match(r"^\d+\.\s+(.*)$", s)
                if not ordered and m_ul:
                    items.append(m_ul.group(1))
                elif ordered and m_ol:
                    items.append(m_ol.group(1))
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(f'<li>{render_inline(t)}</li>' for t in items)}</{tag}>")
            continue
        if stripped == "":                                    # 空行
            i += 1
            continue
        para = [stripped]                                     # 段落（合并软换行）
        i += 1
        while i < n:
            s2 = lines[i].strip()
            if (s2 == "" or s2.startswith(("#", "```", ">", "|"))
                    or re.match(r"^[-*]\s+", s2) or re.match(r"^\d+\.\s+", s2)
                    or re.fullmatch(r"-{3,}", s2)):
                break
            para.append(s2)
            i += 1
        out.append(f"<p>{render_inline(' '.join(para))}</p>")
    return "\n".join(out)


def open_html(path: Path) -> bool:
    """系统浏览器打开；WSL / 无桌面环境用 wslview 兜底。"""
    try:
        if webbrowser.open(path.resolve().as_uri()):
            return True
    except Exception:
        pass
    if shutil.which("wslview"):
        try:
            subprocess.run(["wslview", str(path.resolve())], timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    return False


def _extract_title(md_text: str, fallback: str) -> str:
    for line in md_text.splitlines():
        m = re.match(r"^#\s+(.*)$", line.strip())
        if m:
            return html.escape(m.group(1), quote=True)
    return html.escape(fallback, quote=True)


def main_with_args(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Markdown 测试报告 → 自包含 HTML，默认自动打开")
    ap.add_argument("md", help="report.md 路径")
    ap.add_argument("--no-open", action="store_true", help="只生成不打开（CI/无界面）")
    args = ap.parse_args(argv)

    src = Path(args.md)
    if not src.is_file():
        print(json.dumps({
            "status": "error",
            "error": {"message": f"文件不存在：{src}", "reason": "路径错误",
                      "action": "确认 report.md 路径后重跑"},
        }, ensure_ascii=False, indent=2))
        return 1
    md_text = src.read_text(encoding="utf-8")
    body = render_markdown(md_text)
    html_path = src.with_suffix(".html")
    html_path.write_text(
        HTML_TEMPLATE.format(title=_extract_title(md_text, src.stem), body=body),
        encoding="utf-8")

    opened = False if args.no_open else open_html(html_path)
    print(json.dumps({"status": "ok", "data": {
        "markdown": str(src.resolve()),
        "html": str(html_path.resolve()),
        "opened": opened,
    }}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return main_with_args(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
