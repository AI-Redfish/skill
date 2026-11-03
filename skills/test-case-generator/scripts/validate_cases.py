#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用例文档结构校验与 AC 覆盖检查。

用途：
    对按 test-case-generator/references/output-format.md 生成的用例 Markdown 文档做
    结构校验（编号唯一性/格式、必填列、枚举合法性）与 AC 覆盖率统计。
    校验规则与输出格式见文件内 CHECKS 说明；供 test-case-generator skill 第 4 步调用。

依赖：Python 3.9+ 纯标准库，无第三方依赖。
用法：
    python validate_cases.py --cases <用例文档.md> [--prd <PRD.md>] [--min-rate 100]
    输出 JSON 到 stdout；退出码：0=无 error 级问题，1=存在 error，2=文件/参数错误。

校验规则编号：
    E001 用例编号重复
    E002 用例编号格式不符（TC-<模块码>-<三位序号>）
    E003 必填列为空（用例编号/用例类型/优先级/前置条件/测试步骤/预期结果）
    E004 优先级非法（仅允许 P0/P1/P2）
    E005 用例类型非法（仅允许 正例/反例/边界/权限/其他）
    E006 未找到任何用例表格行（| TC- 开头）
    W001 关联AC 为空（建议补充映射）
    W002 预期结果疑似模糊（长度 < 6 字符或包含"功能正常/一切正常/运行正确"）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_COLS = ("用例编号", "用例类型", "优先级", "前置条件", "测试步骤", "预期结果")
VALID_PRIORITIES = {"P0", "P1", "P2"}
VALID_TYPES = {"正例", "反例", "边界", "权限", "其他"}
CASE_ID_PATTERN = re.compile(r"^TC-[A-Za-z0-9-]+-\d{3}$")
AC_PATTERN = re.compile(r"\bAC\d[0-9A-Za-z]*(?:-[0-9A-Za-z]+)*")
VAGUE_PATTERN = re.compile(r"功能正常|一切正常|运行正确|界面正常")


def _split_row(line: str) -> list[str]:
    """把 '| a | b |' 形式的表格行拆成单元格列表（去首尾空元素）。"""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def _is_separator_row(cells: list[str]) -> bool:
    """识别 |---|---| 分隔行。"""
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != "")


def parse_cases(doc_path: Path) -> tuple[list[dict], list[dict]]:
    """解析用例文档，返回 (用例行列表, issues)。

    表格识别：以包含"用例编号"与"预期结果"的表头行建立列映射，
    其后连续的 | TC- 开头行为用例；遇到非表格行则结束当前表（允许多表拼接）。
    """
    issues: list[dict] = []
    cases: list[dict] = []
    col_map: dict[str, int] | None = None
    section = ""
    try:
        lines = doc_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(json.dumps({"status": "error", "error": f"读取失败: {exc}"}, ensure_ascii=False))
        raise SystemExit(2)

    for line_no, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if stripped.startswith("###"):
            section = stripped.lstrip("#").strip()
            continue
        if not stripped.startswith("|"):
            # 离开表格区域后重置列映射（新表需重新识别表头）
            if not stripped:
                continue
            col_map = None
            continue
        cells = _split_row(stripped)
        if _is_separator_row(cells):
            continue
        joined = "".join(cells)
        if "用例编号" in joined and "预期结果" in joined:
            col_map = {name: idx for idx, name in enumerate(cells) if name}
            continue
        if col_map is None or not joined.startswith("TC-"):
            continue
        row = {name: (cells[idx] if idx < len(cells) else "") for name, idx in col_map.items()}
        row["_line"] = line_no
        row["_section"] = section
        cases.append(row)
    if not cases:
        issues.append({"code": "E006", "line": 0,
                       "message": "未找到任何用例表格行（应以 | TC- 开头，且存在含'用例编号'与'预期结果'的表头）"})
    return cases, issues


def validate(cases: list[dict]) -> list[dict]:
    """对解析出的用例行逐条校验，返回 issues。"""
    issues: list[dict] = []
    seen_ids: dict[str, int] = {}
    for row in cases:
        line = row.get("_line", 0)
        case_id = row.get("用例编号", "").strip()
        if not case_id:
            issues.append({"code": "E003", "line": line, "message": "用例编号为空"})
            continue
        if case_id in seen_ids:
            issues.append({"code": "E001", "line": line,
                           "message": f"用例编号重复：{case_id}（首次出现于第 {seen_ids[case_id]} 行）"})
        else:
            seen_ids[case_id] = line
        if not CASE_ID_PATTERN.fullmatch(case_id):
            issues.append({"code": "E002", "line": line,
                           "message": f"编号格式不符：{case_id}（应为 TC-<模块码>-<三位序号>）"})
        for col in REQUIRED_COLS:
            if not row.get(col, "").strip():
                issues.append({"code": "E003", "line": line, "message": f"必填列为空：{col}"})
        priority = row.get("优先级", "").strip()
        if priority and priority not in VALID_PRIORITIES:
            issues.append({"code": "E004", "line": line,
                           "message": f"优先级非法：{priority}（仅允许 P0/P1/P2）"})
        case_type = row.get("用例类型", "").strip()
        if case_type and case_type not in VALID_TYPES:
            issues.append({"code": "E005", "line": line,
                           "message": f"用例类型非法：{case_type}（仅允许 {'/'.join(sorted(VALID_TYPES))}）"})
        ac_refs = row.get("关联AC", "").strip()
        if not ac_refs:
            issues.append({"code": "W001", "line": line,
                           "message": f"用例 {case_id} 未关联 AC（建议补充映射或标注技术口径编号）"})
        expected = row.get("预期结果", "").strip()
        if expected and (len(expected) < 6 or VAGUE_PATTERN.search(expected)):
            issues.append({"code": "W002", "line": line,
                           "message": f"用例 {case_id} 预期结果疑似模糊断言：{expected[:30]}"})
    return issues


def coverage(cases: list[dict], prd_path: Path | None) -> dict | None:
    """统计 AC 覆盖率；无 PRD 时返回 None。"""
    if prd_path is None:
        return None
    try:
        prd_text = prd_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"status": "error", "error": f"PRD 读取失败: {exc}"}, ensure_ascii=False))
        raise SystemExit(2)
    ac_total = sorted({m.upper() for m in AC_PATTERN.findall(prd_text)})
    ac_covered = set()
    for row in cases:
        ac_covered.update(m.upper() for m in AC_PATTERN.findall(row.get("关联AC", "")))
    ac_missing = [ac for ac in ac_total if ac not in ac_covered]
    rate = round(100.0 * (len(ac_total) - len(ac_missing)) / len(ac_total), 1) if ac_total else None
    return {
        "acTotal": len(ac_total),
        "acCovered": len(ac_total) - len(ac_missing),
        "acMissing": ac_missing,
        "rate": rate,
    }


def main() -> None:
    # Windows 控制台默认 GBK，强制 UTF-8 保证中文 JSON 不乱码（下游用 utf-8 解码）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="用例文档结构校验与 AC 覆盖检查")
    parser.add_argument("--cases", required=True, help="用例 Markdown 文档路径")
    parser.add_argument("--prd", help="PRD Markdown 路径（提供时计算 AC 覆盖率）")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.is_file():
        print(json.dumps({"status": "error", "error": f"用例文档不存在: {cases_path}"}, ensure_ascii=False))
        raise SystemExit(2)
    prd_path = Path(args.prd) if args.prd else None
    if args.prd and not prd_path.is_file():
        print(json.dumps({"status": "error", "error": f"PRD 不存在: {prd_path}"}, ensure_ascii=False))
        raise SystemExit(2)

    cases, issues = parse_cases(cases_path)
    issues.extend(validate(cases))
    cov = coverage(cases, prd_path)

    errors = [i for i in issues if i["code"].startswith("E")]
    result = {
        "status": "ok" if not errors else "fail",
        "file": str(cases_path),
        "total": len(cases),
        "issueCount": {"error": len(errors), "warning": len(issues) - len(errors)},
        "issues": issues,
        "coverage": cov,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
