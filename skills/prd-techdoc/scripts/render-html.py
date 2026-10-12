#!/usr/bin/env python3
"""把 prd-techdoc 生成的技术文档 Markdown 渲染成同名的离线 HTML 副本。

仅使用 Python 标准库。Mermaid 代码块的渲染顺序：
1. `--svg-dir` 提供了预渲染 SVG（`b01.svg`、`b02.svg` … 与文档中代码块顺序一致）时直接内联；
2. 否则尝试调用 mmdc（`--mmdc` 或 `.agents/.env` 的 `MMDC_PATH`，再退回 PATH），
   配置了 `CHROME_PATH` 或 `--puppeteer-config` 时用 `-p` 传入 puppeteer 配置；
3. 都不行时保留 Mermaid 源码块，并在图位置显示“未渲染”提示与脚本输出摘要。

HTML 完全离线：样式内嵌、图片相对路径、不引用 CDN。脚本只读 Markdown，只写 HTML 与临时目录。

用法:
  python scripts/render-html.py <doc.md> [--output <doc.html>] [--svg-dir <dir>]
                               [--mmdc <path>] [--puppeteer-config <json>]
                               [--work-dir <dir>] [--no-mermaid] [--force]
退出码: 0 = 生成成功（Mermaid 未渲染时降级为源码块并返回 0，输出 WARN）；1 = 失败（输入缺失、输出已存在且未加 --force、写入失败）。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def load_agent_env(work_dir: Path) -> dict[str, str]:
    env_file = work_dir / ".agents" / ".env"
    result: dict[str, str] = {}
    if not env_file.is_file():
        return result
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        result[key.strip()] = value
    return result


def safe_url(value: str) -> str:
    value = value.strip().strip("<>")
    scheme = urlsplit(value).scheme.lower()
    if scheme and scheme not in {"http", "https", "file", "mailto"}:
        return "#"
    return html.escape(value, quote=True)


def inline(text: str) -> str:
    tokens: list[str] = []

    def reserve(markup: str) -> str:
        tokens.append(markup)
        return f"\x00{len(tokens) - 1}\x00"

    text = re.sub(r"`([^`]+)`", lambda m: reserve("<code>" + html.escape(m[1]) + "</code>"), text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^\n]*?)\)",
        lambda m: reserve(
            '<a href="{0}" target="_blank" rel="noopener"><img loading="lazy" src="{0}" alt="{1}"></a>'.format(
                safe_url(m[2]), html.escape(m[1], quote=True)
            )
        ),
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^\n]*?)\)",
        lambda m: reserve(f'<a href="{safe_url(m[2])}">{html.escape(m[1])}</a>'),
        text,
    )
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m[1])], text)


def cells(line: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


class MermaidRenderer:
    """按文档顺序渲染 Mermaid 代码块，失败时降级为源码块。"""

    def __init__(self, svg_dir: Path | None, mmdc: str | None, puppeteer: Path | None, timeout: int, enabled: bool):
        self.svg_dir = svg_dir
        self.mmdc = mmdc
        self.puppeteer = puppeteer
        self.timeout = timeout
        self.enabled = enabled
        self.index = 0
        self.mode = "disabled" if not enabled else ("svg-dir" if svg_dir else ("mmdc" if mmdc else "source"))
        self.failures = 0
        self.messages: list[str] = []
        self._tmp: Path | None = None

    def next_block(self, code: str) -> str:
        self.index += 1
        name = f"b{self.index:02d}"
        if not self.enabled:
            return self._fallback(code, "已按 --no-mermaid 跳过渲染")
        if self.svg_dir:
            svg = self.svg_dir / f"{name}.svg"
            if svg.is_file():
                return self._wrap(self._read_svg(svg), name, "")
            self.failures += 1
            return self._fallback(code, f"未找到预渲染文件 {svg}")
        if self.mmdc:
            svg = self._render(code, name)
            if svg:
                return self._wrap(svg, name, "")
            self.failures += 1
            return self._fallback(code, "mmdc 渲染失败")
        return self._fallback(code, "未提供 mmdc 或预渲染目录")

    def _render(self, code: str, name: str) -> str | None:
        if self._tmp is None:
            self._tmp = Path(tempfile.mkdtemp(prefix="techdoc-mermaid-"))
        src = self._tmp / f"{name}.mmd"
        out = self._tmp / f"{name}.svg"
        src.write_text(code, encoding="utf-8")
        cmd = [self.mmdc, "-i", str(src), "-o", str(out)]
        if self.puppeteer:
            cmd += ["-p", str(self.puppeteer)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            self.messages.append(f"{name}: {exc}")
            return None
        if not out.is_file() or out.stat().st_size == 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            self.messages.append(f"{name}: " + (detail[-1] if detail else f"exit={proc.returncode}"))
            return None
        return self._read_svg(out)

    @staticmethod
    def _read_svg(path: Path) -> str:
        svg = path.read_text(encoding="utf-8", errors="replace")
        svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
        svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg)
        return svg.strip()

    @staticmethod
    def _wrap(svg: str, name: str, note: str) -> str:
        note_html = f'<p class="figure-note">{html.escape(note)}</p>' if note else ""
        return f'<figure class="diagram" id="diagram-{name}">{svg}{note_html}</figure>'

    @staticmethod
    def _fallback(code: str, note: str) -> str:
        return (
            f'<div class="diagram diagram-fallback"><p class="figure-note">Mermaid 未渲染：'
            f"{html.escape(note)}；以下为该图的源码，可在支持 Mermaid 的工具中查看。</p>"
            f'<pre data-language="mermaid"><code>{html.escape(code)}</code></pre></div>'
        )

    def cleanup(self) -> None:
        if self._tmp and self._tmp.is_dir():
            shutil.rmtree(self._tmp, ignore_errors=True)


def render_markdown(text: str, mermaid: MermaidRenderer) -> tuple[str, list[tuple[int, str, str]]]:
    lines = text.splitlines()
    parts: list[str] = []
    headings: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level = len(heading[1])
            anchor = f"section-{len(headings) + 1}"
            headings.append((level, heading[2], anchor))
            parts.append(f'<h{level} id="{anchor}">{inline(heading[2])}</h{level}>')
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip().lower()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(block)
            if language == "mermaid":
                parts.append(mermaid.next_block(code))
            else:
                parts.append(
                    f'<pre data-language="{html.escape(language, quote=True)}"><code>{html.escape(code)}</code></pre>'
                )
            continue
        if i + 1 < len(lines) and "|" in line and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            header = cells(line)
            parts.append(
                '<div class="table-scroll"><table><thead><tr>'
                + "".join("<th>" + inline(c) + "</th>" for c in header)
                + "</tr></thead><tbody>"
            )
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                parts.append("<tr>" + "".join("<td>" + inline(c) + "</td>" for c in cells(lines[i])) + "</tr>")
                i += 1
            parts.append("</tbody></table></div>")
            continue
        item = re.match(r"^\s*(-|\d+\.)\s+(.+)$", line)
        if item:
            kind = "ul" if item[1] == "-" else "ol"
            parts.append(f"<{kind}>")
            while i < len(lines):
                item = re.match(r"^\s*(-|\d+\.)\s+(.+)$", lines[i])
                if not item or ("ul" if item[1] == "-" else "ol") != kind:
                    break
                parts.append("<li>" + inline(item[2]) + "</li>")
                i += 1
            parts.append(f"</{kind}>")
            continue
        if line.startswith(">"):
            quote = [line.lstrip(">").strip()]
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip(">").strip())
                i += 1
            parts.append("<blockquote>" + inline(" ".join(q for q in quote if q)) + "</blockquote>")
            continue
        if re.match(r"^\s*---+\s*$", line):
            parts.append("<hr>")
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|> |\s*(-|\d+\.)\s)", lines[i]):
            paragraph.append(lines[i])
            i += 1
        parts.append("<p>" + inline("\n".join(paragraph)) + "</p>")
    return "\n".join(parts), headings


STYLE = """
:root{color-scheme:light;--ink:#182b43;--muted:#62718a;--blue:#2459ae;--line:#dce5ee}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f2f5fa;color:var(--ink);font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
header{background:#152e50;color:#fff;padding:22px 5vw}header strong{font-size:23px}header p{margin:6px 0 0;color:#cbd9ee;font-size:14px}
.layout{display:grid;grid-template-columns:280px minmax(0,1fr);max-width:1560px;margin:auto;gap:24px;padding:24px}
nav{position:sticky;top:18px;max-height:94vh;overflow:auto;padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff;align-self:start}
nav a{display:block;text-decoration:none;color:var(--muted);font-size:13px;padding:5px 0;border-bottom:1px solid #f1f4f8}
nav .level-3{padding-left:12px}nav strong{display:block;margin-bottom:8px}
main{min-width:0;background:#fff;padding:30px 38px;border:1px solid var(--line);border-radius:12px}
h1{font-size:28px;line-height:1.4}h2{margin-top:44px;border-bottom:2px solid #d8e5f8;padding-bottom:10px;font-size:22px;color:#174278}
h3{margin-top:34px;font-size:18px;border-left:4px solid #3872c5;padding-left:12px;scroll-margin-top:18px}
h4{margin-top:26px;font-size:16px;color:#234d82}p{margin:14px 0}a{color:var(--blue);overflow-wrap:anywhere}
code{background:#edf2f8;padding:2px 5px;border-radius:4px;font-size:13px;overflow-wrap:anywhere}
pre{white-space:pre-wrap;padding:16px;background:#f4f7fb;border:1px solid var(--line);border-radius:8px;overflow:auto}
pre code{padding:0;background:none}blockquote{margin:18px 0;background:#fff7e4;border-left:4px solid #d49920;padding:12px 16px}
.table-scroll{max-width:100%;overflow-x:auto;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{border:1px solid var(--line);padding:9px 12px;text-align:left;vertical-align:top;min-width:80px}
th{background:#eaf1fb;white-space:nowrap}tr:nth-child(even){background:#fafcff}
img{display:block;max-width:100%;height:auto;border:1px solid var(--line);border-radius:8px;margin:14px 0}li{margin:6px 0}
.diagram{margin:20px 0;text-align:center;break-inside:avoid}
.diagram svg{display:block;width:100%;max-width:100%;height:auto;margin:0 auto}
.diagram-fallback{text-align:left}.figure-note{color:var(--muted);font-size:13px}
footer{text-align:center;font-size:13px;color:var(--muted);padding:24px}
.toolbar{margin-top:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.toolbar input{padding:8px;border:1px solid #afc1d8;border-radius:6px;min-width:240px}
.toolbar button{border:1px solid #a9bddb;background:#fff;border-radius:6px;padding:7px 14px;cursor:pointer;color:#234d82}
.toolbar a{color:#e5efff;font-size:14px}
@media(max-width:980px){.layout{grid-template-columns:1fr;padding:12px}nav{position:static;max-height:240px}main{padding:20px}input{min-width:0;width:100%}}
@media print{header,nav,.toolbar,footer{display:none}.layout{display:block;padding:0}main{border:0;padding:0}body{background:#fff;font-size:11pt}h2,h3{break-after:avoid}.table-scroll{overflow:visible}table{font-size:9pt}pre{white-space:pre-wrap}figure,tr{break-inside:avoid}}
"""


def find_mmdc(cli_value: str | None, env_value: str | None) -> str | None:
    candidate = cli_value or env_value
    if candidate:
        return candidate
    return shutil.which("mmdc")


def build(md_path: Path, out_path: Path, *, svg_dir: Path | None, mmdc: str | None,
          puppeteer: Path | None, timeout: int, enabled: bool) -> MermaidRenderer:
    renderer = MermaidRenderer(svg_dir, mmdc, puppeteer, timeout, enabled)
    body, headings = render_markdown(md_path.read_text(encoding="utf-8-sig"), renderer)
    title = headings[0][1] if headings else md_path.stem
    toc = "".join(
        f'<a class="level-{level}" href="#{anchor}">{html.escape(label)}</a>'
        for level, label, anchor in headings
        if level in {2, 3}
    )
    notes = ""
    if renderer.messages:
        items = "".join(f"<li>{html.escape(m)}</li>" for m in renderer.messages[:10])
        notes = f'<div class="note-block"><p class="figure-note">Mermaid 渲染失败明细：</p><ul>{items}</ul></div>'
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{STYLE}</style></head>
<body><header><strong>{html.escape(title)}</strong><p>后端技术文档 · 与 Markdown 同源 · 离线可读</p>
<div class="toolbar"><a href="{html.escape(md_path.name, quote=True)}">查看 Markdown 原文</a>
<button type="button" onclick="window.print()">打印 / 保存 PDF</button>
<input id="search" type="search" placeholder="查找文档文字（回车）" aria-label="查找文档文字">
<button type="button" id="find">查找下一处</button></div></header>
<div class="layout"><nav aria-label="文档目录"><strong>文档目录</strong>{toc}</nav><main>{body}{notes}</main></div>
<footer>由同一份 Markdown 生成 · 图表内联 SVG · 不依赖 CDN</footer>
<script>function findText(){{const q=document.getElementById('search').value.trim();if(q&&window.find)window.find(q,false,false,true);}}
document.getElementById('find').addEventListener('click',findText);
document.getElementById('search').addEventListener('keydown',e=>{{if(e.key==='Enter')findText();}});</script>
</body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError("HTML 未成功生成")
    return renderer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("markdown", type=Path, help="技术文档 Markdown 路径")
    parser.add_argument("--output", type=Path, help="HTML 输出路径，默认与 Markdown 同目录同名")
    parser.add_argument("--svg-dir", type=Path, help="预渲染 SVG 目录（b01.svg、b02.svg … 与代码块顺序一致）")
    parser.add_argument("--mmdc", help="mermaid-cli 可执行文件，默认取 .agents/.env 的 MMDC_PATH 或 PATH")
    parser.add_argument("--puppeteer-config", type=Path, help="puppeteer 配置 JSON，用于指定本机 Chrome")
    parser.add_argument("--timeout", type=int, default=90, help="单张图渲染超时秒数，默认 90")
    parser.add_argument("--work-dir", default=None, help=".agents/.env 所在目录，默认当前目录")
    parser.add_argument("--no-mermaid", action="store_true", help="不渲染 Mermaid，保留源码块")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的 HTML")
    args = parser.parse_args()

    source = args.markdown.resolve()
    if not source.is_file():
        print(f"ERROR 未找到 Markdown：{source}")
        return 1
    target = (args.output or source.with_suffix(".html")).resolve()
    if target == source:
        print("ERROR HTML 输出路径不能与 Markdown 相同")
        return 1
    if target.exists() and not args.force:
        print(f"ERROR HTML 已存在，如需覆盖请加 --force：{target}")
        return 1

    work_dir = Path(args.work_dir).resolve() if args.work_dir else Path.cwd()
    env_map = load_agent_env(work_dir)
    mmdc = None if args.no_mermaid else find_mmdc(args.mmdc, env_map.get("MMDC_PATH"))
    puppeteer = args.puppeteer_config
    chrome = env_map.get("CHROME_PATH")
    if puppeteer is None and chrome:
        tmp_cfg = Path(tempfile.mkdtemp(prefix="techdoc-pptr-")) / "puppeteer.json"
        tmp_cfg.write_text(json.dumps({"executablePath": chrome, "args": ["--no-sandbox"]}), encoding="utf-8")
        puppeteer = tmp_cfg

    renderer = build(
        source,
        target,
        svg_dir=args.svg_dir.resolve() if args.svg_dir else None,
        mmdc=mmdc,
        puppeteer=puppeteer,
        timeout=args.timeout,
        enabled=not args.no_mermaid,
    )
    renderer.cleanup()
    print(f"Markdown: {source}")
    print(f"HTML: {target}")
    print(f"mermaid_mode={renderer.mode} mermaid_blocks={renderer.index} failures={renderer.failures}")
    if renderer.failures:
        print("WARN 存在未渲染图，HTML 中已保留 Mermaid 源码并给出提示")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
