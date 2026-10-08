#!/usr/bin/env python3
"""断言收集与报告渲染（Python 版模板，随 init 落位到 <workspace>/assets/common/report.py）

用法：
    import report
    report.check("队列有消费者", s["consumers"] > 0, f"consumers={s['consumers']}")
    report.write_report("runs/<主题>/report-assert.md")
    sys.exit(1 if report.summary()["failed"] else 0)   # 非0=FAIL
证据要求见 skill 的 contracts/report-contract.md：L0 证据不算 PASS。
"""
from __future__ import annotations
import os

_results: list[dict] = []


def check(name: str, ok: bool, evidence: str = "") -> bool:
    """收集一条断言；ok=False 时 evidence 必须可复查（messageId/SQL 前后值/行数）。"""
    ok = bool(ok)
    _results.append({"name": name, "ok": ok, "evidence": str(evidence)})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {evidence}" if evidence else ""), flush=True)
    return ok


def summary() -> dict:
    failed = sum(1 for r in _results if not r["ok"])
    return {"total": len(_results), "passed": len(_results) - failed, "failed": failed}


def render() -> str:
    """渲染成 markdown 断言表（嵌入 report.md 的"结果矩阵"节）。"""
    s = summary()
    rows = [
        f"| {i + 1} | {r['name']} | {'PASS' if r['ok'] else 'FAIL'} |"
        f" {r['evidence'].replace('|', chr(92) + '|')} |"
        for i, r in enumerate(_results)
    ]
    return "\n".join([
        f"共 {s['total']} 项：PASS {s['passed']} / FAIL {s['failed']}", "",
        "| # | 测试点 | 结果 | 证据 |", "|---|---|---|---|", *rows,
    ])


def write_report(file_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(render() + "\n")
    return file_path
