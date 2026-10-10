#!/usr/bin/env python3
"""Offline HTML counterparts for Bug reports; no external skill or packages needed.

Uses the local prd-review report renderer's template-oriented Markdown approach.
Markdown is the sole content source. HTML is deterministic and can be regenerated.
"""
import html
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

REPORT_NAMES = ("analysis.md", "solution.md", "fix-report.md")


def safe_url(value):
    value = value.strip().strip("<>")
    if any(ord(ch) < 32 for ch in value):
        return "#"
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return "#"
    if scheme and scheme not in {"https", "http", "file", "mailto"}:
        return "#"
    return html.escape(value, quote=True)


def inline(text):
    tokens = []

    def reserve(markup):
        tokens.append(markup)
        return "\x00%d\x00" % (len(tokens) - 1)

    text = text.replace("\x00", "")
    text = re.sub(r"`([^`]+)`", lambda m: reserve("<code>" + html.escape(m[1]) + "</code>"), text)
    text = re.sub(r"!\[([^\]]*)\]\(([^\n]*?)\)", lambda m: reserve(
        '<a href="%s" target="_blank" rel="noopener"><img loading="lazy" src="%s" alt="%s"></a>' %
        (safe_url(m[2]), safe_url(m[2]), html.escape(m[1], quote=True))), text)
    text = re.sub(r"\[([^\]]+)\]\(([^\n]*?)\)", lambda m: reserve(
        '<a href="%s">%s</a>' % (safe_url(m[2]), html.escape(m[1]))), text)
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m[1])], text)


def cells(line):
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def render_markdown(text):
    lines = text.splitlines()
    parts, headings = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level = len(heading[1])
            anchor = "section-%d" % (len(headings) + 1)
            headings.append((level, heading[2], anchor))
            parts.append('<h%d id="%s">%s</h%d>' % (level, anchor, inline(heading[2]), level))
            i += 1
            continue
        fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence:
            marker, language = fence[1], fence[2].strip()
            block = []
            i += 1
            closing = re.compile(r"^\s*" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$")
            while i < len(lines) and not closing.match(lines[i]):
                block.append(lines[i])
                i += 1
            parts.append('<pre data-language="%s"><code>%s</code></pre>' %
                         (html.escape(language, quote=True), html.escape("\n".join(block))))
            i += 1
            continue
        if i + 1 < len(lines) and "|" in line and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            parts.append('<div class="table-scroll"><table><thead><tr>' +
                         "".join("<th>" + inline(c) + "</th>" for c in cells(line)) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                parts.append("<tr>" + "".join("<td>" + inline(c) + "</td>" for c in cells(lines[i])) + "</tr>")
                i += 1
            parts.append("</tbody></table></div>")
            continue
        item = re.match(r"^\s*([-+*]|\d+[.)])\s+(.+)$", line)
        if item:
            kind = "ul" if item[1] in "-+*" else "ol"
            start = ' start="%s"' % re.match(r"\d+", item[1])[0] if kind == "ol" else ""
            parts.append("<%s%s>" % (kind, start))
            while i < len(lines):
                item = re.match(r"^\s*([-+*]|\d+[.)])\s+(.+)$", lines[i])
                if not item or ("ul" if item[1] in "-+*" else "ol") != kind:
                    break
                parts.append("<li>" + inline(item[2]) + "</li>")
                i += 1
            parts.append("</%s>" % kind)
            continue
        if line.startswith("> "):
            parts.append("<blockquote>" + inline(line[2:]) + "</blockquote>")
            i += 1
            continue
        if re.match(r"^\s*---+\s*$", line):
            parts.append("<hr>")
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|\s*(`{3,}|~{3,})|> |\s*([-+*]|\d+[.)])\s)", lines[i]) and "|" not in lines[i]:
            paragraph.append(lines[i])
            i += 1
        parts.append("<p>" + inline("\n".join(paragraph)) + "</p>")
    return "\n".join(parts), headings


STYLE = '''
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#182b43;font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
header{background:#183653;color:white;padding:22px 4vw}header a{color:#e4efff;margin-right:20px}header strong{display:block;font-size:24px;margin-bottom:10px}
.layout{display:grid;grid-template-columns:240px minmax(0,1fr);gap:24px;max-width:1400px;padding:24px;margin:auto}nav{align-self:start;position:sticky;top:16px;max-height:92vh;overflow:auto;background:white;padding:16px;border-radius:10px}nav a{display:block;padding:5px 0;font-size:14px}main{min-width:0;background:white;padding:26px 34px;border-radius:10px}h1{font-size:28px}h2{margin-top:36px;color:#174278;border-bottom:1px solid #cddbed}h3{margin-top:28px}a{color:#2459ae;overflow-wrap:anywhere}p{white-space:pre-line}code{background:#edf2f8;padding:2px 5px;overflow-wrap:anywhere}pre{background:#edf2f8;padding:16px;white-space:pre-wrap;overflow:auto}pre code{padding:0}blockquote{margin:16px 0;border-left:4px solid #d49d30;background:#fff8e9;padding:12px 18px}.table-scroll{overflow-x:auto;margin:20px 0}table{width:100%;border-collapse:collapse;font-size:14px}th,td{border:1px solid #dce5ee;text-align:left;padding:10px;min-width:90px}th{background:#eaf1fb}img{max-width:100%;height:auto;display:block;margin:12px 0}footer{text-align:center;padding:24px;color:#62718a;font-size:13px}
@media(max-width:850px){.layout{grid-template-columns:1fr;padding:12px}nav{position:static;max-height:220px}main{padding:20px}}
@media print{header,nav,footer{display:none}.layout{display:block;padding:0}main{padding:0}body{background:white;font-size:11pt}h2,h3{break-after:avoid}img,tr{break-inside:avoid}.table-scroll{overflow:visible}}
'''


def page(source):
    """Deterministic rendering also serves as a freshness check against the MD."""
    source = Path(source)
    body, headings = render_markdown(source.read_text(encoding="utf-8-sig"))
    title = headings[0][1] if headings else source.stem
    toc = "".join('<a href="#%s">%s</a>' % (anchor, html.escape(label))
                  for level, label, anchor in headings if level in {2, 3})
    return ('<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style></head><body><header><strong>%s</strong>'
            '<a href="%s">查看 Markdown 原文</a></header>'
            '<div class="layout"><nav aria-label="报告目录">%s</nav><main>%s</main></div>'
            '<footer>由同一份 Markdown 生成 · 离线可读 · 图片可点击查看原图</footer></body></html>' %
            (html.escape(title), STYLE, html.escape(title), safe_url(source.name), toc, body))


def generate(source):
    source = Path(source)
    target = source.with_suffix(".html")
    output = page(source)
    tmp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(output, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return str(target)


def render_reports(directory, names=REPORT_NAMES, require_complete=False):
    directory = Path(directory)
    sources = []
    # Validate the complete set before refreshing any HTML.
    for name in names:
        source = directory / name
        if not source.is_file():
            if require_complete:
                raise ValueError("报告缺失: " + str(source))
            continue
        content = source.read_text(encoding="utf-8-sig")
        if require_complete and (not content.strip() or "（待填写" in content):
            raise ValueError("报告尚未完整落盘: " + str(source))
        sources.append(source)
    return {source.stem: generate(source) for source in sources}


def current_reports(directory):
    result = {}
    for name in REPORT_NAMES:
        source = Path(directory) / name
        target = source.with_suffix(".html")
        result[source.stem] = (source.is_file() and target.is_file() and
                               target.read_text(encoding="utf-8") == page(source))
    return result
