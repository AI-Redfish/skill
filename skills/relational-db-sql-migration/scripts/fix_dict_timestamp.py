#!/usr/bin/env python3
"""fix_dict_timestamp.py — 字典表 create_time/update_time 固定时间字面量定位修复。

将字典表（sys_dict_key / sys_dict_value / sys_tenant_dict_key / sys_tenant_dict_value /
zz_tenant_global_dict / zz_tenant_global_dict_item / zz_global_dict / zz_global_dict_item）
INSERT/REPLACE/UPDATE 语句中 create_time、update_time 列位置上的固定时间字面量
（如 '2026-10-14 10:00:00'、20261014）定位并替换为 CURRENT_TIMESTAMP（运行时时间）。
逻辑与 scripts/ci/dict-timestamp-check.awk 的判定对齐：
  - 只处理目标表为字典表、且显式列出字段清单的语句；
  - 只替换 create_time/update_time 列位置上的字面量，不做整行盲替换；
  - 语句扫描以分号边界为界，不跨语句；覆盖 VALUES 行、SELECT 字段列表（含 UNION）、
    INSERT...SET、ON DUPLICATE KEY UPDATE、UPDATE SET（含 MySQL 多表与
    Kingbase `UPDATE ... SET ... FROM ... WHERE` 语法）。

用法:
  python3 fix_dict_timestamp.py [--apply] [--json] [--tables a,b,c]
                                [--tables-file FILE] <file> [<file> ...]
  默认 dry-run（只报告不落盘）；--apply 才写回文件。
  文件以字节透明方式读写（latin1），编码与行尾（CRLF/LF）保持不变。

依赖: 仅 Python 3.9+ 标准库（uv run / python 直跑均可）。
退出码: 0=成功（无待修复项或已应用）；1=dry-run 发现待修复项；
        2=用法或输入错误；3=内部一致性断言失败（不应发生，请报告）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_TABLES = (
    "sys_dict_key",
    "sys_dict_value",
    "sys_tenant_dict_key",
    "sys_tenant_dict_value",
    "zz_tenant_global_dict",
    "zz_tenant_global_dict_item",
    "zz_global_dict",
    "zz_global_dict_item",
)
TIME_COLS = {"create_time", "update_time"}
REPL = "CURRENT_TIMESTAMP"
# 赋值右值结束关键字（顶层出现即终止）。必须包含 from：
# Kingbase/PG 的 `UPDATE ... SET c='lit' FROM (...) t WHERE ...` 若缺少 from，
# 右值区间会吞掉整个 FROM 子句，替换时造成整块删除（实战踩坑）。
VALUE_STOP_WORDS = {"where", "from", "order", "limit", "returning", "group", "having", "union", "on"}
SELECT_LIST_END_WORDS = {"from", "where", "union", "group", "order", "limit", "having", "into", "window", "returning"}
INSERT_MODIFIERS = {"ignore", "low_priority", "delayed", "high_priority", "into"}
SELECT_MODIFIERS = ("distinct", "all", "sql_calc_found_rows", "high_priority", "straight_join", "sql_no_cache", "sql_cache")
WORD_OK = set("A-Za-z0-9_$")


def _is_word_char(c: str) -> bool:
    return c.isalnum() and c.isascii() or c in ("_", "$")


def normalize_name(s: str) -> str:
    x = "".join(ch for ch in s.lower() if ch not in '`" \t\r\n')
    if "." in x:
        x = x.rsplit(".", 1)[1]
    return x


def is_ws(c: str) -> bool:
    return c in " \t\r\n"


def skip_quoted(t: str, i: int) -> int:
    """t[i] 为引号；返回结束引号之后的位置（MySQL 反斜杠转义、双写引号均处理）。"""
    q = t[i]
    j = i + 1
    n = len(t)
    while j < n:
        c = t[j]
        if c == "\\":
            j += 2
            continue
        if c == q:
            if j + 1 < n and t[j + 1] == q:
                j += 2
                continue
            return j + 1
        j += 1
    return j


def skip_misc(t: str, i: int, end: int) -> int:
    """跳过空白与注释（-- 行注释、# 行注释、/* */ 块注释）。"""
    while i < end:
        c = t[i]
        nxt = t[i + 1] if i + 1 < len(t) else ""
        if is_ws(c):
            i += 1
            continue
        if c == "-" and nxt == "-":
            while i < end and t[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            e = t.find("*/", i + 2)
            i = end if e < 0 or e >= end else e + 2
            continue
        if c == "#" and (i == 0 or t[i - 1] in " \t") and nxt != ">":
            while i < end and t[i] != "\n":
                i += 1
            continue
        break
    return i


def read_word(t: str, i: int) -> tuple[int, str]:
    j = i
    n = len(t)
    while j < n and (_is_word_char(t[j])):
        j += 1
    return j, t[i:j]


def read_token(t: str, i: int) -> tuple[int, str]:
    """标识符 / 反引号或双引号标识符（去引号）/ 单字符 token。"""
    i = skip_misc(t, i, len(t))
    if i >= len(t):
        return i, ""
    c = t[i]
    if c in "`\"":
        j = i + 1
        out = []
        while j < len(t):
            if t[j] == c:
                if j + 1 < len(t) and t[j + 1] == c:
                    out.append(c)
                    j += 2
                    continue
                j += 1
                break
            out.append(t[j])
            j += 1
        return j, "".join(out)
    if _is_word_char(c):
        return read_word(t, i)
    return i + 1, c


def match_paren(t: str, i: int, end: int) -> int:
    """t[i]='('；返回配对 ')' 之后的位置，失败返回 -1。"""
    depth = 0
    j = i
    while j < end:
        c = t[j]
        if c in "'\"`":
            j = skip_quoted(t, j)
            continue
        if c == "-" and j + 1 < end and t[j + 1] == "-":
            while j < end and t[j] != "\n":
                j += 1
            continue
        if c == "/" and j + 1 < end and t[j + 1] == "*":
            e = t.find("*/", j + 2)
            j = end if e < 0 or e >= end else e + 2
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def split_top_level(t: str, s: int, e: int) -> list[tuple[int, int]]:
    """顶层逗号切分，返回各单元格 [start, end) 偏移（引号/括号/注释感知）。"""
    out: list[tuple[int, int]] = []
    depth = 0
    start = s
    i = s
    while i < e:
        c = t[i]
        if c in "'\"`":
            i = skip_quoted(t, i)
            continue
        if c == "-" and i + 1 < e and t[i + 1] == "-":
            nl = t.find("\n", i)
            if nl < 0 or nl >= e:
                break
            i = nl + 1
            continue
        if c == "/" and i + 1 < e and t[i + 1] == "*":
            ce = t.find("*/", i + 2)
            if ce < 0 or ce >= e:
                break
            i = ce + 2
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            out.append((start, i))
            start = i + 1
        i += 1
    out.append((start, e))
    return out


def trim_span(t: str, s: int, e: int) -> tuple[int, int]:
    while s < e and is_ws(t[s]):
        s += 1
    while e > s and is_ws(t[e - 1]):
        e -= 1
    return s, e


def line_of(t: str, abs_pos: int) -> int:
    return t.count("\n", 0, abs_pos) + 1


def value_end(t: str, pos: int, end: int) -> int:
    """赋值右值结束位置：顶层逗号或子句关键字（见 VALUE_STOP_WORDS）。"""
    depth = 0
    p = pos
    while p < end:
        c = t[p]
        if c in "'\"`":
            p = skip_quoted(t, p)
            continue
        if c == "-" and p + 1 < end and t[p + 1] == "-":
            while p < end and t[p] != "\n":
                p += 1
            continue
        if c == "/" and p + 1 < end and t[p + 1] == "*":
            e2 = t.find("*/", p + 2)
            p = end if e2 < 0 or e2 >= end else e2 + 2
            continue
        if c == "(":
            depth += 1
            p += 1
            continue
        if c == ")":
            depth -= 1
            p += 1
            continue
        if depth == 0:
            if c == ",":
                return p
            if c.isalpha() and c.isascii():
                e2, w = read_word(t, p)
                if w.lower() in VALUE_STOP_WORDS:
                    return p
                p = e2
                continue
        p += 1
    return end


def is_literal_time(v: str) -> bool:
    """判定值是否为固定时间字面量（对齐 awk is_literal_time）。"""
    x = v.strip()
    while len(x) > 1 and x[0] == "(":
        m = match_paren(x, 0, len(x))
        if m == len(x):
            x = x[1:m - 1].strip()
        else:
            break
    if not x:
        return False
    low = x.lower()
    if low == "null":
        return False
    if re.search(r"current_timestamp|current_date|current_time|localtimestamp|localtime|sysdate|clock_timestamp|statement_timestamp|transaction_timestamp|timeofday", low):
        return False
    if re.search(r"now[ \t]*\(", low) or re.search(r"getdate[ \t]*\(", low):
        return False
    if re.search(r"unix_timestamp[ \t]*\([ \t]*\)", low):
        return False
    if re.fullmatch(r"[-+]?[0-9]+([.][0-9]+)?", x):
        return True  # 纯数值（含 20261014 这类整型时间；与 awk 一致：不剥引号）
    if re.search(r"'[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}", x):
        return True
    if re.search(r"'[0-9]{8}([0-9]{6})?'", x):
        return True
    if re.search(r"'[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?", x):
        return True
    return False


def split_statements(t: str) -> list[tuple[int, int]]:
    """按分号切出语句区间（引号/注释/$$ 美元引用感知），返回 [start, end) 列表。"""
    stmts: list[tuple[int, int]] = []
    in_sq = in_dq = in_bt = in_line = in_block = in_dollar = False
    start = -1
    i = 0
    n = len(t)

    def begin(j: int) -> None:
        nonlocal start
        if start < 0:
            start = j

    while i < n:
        c = t[i]
        nxt = t[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_dollar:
            if c == "$" and nxt == "$":
                in_dollar = False
                i += 2
                continue
            i += 1
            continue
        if in_sq:
            begin(i)
            if c == "\\":
                i += 2
                continue
            if c == "'":
                if nxt == "'":
                    i += 2
                    continue
                in_sq = False
            i += 1
            continue
        if in_dq:
            begin(i)
            if c == "\\":
                i += 2
                continue
            if c == '"':
                if nxt == '"':
                    i += 2
                    continue
                in_dq = False
            i += 1
            continue
        if in_bt:
            begin(i)
            if c == "`":
                in_bt = False
            i += 1
            continue
        if c == "-" and nxt == "-":
            in_line = True
            i += 2
            continue
        if c == "#" and (i == 0 or t[i - 1] in " \t") and nxt != ">":
            in_line = True
            i += 1
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == "$" and nxt == "$":
            begin(i)
            in_dollar = True
            i += 2
            continue
        if c == "'":
            begin(i)
            in_sq = True
            i += 1
            continue
        if c == '"':
            begin(i)
            in_dq = True
            i += 1
            continue
        if c == "`":
            begin(i)
            in_bt = True
            i += 1
            continue
        if c == ";":
            if start >= 0:
                stmts.append((start, i))
            start = -1
            i += 1
            continue
        if not is_ws(c):
            begin(i)
        i += 1
    if start >= 0:
        stmts.append((start, n))
    return stmts


def parse_table_ref(t: str, i: int, end: int) -> tuple[int, str | None]:
    p = skip_misc(t, i, end)
    if p >= end:
        return -1, None
    e, tok = read_token(t, p)
    if not tok or not (tok[0].isalnum() and tok[0].isascii() or tok[0] in '`"_'):
        return -1, None
    name = normalize_name(tok)
    while True:
        p = skip_misc(t, e, end)
        if p >= end or t[p] != ".":
            break
        e, tok = read_token(t, p + 1)
        if not tok:
            break
        name = normalize_name(tok)
    return e, name


def check_assignments(t: str, pos: int, end: int, edits: list, log: list[str]) -> None:
    """SET / ON DUPLICATE KEY UPDATE 赋值列表（有界 [pos, end)）。"""
    p = pos
    while p < end:
        p = skip_misc(t, p, end)
        if p >= end:
            return
        e, col = read_token(t, p)
        col = normalize_name(col)
        if not col or not (col[0].isalnum() and col[0].isascii() or col[0] in "_"):
            return
        dot = skip_misc(t, e, end)
        if dot < end and t[dot] == ".":
            e, col = read_token(t, dot + 1)
            col = normalize_name(col)
        e = skip_misc(t, e, end)
        if e >= end or t[e] != "=":
            return
        vs = skip_misc(t, e + 1, end)
        ve = value_end(t, vs, end)
        s2, e2 = trim_span(t, vs, ve)
        val = t[s2:e2]
        if col in TIME_COLS and is_literal_time(val):
            if "\r" in val or "\n" in val:
                raise ConsistencyError(f"SET 值区间含换行 L{line_of(t, s2)}: {val[:80]!r}")
            edits.append((s2, e2))
            log.append(f"L{line_of(t, s2)} SET {col} = {val}")
        p = ve
        p = skip_misc(t, p, end)
        if p < end and t[p] == ",":
            p += 1
            continue
        return


def check_select_lists(t: str, pos: int, end: int, time_idx: dict, edits: list, log: list[str]) -> None:
    """INSERT...SELECT 的字段列表（含 UNION 分支），有界 [pos, end)。"""
    depth = 0
    p = pos
    while p < end:
        c = t[p]
        if c in "'\"`":
            p = skip_quoted(t, p)
            continue
        if c == "-" and p + 1 < end and t[p + 1] == "-":
            while p < end and t[p] != "\n":
                p += 1
            continue
        if c == "/" and p + 1 < end and t[p + 1] == "*":
            e = t.find("*/", p + 2)
            p = end if e < 0 or e >= end else e + 2
            continue
        if c == "(":
            depth += 1
            p += 1
            continue
        if c == ")":
            depth -= 1
            p += 1
            continue
        if depth == 0 and c.isalpha() and c.isascii():
            e, w0 = read_word(t, p)
            if w0.lower() == "select":
                # 字段列表结束位置（有界）
                d2 = 0
                q = e
                list_end = end
                while q < end:
                    c2 = t[q]
                    if c2 in "'\"`":
                        q = skip_quoted(t, q)
                        continue
                    if c2 == "-" and q + 1 < end and t[q + 1] == "-":
                        while q < end and t[q] != "\n":
                            q += 1
                        continue
                    if c2 == "/" and q + 1 < end and t[q + 1] == "*":
                        x = t.find("*/", q + 2)
                        q = end if x < 0 or x >= end else x + 2
                        continue
                    if c2 == "(":
                        d2 += 1
                        q += 1
                        continue
                    if c2 == ")":
                        d2 -= 1
                        q += 1
                        continue
                    if d2 == 0 and c2.isalpha() and c2.isascii():
                        e2, w2 = read_word(t, q)
                        if w2.lower() in SELECT_LIST_END_WORDS:
                            list_end = q
                            break
                        q = e2
                        continue
                    q += 1
                # 去掉前导空白与 SELECT 修饰词
                ls = e
                while ls < list_end and is_ws(t[ls]):
                    ls += 1
                changed = True
                while changed:
                    changed = False
                    for mod in SELECT_MODIFIERS:
                        if t[ls:list_end].lower().startswith(mod) and (
                            ls + len(mod) >= list_end or is_ws(t[ls + len(mod)])
                        ):
                            ls += len(mod)
                            while ls < list_end and is_ws(t[ls]):
                                ls += 1
                            changed = True
                            break
                cells = split_top_level(t, ls, list_end)
                for k in sorted(time_idx):
                    if k > len(cells):
                        continue
                    cs, ce = trim_span(t, cells[k - 1][0], cells[k - 1][1])
                    val = t[cs:ce]
                    if is_literal_time(val):
                        if "\r" in val or "\n" in val:
                            raise ConsistencyError(f"SELECT 值区间含换行: {val[:80]!r}")
                        edits.append((cs, ce))
                        log.append(f"L{line_of(t, cs)} SELECT#{k} {time_idx[k]} = {val}")
                p = list_end
                continue
            p = e
            continue
        p += 1


def analyze_insert(t: str, s: int, e: int, dicts: set, edits: list, log: list[str]) -> None:
    p = skip_misc(t, s, e)
    x, kw = read_word(t, p)
    kw = kw.lower()
    p = x  # 先推进过 INSERT/REPLACE 关键字
    while True:
        p = skip_misc(t, p, e)
        x, kw = read_token(t, p)
        kw = kw.lower()
        if not kw or not (kw[0].isalpha() and kw[0].isascii()):
            # 表名 token（可能是反引号/双引号包裹）：交由 parse_table_ref 处理
            break
        if kw in INSERT_MODIFIERS:
            p = x
            continue
        break
    te, table = parse_table_ref(t, p, e)
    if te < 0 or table not in dicts:
        return
    time_idx: dict = {}
    p = skip_misc(t, te, e)
    if p < e and t[p] == "(":
        pe = match_paren(t, p, e)
        if pe < 0:
            return
        for idx, (cs, ce) in enumerate(split_top_level(t, p + 1, pe - 1), start=1):
            col = normalize_name(t[cs:ce])
            if col in TIME_COLS:
                time_idx[idx] = col
        p = pe
    else:
        return  # 未显式列出字段，无法按位置定位（对齐 awk）
    p = skip_misc(t, p, e)
    x, kw = read_word(t, p)
    kw = kw.lower()
    if kw == "values":
        p = x
        while True:
            p = skip_misc(t, p, e)
            if p >= e or t[p] != "(":
                break
            pe = match_paren(t, p, e)
            if pe < 0:
                break
            cells = split_top_level(t, p + 1, pe - 1)
            for k in sorted(time_idx):
                if k > len(cells):
                    continue
                cs, ce = trim_span(t, cells[k - 1][0], cells[k - 1][1])
                val = t[cs:ce]
                if is_literal_time(val):
                    if "\r" in val or "\n" in val:
                        raise ConsistencyError(f"VALUES 值区间含换行: {val[:80]!r}")
                    edits.append((cs, ce))
                    log.append(f"L{line_of(t, cs)} VALUES#{k} {time_idx[k]} = {val}")
            p = pe
            p = skip_misc(t, p, e)
            if p < e and t[p] == ",":
                p += 1
                continue
            break
        tail = t[p:e].lower()
        q = tail.find("on duplicate key update")
        if q >= 0:
            check_assignments(t, p + q + len("on duplicate key update"), e, edits, log)
    elif kw == "select":
        check_select_lists(t, p, e, time_idx, edits, log)
    elif kw == "set":
        check_assignments(t, x, e, edits, log)


def analyze_update(t: str, s: int, e: int, dicts: set, edits: list, log: list[str]) -> None:
    p = skip_misc(t, s, e)
    x, kw = read_word(t, p)
    kw = kw.lower()
    p = x  # 先推进过 UPDATE 关键字
    if kw in ("low_priority", "ignore"):
        p = skip_misc(t, p, e)
        x, _ = read_word(t, p)
        p = x
    te, table = parse_table_ref(t, p, e)
    if te < 0 or table not in dicts:
        return
    depth = 0
    q = te
    while q < e:
        c = t[q]
        if c in "'\"`":
            q = skip_quoted(t, q)
            continue
        if c == "-" and q + 1 < e and t[q + 1] == "-":
            while q < e and t[q] != "\n":
                q += 1
            continue
        if c == "/" and q + 1 < e and t[q + 1] == "*":
            x2 = t.find("*/", q + 2)
            q = e if x2 < 0 or x2 >= e else x2 + 2
            continue
        if c == "(":
            depth += 1
            q += 1
            continue
        if c == ")":
            depth -= 1
            q += 1
            continue
        if depth == 0 and c.isalpha() and c.isascii():
            e2, w = read_word(t, q)
            if w.lower() == "set":
                check_assignments(t, e2, e, edits, log)
                return
            q = e2
            continue
        q += 1


class ConsistencyError(Exception):
    """内部一致性断言失败（编辑区间非法等）。"""


def find_edits(t: str, dicts: set) -> tuple[list[tuple[int, int]], list[str]]:
    """返回（编辑区间列表, 日志列表）。区间按文件偏移升序、互不重叠。"""
    edits: list[tuple[int, int]] = []
    log: list[str] = []
    for ss, se in split_statements(t):
        p = skip_misc(t, ss, se)
        if p >= se:
            continue
        _, w0 = read_word(t, p)
        kw = w0.lower()
        if kw in ("insert", "replace"):
            analyze_insert(t, ss, se, dicts, edits, log)
        elif kw == "update":
            analyze_update(t, ss, se, dicts, edits, log)
    edits.sort()
    for a, b in zip(edits, edits[1:]):
        if b[0] < a[1]:
            raise ConsistencyError(f"编辑区间重叠: {a} vs {b}")
    return edits, log


def apply_edits(t: str, edits: list[tuple[int, int]]) -> str:
    for s2, e2 in edits:
        if "\r" in t[s2:e2] or "\n" in t[s2:e2]:
            raise ConsistencyError("编辑区间包含换行符")
    out = t
    for s2, e2 in reversed(edits):
        out = out[:s2] + REPL + out[e2:]
    if out.count("\n") != t.count("\n"):
        raise ConsistencyError("替换前后总行数不一致")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="字典表 create_time/update_time 固定时间字面量定位修复")
    ap.add_argument("files", nargs="+", help="待处理 SQL 文件（字节透明，行尾/编码不变）")
    ap.add_argument("--apply", action="store_true", help="写回文件（默认 dry-run 只报告）")
    ap.add_argument("--json", action="store_true", help="结果以 JSON 输出到 stdout")
    ap.add_argument("--tables", default=",".join(DEFAULT_TABLES), help="逗号分隔的字典表清单")
    ap.add_argument("--tables-file", help="从文件读取字典表清单（每行一个，# 注释）")
    args = ap.parse_args(argv)

    tables = set(filter(None, (normalize_name(x) for x in args.tables.split(","))))
    if args.tables_file:
        tf = Path(args.tables_file)
        if not tf.is_file():
            msg = f"字典表清单不存在: {tf}；请检查 --tables-file 路径"
            (print(json.dumps({"status": "error", "error": {"message": msg}})) if args.json else print(msg, file=sys.stderr))
            return 2
        lines = tf.read_text(encoding="utf-8").splitlines()
        tables = set(filter(None, (normalize_name(l.split("#", 1)[0].strip()) for l in lines)))
    if not tables:
        print("字典表清单为空；请检查 --tables / --tables-file", file=sys.stderr)
        return 2

    files = [Path(f) for f in args.files]
    for f in files:
        if not f.is_file():
            msg = f"文件不存在: {f}；请确认相对/绝对路径"
            (print(json.dumps({"status": "error", "error": {"message": msg}})) if args.json else print(msg, file=sys.stderr))
            return 2

    total = 0
    report = []
    for f in files:
        t = f.read_bytes().decode("latin-1")
        try:
            edits, log = find_edits(t, tables)
        except ConsistencyError as exc:
            msg = f"{f}: 内部一致性断言失败: {exc}；请缩减用例并反馈"
            (print(json.dumps({"status": "error", "error": {"message": msg}})) if args.json else print(msg, file=sys.stderr))
            return 3
        if edits:
            detail = {"file": str(f), "count": len(edits), "lines": sorted({int(l.split("L")[1].split(" ")[0]) for l in log})}
            report.append(detail)
            if args.json:
                pass
            else:
                print(f"{f}: {len(edits)} 处")
                for l in log:
                    print("  " + l)
            total += len(edits)
            if args.apply:
                out = apply_edits(t, edits)
                f.write_bytes(out.encode("latin-1"))

    if args.json:
        print(json.dumps({"status": "ok", "data": {"total": total, "files": report, "applied": bool(args.apply)}}, ensure_ascii=False))
    else:
        print(f"{'已修改' if args.apply else '（dry-run）'}共 {total} 处")
    return 1 if (total and not args.apply) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
