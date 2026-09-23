#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iteration-1 eval-2：配置缺失触发理解闭环（脚本侧，离线）+ 无头提示词契约。

- 在空临时项目跑 bugfix.py config-status：应退出码 2 且列出全部缺失键
  （该退出码是 SKILL.md 理解闭环「一次只问一个」的脚本侧触发点）
- dingtalk_listen.build_fix_prompt：步骤顺序必须是 补全 analysis.md → 实施修复，
  且分析阶段禁止改代码（无头链路同样遵循分析先行）
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "zentao-bugfix"
sys.path.insert(0, str(SKILL / "scripts"))
spec = importlib.util.spec_from_file_location("bugfix", SKILL / "scripts" / "bugfix.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)
spec2 = importlib.util.spec_from_file_location("dl", SKILL / "scripts" / "dingtalk_listen.py")
dl = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dl)

t0 = time.time()
results = []


def check(text, fn):
    try:
        ev = fn()
    except Exception as e:  # noqa: BLE001
        ev = "EXCEPTION: %r" % e
    results.append({"text": text, "passed": not str(ev).startswith(("FAIL", "EXCEPTION")),
                    "evidence": str(ev)})


with tempfile.TemporaryDirectory() as td:
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / "bugfix.py"),
                        "config-status", "--project", "."],
                       cwd=td, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = {}
    check("无配置项目 config-status 退出码 2（触发理解闭环：AI 逐项索取，不脑补凭据）",
          lambda: "OK: exit=%d missing=%s" % (r.returncode, data.get("missing"))
          if r.returncode == 2 else "FAIL: exit=%d out=%s" % (r.returncode, r.stdout[:120]))
    check("缺失键清单完整（ZENTAO_BASE_URL/ACCOUNT/PASSWORD）",
          lambda: "OK" if set(data.get("missing") or []) >= {
              "ZENTAO_BASE_URL", "ZENTAO_ACCOUNT", "ZENTAO_PASSWORD"} else "FAIL: %s" % data)

p = dl.build_fix_prompt("12345")
check("无头修复提示词：先补全 analysis.md 输出分析报告，再实施修复（顺序正确）",
      lambda: "OK: 顺序正确" if p.index("补全 analysis.md") < p.index("实施修复")
      else "FAIL: 顺序颠倒")
check("无头修复提示词：分析阶段明确禁止修改任何代码文件",
      lambda: "OK" if "禁止修改任何代码文件" in p else "FAIL")

passed = sum(1 for r in results if r["passed"])
grading = {"summary": {"pass_rate": passed / len(results), "passed": passed,
                       "failed": len(results) - passed, "total": len(results)},
           "expectations": results}
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(grading, ensure_ascii=False, indent=2), encoding="utf-8")
(out.parent / "timing.json").write_text(json.dumps({
    "total_tokens": 0, "duration_ms": int((time.time() - t0) * 1000),
    "total_duration_seconds": round(time.time() - t0, 2),
    "note": "脚本级离线验证；真实禅道 e2e 见降级说明"}, ensure_ascii=False))
print(json.dumps(grading["summary"], ensure_ascii=False))
