# check-doc.py — 技术文档结构自检（纯标准库，无第三方依赖）
# 覆盖：一级标题数量/顺序/禁用章节、状态机二级标题与图后说明、增量字典编码交叉校验、
#       重复状态字段扫描、悬空章节引用、非 MySQL 方言扫描、ER 实体与 SQL 表名对应。
# 用法:
#   uv run scripts/check-doc.py --md <doc.md>     # 推荐：uv 自动隔离运行
#   python scripts/check-doc.py --md <doc.md>     # 等价：纯标准库可直接运行
# 退出码: 0 = P0 检查全部通过（P1 项仅提示）；1 = 存在 P0 问题；2 = 输入问题。
# 本脚本只读文档，不修改文档；修改一律走主调用方。

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXPECTED_H1 = ["ER图", "增量SQL", "业务流程图", "数据流转图", "接口清单", "增量字典"]
FORBIDDEN_H1 = ["方案概述", "设计目标与原则", "背景", "收益", "风险", "排期", "迁移方案", "验收用例", "事务与并发"]

SEP_ROW = re.compile(r"^\|[\s:\-|]+\|\s*$")
DATA_ROW_5 = re.compile(r"^\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|\s*$")
DICT_CODE_TYPE = re.compile(r"\| `([A-Za-z][A-Za-z0-9]*)` \| [^|]+ \| (常量字典|全局字典|自定义字典) \|")
ENUM_HEADING = re.compile(r"^### ([A-Za-z][A-Za-z0-9]*)（")
DATA_ROW_3 = re.compile(r"^\|[^|]*\|[^|]*\|[^|]*\|\s*$")
STATUS_COL = re.compile(r"^\s+(\w*status\w*)\s+(varchar|tinyint|int|char)\b", re.IGNORECASE)
DIALECT = re.compile(r"kingbase|postgres|oracle|dm8|达梦|sqlserver|sql\s+server|方言|其他数据库", re.IGNORECASE)
ER_ENTITY = re.compile(r"^\s{4}[A-Z][A-Z0-9_]+ \{")
CREATE_TABLE = re.compile(r"^CREATE TABLE (\w+)", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description="技术文档结构自检")
    parser.add_argument("--md", required=True, help="被校验的技术文档路径")
    args = parser.parse_args()

    md_path = Path(args.md)
    if not md_path.is_file():
        print(f"ERROR doc not found: {args.md}")
        return 2
    lines = md_path.read_text(encoding="utf-8-sig").splitlines()

    exit_code = 0

    def fail(msg: str) -> None:
        nonlocal exit_code
        print(msg)
        exit_code = 1

    # ---------- 1. 一级标题数量 / 顺序 / 禁用章节 ----------
    h1 = []
    for i, line in enumerate(lines):
        m = re.match(r"^# (.+)$", line)
        if m:
            h1.append((i + 1, m.group(1).strip()))
    order_ok = "OK"
    if len(h1) != len(EXPECTED_H1):
        order_ok = "BAD"
        fail(f"H1_COUNT expected={len(EXPECTED_H1)} actual={len(h1)}")
    else:
        for i, (ln, text) in enumerate(h1):
            if text != EXPECTED_H1[i]:
                order_ok = "BAD"
                fail(f"H1_{i + 1} expected='{EXPECTED_H1[i]}' actual='{text}' line={ln}")
    forbidden_hits = 0
    for ln, text in h1:
        if text in FORBIDDEN_H1:
            forbidden_hits += 1
            fail(f"FORBIDDEN_H1 '{text}' line={ln}")
    print(f"h1_count={len(h1)} h1_order={order_ok} forbidden={forbidden_hits}")

    # ---------- 2. 状态机标题层级与图后说明 ----------
    state_count = bad_heading = bad_note = 0
    for i, line in enumerate(lines):
        if not re.match(r"^stateDiagram(-v2)?\s*$", line):
            continue
        state_count += 1
        h = i - 1
        while h >= 0 and not re.match(r"^#{1,6} ", lines[h]):
            h -= 1
        if h < 0 or not re.match(r"^## [^#]", lines[h]):
            bad_heading += 1
            fail(f"BAD_HEADING line={i + 1}")
        c = i + 1
        while c < len(lines) and not re.match(r"^```\s*$", lines[c]):
            c += 1
        n = c + 1
        while n < len(lines) and not lines[n].strip():
            n += 1
        if n >= len(lines) or not re.match(r"^(- |> )", lines[n]):
            bad_note += 1
            fail(f"BAD_NOTE line={i + 1}")
    print(f"state_diagrams={state_count} bad_headings={bad_heading} bad_notes={bad_note}")

    # ---------- 3. 增量字典编码交叉校验 ----------
    use_start = enum_start = -1
    for i, line in enumerate(lines):
        if re.match(r"^## 实体字段字典使用清单\s*$", line):
            use_start = i
        elif re.match(r"^## 字典枚举项\s*$", line):
            enum_start = i
    if use_start < 0 or enum_start < 0 or enum_start < use_start:
        fail(f"DICT_SECTION_MISSING useStart={use_start} enumStart={enum_start}（需要“## 实体字段字典使用清单”与“## 字典枚举项”且顺序正确）")
        print("dict usage_rows=0 usage_codes=0 enum_tables=0 missing_table=0 orphan_table=0 duplicate_table=0 type_invalid=0 empty_table=0")
    else:
        dict_end = len(lines)
        for i in range(enum_start + 1, len(lines)):
            if re.match(r"^# [^#]", lines[i]):
                dict_end = i
                break

        use_rows = 0
        use_codes: list[str] = []
        type_invalid = 0
        header_skipped = False
        for i in range(use_start + 1, enum_start):
            t = lines[i]
            if SEP_ROW.match(t):
                continue
            if DATA_ROW_5.match(t):
                if not header_skipped:
                    header_skipped = True
                    continue
                use_rows += 1
                m = DICT_CODE_TYPE.search(t)
                if m:
                    use_codes.append(m.group(1))
                else:
                    type_invalid += 1
                    fail(f"DICT_TYPE_INVALID line={i + 1}: {t.strip()}")

        enum_codes: list[str] = []
        empty_table = 0
        i = enum_start + 1
        while i < dict_end:
            line = lines[i]
            m = ENUM_HEADING.match(line)
            if m:
                code = m.group(1)
                enum_codes.append(code)
                j = i + 1
                items = 0
                item_header_skipped = False
                while j < dict_end and not lines[j].startswith("### "):
                    t = lines[j]
                    if not SEP_ROW.match(t) and DATA_ROW_3.match(t):
                        if not item_header_skipped:
                            item_header_skipped = True
                        else:
                            items += 1
                    j += 1
                if items == 0:
                    empty_table += 1
                    fail(f"DICT_EMPTY_TABLE {code} line={i + 1}")
                i = j
            elif line.startswith("### "):
                fail(f"DICT_ENUM_HEADING_FORMAT line={i + 1}: {line.strip()}（应为 `### 字典编码（字典名称）`）")
                i += 1
            else:
                i += 1

        u_set = sorted(set(use_codes))
        e_set = sorted(set(enum_codes))
        missing = [c for c in u_set if c not in e_set]
        orphan = [c for c in e_set if c not in u_set]
        dup = {c for c in enum_codes if enum_codes.count(c) > 1}
        for c in missing:
            fail(f"MISSING_TABLE {c}")
        for c in orphan:
            fail(f"ORPHAN_TABLE {c}")
        for c in sorted(dup):
            fail(f"DUPLICATE_TABLE {c} x{enum_codes.count(c)}")
        print(
            f"dict usage_rows={use_rows} usage_codes={len(u_set)} enum_tables={len(e_set)} "
            f"missing_table={len(missing)} orphan_table={len(orphan)} duplicate_table={len(dup)} "
            f"type_invalid={type_invalid} empty_table={empty_table}"
        )

    # ---------- 4. 重复状态字段扫描（列清单，需人工确认） ----------
    status_cols = [(i + 1, line.strip()) for i, line in enumerate(lines) if STATUS_COL.match(line)]
    print(f"status_field_candidates={len(status_cols)}")
    for ln, text in status_cols:
        print(f"  STATUS_COL {ln}: {text}")
    print("  # 人工确认：同实体不得存在取值一一对应的同义双状态字段；发现即合并（未发生用 NULL，页面显示 -，不落库），裁决写入冲突/采用口径段")

    # ---------- 5. 悬空章节引用扫描 ----------
    headings = {m.group(1).strip() for line in lines if (m := re.match(r"^#{1,6} (.+)$", line))}
    dangling = 0
    dq1, dq2 = "\u201C", "\u201D"  # 智能引号用码点构造
    ref_pattern = re.compile("见[" + dq1 + "《]([^" + dq2 + "》]+)[" + dq1 + dq2 + "》]")
    for i, line in enumerate(lines):
        for m in ref_pattern.finditer(line):
            if m.group(1) not in headings:
                dangling += 1
                fail(f"DANGLING line {i + 1}: {m.group(1)}")
    print(f"dangling_refs={dangling}")

    # ---------- 6. 非 MySQL 方言扫描 ----------
    dialect_hits = [(i + 1, line.strip()) for i, line in enumerate(lines) if DIALECT.search(line)]
    for ln, text in dialect_hits:
        fail(f"NON_MYSQL line={ln}: {text}")
    print(f"non_mysql_hits={len(dialect_hits)}")

    # ---------- 7. ER 实体与 SQL 表名对应（P1，复用/外部表除外） ----------
    er_set = sorted({line.strip().split(" ")[0] for line in lines if ER_ENTITY.match(line)})
    sql_set = sorted({m.group(1).upper() for line in lines if (m := CREATE_TABLE.match(line))})
    er_no_table = [t for t in er_set if t not in sql_set]
    table_no_er = [t for t in sql_set if t not in er_set]
    for t in er_no_table:
        print(f"  P1 ER_WITHOUT_TABLE {t}")
    for t in table_no_er:
        print(f"  P1 TABLE_WITHOUT_ER {t}")
    print(f"er_without_table={len(er_no_table)} table_without_er={len(table_no_er)} (P1，复用/外部表除外，人工确认)")

    print("RESULT " + ("PASS" if exit_code == 0 else "FAIL"))
    return exit_code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
