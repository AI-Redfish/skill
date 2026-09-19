#!/usr/bin/env python3
"""gen_test_report.py — 测试通过后，调用官方 skill-creator 脚本生成测试报告。

职责（SKILL.md §6）：
1. 定位依赖（复用 ensure_dependency 的搜索逻辑，缺省时自动检查）；
2. 调用官方 scripts.aggregate_benchmark.py：汇总 iteration-N 下各 eval 的 grading.json
   → benchmark.json / benchmark.md；
3. 调用官方 eval-viewer/generate_review.py --static：产出独立 HTML 评审页（免起服务）；
4. 可选：--trigger-results（官方 run_loop.py 的 JSON 输出）→ scripts.generate_report.py
   生成触发优化 HTML 报告；
5. 汇总 gate-state.json（评审轮次/置信度/测试轮次）+ benchmark 结果
   → reports/test-report.md。

用法：
  python gen_test_report.py --workspace DIR --skill-name NAME
      [--dep PATH] [--iteration N] [--trigger-results FILE] [--skill-path PATH]

输出：JSON 到 stdout（artifacts 路径、degraded 降级项）；报告写入 <workspace>/reports/。
退出码：0 成功（允许有降级项）；1 生成失败；2 参数错误。
纯标准库，Python 3.9+。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ensure_dependency import locate  # noqa: E402


def log(msg: str) -> None:
    print(f"[gen_test_report] {msg}", file=sys.stderr)


def run(cmd: list, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        log(f"命令失败（{proc.returncode}）：{' '.join(map(str, cmd))}\n{proc.stderr[-1500:]}")
    return proc.returncode, proc.stdout


def find_latest_iteration(workspace: Path) -> Path | None:
    iters = sorted(workspace.glob("iteration-*"),
                   key=lambda p: int(p.name.split("-")[1]) if p.name.split("-")[-1].isdigit() else 0)
    return iters[-1] if iters else None


def parse_benchmark(benchmark_json: Path) -> list[dict]:
    """从 benchmark.json 提取各配置的通过率摘要（容忍结构差异）。"""
    try:
        data = json.loads(benchmark_json.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = []
    summary = data.get("run_summary", data.get("summary", {}))
    runs_by_config: dict = {}
    for r in data.get("runs", []) or []:
        if isinstance(r, dict):
            cfg = r.get("configuration", r.get("config", "?"))
            runs_by_config[cfg] = runs_by_config.get(cfg, 0) + 1
    for config, stats in summary.items():
        if not isinstance(stats, dict):
            continue
        if config == "delta":
            rows.append({"config": "delta（with−without）",
                         "pass_rate": stats.get("pass_rate"),
                         "runs": "-"})
            continue
        pr = stats.get("pass_rate", {})
        mean = pr.get("mean") if isinstance(pr, dict) else pr
        rows.append({
            "config": config,
            "pass_rate": round(float(mean), 4) if mean is not None else None,
            "runs": runs_by_config.get(config, "-"),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="调用官方 skill-creator 脚本生成测试报告")
    parser.add_argument("--workspace", required=True, help="测试工作区目录")
    parser.add_argument("--skill-name", required=True, help="被测 skill 名称")
    parser.add_argument("--dep", default=None, help="官方 skill-creator 路径（缺省自动搜索）")
    parser.add_argument("--iteration", type=int, default=None, help="指定 iteration-N（缺省取最新）")
    parser.add_argument("--trigger-results", default=None,
                        help="官方 run_loop.py 输出的 JSON（可选，生成触发优化报告）")
    parser.add_argument("--skill-path", default=None, help="被测 skill 路径（写入 benchmark 元数据）")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(json.dumps({"status": "error", "error": {
            "message": f"工作区不存在：{workspace}",
            "hint": "测试阶段应已创建 <workspace>/iteration-N（见 references/testing-guide.md）"}},
            ensure_ascii=False))
        return 2

    # 1. 定位依赖
    if args.dep:
        dep = Path(args.dep).expanduser().resolve()
        if not (dep / "SKILL.md").is_file():
            print(json.dumps({"status": "error", "error": {
                "message": f"--dep 不是有效的 skill-creator 目录：{dep}"}}, ensure_ascii=False))
            return 2
    else:
        found = locate(workspace)
        if not found:
            print(json.dumps({"status": "error", "error": {
                "message": "未找到 skill-creator 依赖",
                "hint": "先运行 ensure_dependency.py，或用 --dep 显式指定路径"}},
                ensure_ascii=False))
            return 1
        dep = found[0]

    # 2. 确定 iteration 目录
    if args.iteration:
        iter_dir = workspace / f"iteration-{args.iteration}"
        if not iter_dir.is_dir():
            print(json.dumps({"status": "error", "error": {
                "message": f"iteration 目录不存在：{iter_dir}",
                "hint": "检查 --iteration 参数或先完成测试落盘"}}, ensure_ascii=False))
            return 2
    else:
        iter_dir = find_latest_iteration(workspace)
        if not iter_dir:
            print(json.dumps({"status": "error", "error": {
                "message": f"{workspace} 下未发现 iteration-* 目录",
                "hint": "测试结果须按 iteration-N/eval-*/<config>/ 布局落盘"
                        "（references/testing-guide.md）"}}, ensure_ascii=False))
            return 1

    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    degraded: list[str] = []
    artifacts: dict = {"workspace": str(workspace), "iteration": iter_dir.name}

    # 3. 官方 aggregate_benchmark（cwd 必须在 dep 根，因为其以 scripts.xxx 模块方式导入）
    benchmark_json = iter_dir / "benchmark.json"
    benchmark_md = iter_dir / "benchmark.md"
    if (dep / "scripts" / "aggregate_benchmark.py").is_file():
        cmd = [sys.executable, "-m", "scripts.aggregate_benchmark", str(iter_dir),
               "--skill-name", args.skill_name]
        if args.skill_path:
            cmd += ["--skill-path", str(Path(args.skill_path).resolve())]
        code, _ = run(cmd, cwd=dep)
        if code == 0 and benchmark_json.is_file():
            artifacts["benchmark_json"] = str(benchmark_json)
            artifacts["benchmark_md"] = str(benchmark_md) if benchmark_md.is_file() else None
        else:
            degraded.append("aggregate_benchmark 失败（检查 grading.json 布局："
                            "eval-*/<config>/run-1/grading.json，字段 summary+expectations）")
    else:
        degraded.append("依赖版本无 aggregate_benchmark.py，跳过基准汇总")

    # 4. 官方评审页（--static 免服务；要求 workspace 内存在 outputs/ 目录）
    review_html = reports / "review.html"
    if (dep / "eval-viewer" / "generate_review.py").is_file():
        cmd = [sys.executable, str(dep / "eval-viewer" / "generate_review.py"),
               str(iter_dir), "--skill-name", args.skill_name, "--static", str(review_html)]
        if benchmark_json.is_file():
            cmd += ["--benchmark", str(benchmark_json)]
        code, _ = run(cmd)
        if code == 0 and review_html.is_file():
            artifacts["review_html"] = str(review_html)
        else:
            degraded.append("generate_review 失败（通常因工作区无 outputs/ 目录："
                            "测试时须把产物存入 eval-*/<config>/outputs/）")
    else:
        degraded.append("依赖版本无 eval-viewer/generate_review.py，跳过 HTML 评审页")

    # 5. 可选：触发优化报告
    if args.trigger_results:
        trig = Path(args.trigger_results).expanduser().resolve()
        trigger_html = reports / "trigger-report.html"
        if trig.is_file() and (dep / "scripts" / "generate_report.py").is_file():
            code, _ = run([sys.executable, "-m", "scripts.generate_report", str(trig),
                           "-o", str(trigger_html), "--skill-name", args.skill_name], cwd=dep)
            if code == 0 and trigger_html.is_file():
                artifacts["trigger_html"] = str(trigger_html)
            else:
                degraded.append("generate_report 失败（确认 --trigger-results 是 run_loop.py 的 JSON 输出）")
        else:
            degraded.append("--trigger-results 文件不存在或依赖缺 generate_report.py，跳过触发报告")

    # 6. 汇总 Markdown 报告（含门禁状态）
    gate_state = {}
    gate_file = workspace / "gate-state.json"
    if gate_file.is_file():
        try:
            gate_state = json.loads(gate_file.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            degraded.append("gate-state.json 解析失败，报告不含门禁轮次信息")

    bench_rows = parse_benchmark(benchmark_json) if benchmark_json.is_file() else []
    md = [f"# 测试报告 — {args.skill_name}", "",
          f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
          f"- 测试迭代：`{iter_dir.name}`",
          f"- 依赖：anthropics skill-creator @ `{dep}`", ""]
    if gate_state:
        rv, tv = gate_state.get("review", {}), gate_state.get("test", {})
        md += ["## 门禁过程", "",
               f"- 评审轮次：{rv.get('rounds', '?')}（最终置信度 {rv.get('confidence', '?')}%，"
               f"{'通过' if rv.get('passed') else '未通过'}）",
               f"- 测试轮次：{tv.get('rounds', '?')}（{'通过' if tv.get('passed') else '未通过'}）", ""]
    if bench_rows:
        md += ["## 基准摘要（官方 aggregate_benchmark）", "",
               "| 配置 | 断言通过率 | 运行次数 |", "|---|---|---|"]
        for r in bench_rows:
            md.append(f"| {r['config']} | {r['pass_rate']} | {r.get('runs') or '-'} |")
        md.append("")
    if degraded:
        md += ["## 降级项", ""] + [f"- ⚠️ {d}" for d in degraded] + [""]
    md += ["## 产物索引", ""]
    for k, v in artifacts.items():
        if v:
            md.append(f"- {k}: `{v}`")
    md += ["", "---", "评审页用浏览器打开 review.html 查看（Outputs 逐例浏览 + Benchmark 量化对比）。"]

    report_md = reports / "test-report.md"
    report_md.write_text("\n".join(md), encoding="utf-8")
    artifacts["test_report_md"] = str(report_md)

    print(json.dumps({"status": "ok", "skill_name": args.skill_name,
                      "artifacts": artifacts, "degraded": degraded},
                     ensure_ascii=False, indent=2))
    if degraded:
        log(f"完成，但有 {len(degraded)} 个降级项，见报告")
    return 0


if __name__ == "__main__":
    sys.exit(main())
