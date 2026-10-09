#!/usr/bin/env python3
"""Render a PRD Markdown report to offline HTML and open the OS default browser.

Standard library only. Supports the report templates' headings, paragraphs, lists,
pipe tables, fenced code, blockquotes, links, images and inline emphasis/code.
It is a template-oriented renderer, not a complete CommonMark implementation.
"""
from __future__ import annotations

import argparse
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


def safe_url(value: str) -> str:
    value = value.strip().strip('<>')
    scheme = urlsplit(value).scheme.lower()
    if scheme and scheme not in {'https', 'http', 'file', 'mailto'}:
        return '#'
    return html.escape(value, quote=True)


def inline(text: str) -> str:
    tokens: list[str] = []

    def reserve(markup: str) -> str:
        tokens.append(markup)
        return f'\x00{len(tokens) - 1}\x00'

    text = re.sub(r'`([^`]+)`', lambda m: reserve('<code>' + html.escape(m[1]) + '</code>'), text)
    text = re.sub(r'!\[([^\]]*)\]\(([^\n]*?)\)', lambda m: reserve(
        f'<a href="{safe_url(m[2])}" target="_blank" rel="noopener"><img loading="lazy" src="{safe_url(m[2])}" alt="{html.escape(m[1], quote=True)}"></a>'), text)
    text = re.sub(r'\[([^\]]+)\]\(([^\n]*?)\)', lambda m: reserve(
        f'<a href="{safe_url(m[2])}">{html.escape(m[1])}</a>'), text)
    text = html.escape(text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    return re.sub(r'\x00(\d+)\x00', lambda m: tokens[int(m[1])], text)


def cells(line: str) -> list[str]:
    return [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', line.strip().strip('|'))]


def render_markdown(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = text.splitlines()
    parts: list[str] = []
    headings: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading:
            level = len(heading[1])
            anchor = f'section-{len(headings) + 1}'
            headings.append((level, heading[2], anchor))
            parts.append(f'<h{level} id="{anchor}">{inline(heading[2])}</h{level}>')
            i += 1
            continue
        if line.startswith('```'):
            language = line[3:].strip()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i])
                i += 1
            parts.append(f'<pre data-language="{html.escape(language, quote=True)}"><code>{html.escape(chr(10).join(block))}</code></pre>')
            i += 1
            continue
        if i + 1 < len(lines) and '|' in line and re.match(r'^\s*\|?\s*:?-{3,}', lines[i + 1]):
            header = cells(line)
            parts.append('<div class="table-scroll"><table><thead><tr>' + ''.join('<th>' + inline(c) + '</th>' for c in header) + '</tr></thead><tbody>')
            i += 2
            while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                parts.append('<tr>' + ''.join('<td>' + inline(c) + '</td>' for c in cells(lines[i])) + '</tr>')
                i += 1
            parts.append('</tbody></table></div>')
            continue
        item = re.match(r'^\s*(-|\d+\.)\s+(.+)$', line)
        if item:
            kind = 'ul' if item[1] == '-' else 'ol'
            parts.append(f'<{kind}>')
            while i < len(lines):
                item = re.match(r'^\s*(-|\d+\.)\s+(.+)$', lines[i])
                if not item or ('ul' if item[1] == '-' else 'ol') != kind:
                    break
                parts.append('<li>' + inline(item[2]) + '</li>')
                i += 1
            parts.append(f'</{kind}>')
            continue
        if line.startswith('> '):
            parts.append('<blockquote>' + inline(line[2:]) + '</blockquote>')
            i += 1
            continue
        if re.match(r'^\s*---+\s*$', line):
            parts.append('<hr>')
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,6}\s|```|> |\s*(-|\d+\.)\s)', lines[i]) and '|' not in lines[i]:
            paragraph.append(lines[i])
            i += 1
        parts.append('<p>' + inline('\n'.join(paragraph)) + '</p>')
    return '\n'.join(parts), headings


STYLE = '''
:root{color-scheme:light;--ink:#182b43;--muted:#62718a;--blue:#2459ae;--line:#dce5ee}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f2f5fa;color:var(--ink);font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
header{background:#152e50;color:white;padding:24px 5vw}header strong{font-size:24px}header p{margin:5px 0;color:#cbd9ee}header a{color:#e5efff}
.layout{display:grid;grid-template-columns:270px minmax(0,1fr);max-width:1520px;margin:auto;gap:24px;padding:24px}nav{position:sticky;top:18px;max-height:94vh;overflow:auto;padding:16px;border:1px solid var(--line);border-radius:12px;background:white;align-self:start}nav a{display:block;text-decoration:none;color:var(--muted);font-size:13px;padding:5px 0;border-bottom:1px solid #f1f4f8}nav .level-3{padding-left:12px}nav strong{display:block;margin-bottom:8px}
main{min-width:0;background:white;padding:30px 38px;border:1px solid var(--line);border-radius:12px}h1{font-size:30px;line-height:1.4}h2{margin-top:44px;border-bottom:2px solid #d8e5f8;padding-bottom:10px;font-size:23px;color:#174278}h3{margin-top:36px;font-size:19px;border-left:4px solid #3872c5;padding-left:12px;scroll-margin-top:18px}p{margin:15px 0}a{color:var(--blue);overflow-wrap:anywhere}code{background:#edf2f8;padding:2px 5px;border-radius:4px;font-size:13px;overflow-wrap:anywhere}pre{white-space:pre-wrap;padding:18px;background:#edf2f8;border-radius:8px;overflow:auto}pre code{padding:0}blockquote{margin:20px 0;background:#fff7e4;border-left:4px solid #d49920;padding:14px 18px}.table-scroll{max-width:100%;overflow-x:auto;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top;min-width:85px}th{background:#eaf1fb;white-space:nowrap}tr:nth-child(even){background:#fafcff}img{display:block;max-width:100%;height:auto;border:1px solid var(--line);border-radius:8px;margin:14px 0}li{margin:7px 0}button{border:1px solid #a9bddb;background:white;border-radius:6px;padding:7px 14px;cursor:pointer;color:#234d82}.toolbar{display:flex;gap:12px;align-items:center;margin-top:12px}input{padding:8px;border:1px solid #afc1d8;border-radius:6px;min-width:260px}mark{background:#ffdc82}footer{text-align:center;font-size:13px;color:var(--muted);padding:26px}.priority{font-weight:700}
@media(max-width:950px){.layout{grid-template-columns:1fr;padding:12px}nav{position:static;max-height:220px}main{padding:20px}header{padding:20px}h1{font-size:25px}input{min-width:0;width:100%}}
@media print{header,nav,.toolbar,footer{display:none}.layout{display:block;padding:0}main{border:0;padding:0}body{background:white;font-size:11pt}h2,h3{break-after:avoid}img,tr{break-inside:avoid}.table-scroll{overflow:visible}table{font-size:9pt}a{color:inherit;text-decoration:none}pre{white-space:pre-wrap}}
'''


def generate(source: Path, target: Path) -> None:
    body, headings = render_markdown(source.read_text(encoding='utf-8-sig'))
    title = headings[0][1] if headings else source.stem
    toc = ''.join(f'<a class="level-{level}" href="#{anchor}">{html.escape(label)}</a>' for level, label, anchor in headings if level in {2, 3})
    page = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{STYLE}</style></head>
<body><header><strong>{html.escape(title)}</strong><p>业务合理性 · 前后一致性 · 原型与 PRD 对照 · 可验收性</p><div class="toolbar"><a href="{html.escape(source.name, quote=True)}">查看 Markdown 原文</a><button type="button" onclick="window.print()">打印 / 保存 PDF</button><input id="search" type="search" placeholder="查找报告文字（回车）" aria-label="查找报告文字"><button type="button" id="find">查找下一处</button></div></header>
<div class="layout"><nav aria-label="报告目录"><strong>报告目录</strong>{toc}</nav><main>{body}</main></div><footer>报告正文由同一份 Markdown 生成 · 核心内容离线可读 · 截图可点击查看原图</footer>
<script>function findText(){{const q=document.getElementById('search').value.trim();if(q&&window.find)window.find(q,false,false,true);}}document.getElementById('find').addEventListener('click',findText);document.getElementById('search').addEventListener('keydown',e=>{{if(e.key==='Enter')findText();}});</script></body></html>'''
    target.write_text(page, encoding='utf-8')
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError('HTML 报告未成功生成')


def open_default(target: Path) -> str:
    target = target.resolve()
    if os.name == 'nt':
        os.startfile(str(target))
        return 'Windows 默认关联已接受打开请求'
    if sys.platform == 'darwin':
        subprocess.run(['open', str(target)], check=True, timeout=30)
        return 'macOS 默认关联已接受打开请求'
    if 'microsoft' in Path('/proc/sys/kernel/osrelease').read_text().lower():
        winpath = subprocess.check_output(['wslpath', '-w', str(target)], text=True).strip()
        script = "Start-Process -FilePath '" + winpath.replace("'", "''") + "' -ErrorAction Stop"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], check=True, timeout=30)
        return 'Windows 默认关联已接受打开请求（通过 WSL）'
    opener = shutil.which('xdg-open')
    if not opener:
        raise RuntimeError('当前环境未找到 xdg-open；请手动打开 HTML 报告')
    subprocess.run([opener, str(target)], check=True, timeout=30)
    return 'Linux 默认关联已接受打开请求'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('markdown', type=Path)
    parser.add_argument('--output', type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--no-open', action='store_true')
    group.add_argument('--open-only', action='store_true')
    args = parser.parse_args()
    source = args.markdown.resolve()
    target = (args.output or source.with_suffix('.html')).resolve()
    if target == source:
        parser.error('HTML 输出路径不能与 Markdown 输入路径相同')
    if not args.open_only:
        if target.exists():
            parser.error('HTML 已存在；请使用新的配对文件名，避免覆盖已有报告')
        target.parent.mkdir(parents=True, exist_ok=True)
        generate(source, target)
        print(f'Markdown: {source}\nHTML: {target}')
    if not args.no_open:
        if not target.is_file():
            parser.error('HTML 报告不存在')
        try:
            print(open_default(target))
        except Exception as exc:
            print(f'默认浏览器打开失败：{exc}\n请手动打开：{target}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
