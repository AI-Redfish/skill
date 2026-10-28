#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
read_docx.py — 提取 .docx 的纯文本（按段落与表格行输出），用于阅读需求文档/技术方案文档。

用法：
  python read_docx.py <文件.docx> [更多.docx ...]

仅依赖标准库。表格按 “R行号: [单元格, ...]” 输出，段落按 “P: 文本” 输出。
"""
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def para_text(p):
    return "".join(t.text or "" for t in p.iter(W + "t"))


def dump(path):
    print("=" * 20, path, "=" * 20)
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    ti = 0
    for child in body:
        tag = child.tag.replace(W, "")
        if tag == "p":
            txt = para_text(child).strip()
            if txt:
                print("P:", txt)
        elif tag == "tbl":
            ti += 1
            print("----- TABLE %d -----" % ti)
            for ri, tr in enumerate(child.findall(W + "tr")):
                cells = [para_text(tc).strip() for tc in tr.findall(W + "tc")]
                if any(cells):
                    print("R%d: %s" % (ri, cells))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: python read_docx.py <文件.docx> [...]")
    for p in sys.argv[1:]:
        dump(p)
