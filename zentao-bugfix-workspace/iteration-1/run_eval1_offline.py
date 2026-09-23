#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iteration-1 eval-1：分析先行流程（脚本级端到端，离线）。

不连禅道：直接驱动 bugfix.py 的 scaffold_analysis / analysis_complete_status，
模拟「prepare 生成骨架 → 未补全时 report 校验为 yes → AI 补全 → 校验为 no」
的完整流转，并验证骨架含分析先行提示。输出 grading.json。
"""
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "zentao-bugfix"
spec = importlib.util.spec_from_file_location("bugfix", SKILL / "scripts" / "bugfix.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)

t0 = time.time()
results = []


def check(text, fn):
    try:
        ev = fn()
    except Exception as e:  # noqa: BLE001
        ev = "EXCEPTION: %r" % e
    results.append({"text": text, "passed": not str(ev).startswith(("FAIL", "EXCEPTION")),
                    "evidence": str(ev)})


info = {
    "report_dir": "", "date": "20260923", "base_branch": "main",
    "head_short": "abc1234", "branch": "bugfix/99901_20260923", "wt_path": "/tmp/x",
}

with tempfile.TemporaryDirectory() as td:
    rd = Path(td) / ".agents" / "bugfix" / "99901"
    rd.mkdir(parents=True)
    info["report_dir"] = str(rd)

    # 1) prepare 阶段：生成骨架，含分析先行提示与（待填写）标记
    p = bf.scaffold_analysis({"title": "登录报错"}, [], [], dict(info),
                             "http://zentao.example.com", "99901")
    text = Path(p).read_text(encoding="utf-8")
    check("prepare 生成的 analysis.md 骨架位于 worktree .agents 目录（report_dir 下）",
          lambda: "OK: %s" % p if ".agents" in p and "analysis.md" in p else "FAIL")
    check("骨架含「分析先行」流程要求提示（先补全报告再改代码）",
          lambda: "OK: 提示存在" if ("分析先行" in text and "之前" in text) else "FAIL: 无提示")
    check("骨架分析章节留（待填写）标记（供完成度检测）",
          lambda: "OK: %d 处" % text.count("（待填写）") if "（待填写）" in text else "FAIL")

    # 2) report 阶段（未补全）：校验为 yes
    check("report 校验：analysis.md 未补全 → ANALYSIS_INCOMPLETE=yes",
          lambda: "OK: %s" % bf.analysis_complete_status(str(rd))
          if bf.analysis_complete_status(str(rd)) == "yes" else "FAIL")

    # 3) AI 补全（模拟 Edit：去掉全部（待填写）标记，填入根因证据）
    text2 = text.replace("（待填写）", "根因：XxxController.java:88 空指针（确认，文件:行号证据）")
    Path(p).write_text(text2, encoding="utf-8")
    check("AI 补全后 → ANALYSIS_INCOMPLETE=no（分析报告已完整，先于代码修复落盘）",
          lambda: "OK: %s" % bf.analysis_complete_status(str(rd))
          if bf.analysis_complete_status(str(rd)) == "no" else "FAIL")

    # 4) 错误路径：analysis.md 缺失 → missing
    Path(p).unlink()
    check("错误路径：analysis.md 缺失 → ANALYSIS_INCOMPLETE=missing",
          lambda: "OK: %s" % bf.analysis_complete_status(str(rd))
          if bf.analysis_complete_status(str(rd)) == "missing" else "FAIL")

passed = sum(1 for r in results if r["passed"])
grading = {
    "summary": {"pass_rate": passed / len(results), "passed": passed,
                "failed": len(results) - passed, "total": len(results)},
    "expectations": results,
}
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(grading, ensure_ascii=False, indent=2), encoding="utf-8")
(out.parent / "timing.json").write_text(json.dumps({
    "total_tokens": 0, "duration_ms": int((time.time() - t0) * 1000),
    "total_duration_seconds": round(time.time() - t0, 2),
    "note": "脚本级离线验证（不消耗模型 token）；真实禅道 e2e 见降级说明"}, ensure_ascii=False))
print(json.dumps(grading["summary"], ensure_ascii=False))
