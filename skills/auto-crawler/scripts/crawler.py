#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["scrapling[fetchers,shell]==0.5.1"]
# ///
"""Scrapling CLI: fetch one page or crawl bounded same-origin links.

Usage: uv run crawler.py fetch URL --field title=h1::text
       uv run crawler.py crawl URL --links 'li.next a::attr(href)' --max-pages 3
Dependencies: PEP 723, Python 3.10+, uv; browser mode requires `scrapling install`.
stdout: one JSON object; logs: stderr. Exit 0 success, 1 runtime/partial, 2 input error.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from xml.etree import ElementTree as ET


class InputError(ValueError):
    """Invalid user input; safe to display."""


def url_checked(url: str) -> str:
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username or parts.password or any(c.isspace() for c in url):
            raise ValueError
        _ = parts.port
    except ValueError:
        raise InputError("URL must be HTTP(S), with a host and no credentials/whitespace") from None
    return urldefrag(url)[0]


def origin(url: str) -> tuple[str, str, int]:
    p = urlsplit(url_checked(url))
    return p.scheme, p.hostname.lower(), p.port or (443 if p.scheme == "https" else 80)


def positive(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return result


def fields_checked(values: list[str]) -> dict[str, str]:
    fields = {}
    for value in values:
        name, sep, selector = value.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not selector.strip():
            raise InputError("--field requires NAME=CSS or NAME=xpath:EXPRESSION")
        if name in fields or name == "_url":
            raise InputError("field names must be unique; _url is reserved")
        fields[name] = selector
    return fields


def select(node, expression: str):
    return node.xpath(expression[6:]) if expression.startswith("xpath:") else node.css(expression)


def extract(page, fields: dict[str, str], row: str | None) -> list[dict]:
    if not fields:
        return [{"_url": page.url, "title": page.css("title::text").get("") or "",
                 "content": page.markdown(main_content_only=True)}]
    nodes = select(page, row) if row else [page]
    return [{"_url": page.url, **{name: select(node, expr).get("") or ""
                               for name, expr in fields.items()}} for node in nodes]


def env_proxy(workdir: Path) -> str | None:
    # Proxy credentials must be provided explicitly by the invoking process.
    return os.environ.get("AUTO_CRAWLER_PROXY") or None


def csv_cell(value) -> str:
    value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def serialize(items: list[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(items, ensure_ascii=False, indent=2) + "\n"
    if fmt == "jsonl":
        return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    if fmt == "csv":
        buffer = io.StringIO(newline="")
        names = list(dict.fromkeys(key for item in items for key in item)) or ["_url"]
        writer = csv.DictWriter(buffer, fieldnames=names)
        writer.writeheader()
        writer.writerows({k: csv_cell(v) for k, v in item.items()} for item in items)
        return buffer.getvalue()
    if fmt == "xml":
        root = ET.Element("items")
        for item in items:
            element = ET.SubElement(root, "item")
            for key, value in item.items():
                # User field names are XML-safe; use named fields for arbitrary dictionary keys.
                child = ET.SubElement(element, "field", name=key)
                child.text = str(value)
        return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"
    if fmt == "md":
        sections = []
        for item in items:
            if "content" in item:
                sections.append(f"Source: {item['_url']}\n\n{item['content']}")
            else:
                sections.append("\n".join(f"- **{key}**: {value}" for key, value in item.items()))
        return "\n\n---\n\n".join(sections) + "\n"
    raise InputError("unsupported output format")


def output_path(args) -> Path:
    base = (args.workdir / ".agents" / "out" / "auto-crawler").resolve()
    path = Path(args.output).expanduser() if args.output else base / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + "." + args.format)
    if not path.is_absolute():
        path = args.workdir / path
    path = path.resolve()
    if path.exists():
        raise InputError("output already exists; choose a new file (no overwrite)")
    if path.suffix.lower() != "." + args.format:
        raise InputError("output extension must match --format")
    return path


def browser_options(args, proxy: str | None) -> dict:
    options = {"headless": not args.headful, "timeout": int(args.timeout * 1000),
               "network_idle": True, "solve_cloudflare": args.solve_cloudflare}
    if args.wait_selector:
        options["wait_selector"] = args.wait_selector
    if proxy:
        options["proxy"] = proxy
    return options


def fetch(args, fields, proxy) -> tuple[list[dict], dict]:
    from scrapling.fetchers import Fetcher, StealthyFetcher
    if args.engine == "http":
        page = Fetcher.get(args.url, timeout=args.timeout, retries=1, proxy=proxy,
                           follow_redirects=False)
    else:
        page = StealthyFetcher.fetch(args.url, **browser_options(args, proxy))
    if not 200 <= page.status < 300:
        raise RuntimeError(f"HTTP_{page.status}")
    if origin(page.url) != origin(args.url):
        raise RuntimeError("CROSS_ORIGIN_REDIRECT")
    return extract(page, fields, args.row), {"pages": 1, "http_status": page.status, "completed": True}


def crawl(args, fields, proxy) -> tuple[list[dict], dict]:
    from scrapling.fetchers import FetcherSession, AsyncStealthySession
    from scrapling.spiders import Spider

    class ConfiguredSpider(Spider):
        name = "auto_crawler"
        start_urls = [args.url]
        allowed_domains = {urlsplit(args.url).hostname}
        robots_txt_obey = True
        concurrent_requests = args.concurrency
        concurrent_requests_per_domain = args.concurrency
        download_delay = args.delay
        autothrottle_enabled = True
        autothrottle_start_delay = args.delay
        autothrottle_max_delay = max(60, args.delay)
        max_blocked_retries = 0
        logging_level = 30

        def __init__(self):
            self.seen = {args.url}
            self.errors = 0
            self.pages = 0
            self.empty_pages = 0
            super().__init__()

        def configure_sessions(self, manager):
            if args.engine == "http":
                session = FetcherSession(timeout=args.timeout, retries=1, proxy=proxy, follow_redirects=False)
            else:
                session = AsyncStealthySession(**browser_options(args, proxy))
            manager.add("default", session)

        async def on_error(self, request, error):
            self.errors += 1

        async def parse(self, response):
            self.pages += 1
            if not 200 <= response.status < 300 or origin(response.url) != origin(args.url):
                self.errors += 1
                return
            rows = extract(response, fields, args.row)
            if not rows:
                self.empty_pages += 1
            for item in rows:
                yield item
            if args.links:
                for href in select(response, args.links).getall():
                    try:
                        target = url_checked(urljoin(response.url, href))
                        same_origin = origin(target) == origin(args.url)
                    except (InputError, TypeError):
                        continue
                    if same_origin and target not in self.seen and len(self.seen) < args.max_pages:
                        self.seen.add(target)
                        yield response.follow(target, callback=self.parse)

    spider = ConfiguredSpider()
    result = spider.start()
    # A blocked robots request can yield no pages without on_error; never report this as success.
    incomplete = spider.errors > 0 or spider.pages == 0 or spider.empty_pages > 0
    return list(result.items), {"pages": spider.pages, "scheduled_pages": len(spider.seen),
                                "errors": spider.errors, "empty_pages": spider.empty_pages,
                                "completed": result.completed and not incomplete}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message)


def parser() -> argparse.ArgumentParser:
    root = Parser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("fetch", "crawl"):
        sub = commands.add_parser(name, help="single page" if name == "fetch" else "bounded same-origin crawl")
        sub.add_argument("url", help="HTTP(S) URL; credentials in URLs are rejected")
        sub.add_argument("--workdir", type=Path, default=Path.cwd(), help="runtime workspace; default cwd")
        sub.add_argument("--engine", choices=("http", "browser"), default="http")
        sub.add_argument("--row", help="CSS row selector, or xpath:EXPRESSION")
        sub.add_argument("--field", action="append", default=[], help="repeat NAME=CSS or NAME=xpath:EXPRESSION; first match per row")
        sub.add_argument("--format", choices=("json", "jsonl", "csv", "xml", "md"), default="json")
        sub.add_argument("--output", help="new output path; default .agents/out/auto-crawler/<unique>.<format>")
        sub.add_argument("--timeout", type=positive, default=30, help="seconds; default 30")
        sub.add_argument("--headful", action="store_true", help="show browser; browser engine only")
        sub.add_argument("--wait-selector", help="wait for CSS selector; browser engine only")
        sub.add_argument("--solve-cloudflare", action="store_true", help="explicit opt-in; authorized sites only")
        if name == "crawl":
            sub.add_argument("--links", help="CSS link::attr(href), or xpath:EXPRESSION; absent means seed only")
            sub.add_argument("--max-pages", type=int, default=20, help="max unique admitted URLs, default 20 (max 1000)")
            sub.add_argument("--concurrency", type=int, default=2, help="1..8, default 2")
            sub.add_argument("--delay", type=positive, default=1, help="per-domain seconds; default 1; robots/AutoThrottle may increase")
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        args.url = url_checked(args.url)
        args.workdir = args.workdir.resolve()
        fields = fields_checked(args.field)
        if args.row and not fields:
            raise InputError("--row requires at least one --field")
        if args.engine == "http" and (args.headful or args.wait_selector or args.solve_cloudflare):
            raise InputError("browser options require --engine browser")
        if args.command == "crawl" and not (1 <= args.max_pages <= 1000 and 1 <= args.concurrency <= 8):
            raise InputError("--max-pages must be 1..1000 and --concurrency 1..8")
        path = output_path(args)
        proxy = env_proxy(args.workdir)
        # Prevent third-party progress output from corrupting the JSON stdout contract.
        with contextlib.redirect_stdout(sys.stderr):
            items, stats = (fetch if args.command == "fetch" else crawl)(args, fields, proxy)
        payload = serialize(items, args.format)
        if not items:
            print(json.dumps({"status": "error", "error": {"message": "no records extracted", "hint": "Check robots.txt, HTTP status, row/field selectors or browser mode"}, "data": stats}))
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(payload)
        ok = stats["completed"]
        print(json.dumps({"status": "ok" if ok else "partial", "data": {"output": str(path), "records": len(items), **stats}}, ensure_ascii=False))
        return 0 if ok else 1
    except (InputError, FileExistsError) as error:
        message = str(error) if isinstance(error, InputError) else "output already exists"
        print(json.dumps({"status": "error", "error": {"message": message, "hint": "Check --help; choose valid input and a new output path"}}))
        return 2
    except Exception as error:
        # Exceptions can contain proxy credentials, cookies or full URLs. Do not echo them.
        print(json.dumps({"status": "error", "error": {"message": type(error).__name__, "hint": "Check selectors, network/TLS, robots.txt and browser installation; do not disable TLS validation"}}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
