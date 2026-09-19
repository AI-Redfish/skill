#!/usr/bin/env python3
"""gate.py — skill-creator-plus 的评审/测试门禁状态机。

防止跳步：理解闭环（95% 信心）未通过不能编写；评审未通过不能测试；
测试失败必须修改后重走完整评审；报告生成后才算完成。
状态持久化在 <workspace>/gate-state.json，跨轮次/跨会话可恢复。

用法（详见 --help 与 SKILL.md §1/§2）：
  gate.py init --skill <path> --workspace <dir> [--name NAME]
  gate.py show
  gate.py clarify-pass --confidence N [--qa-file F] [--notes S]   # 理解闭环通过(≥95)
  gate.py clarify-fail [--notes S]                                # 仍有信息缺口，继续提问
  gate.py review-pass --confidence N --checklist <JSON> [--notes S]
  gate.py review-fail [--issues-file F] [--notes S]
  gate.py test-pass  [--summary S]
  gate.py test-fail  [--failures-file F] [--notes S]
  gate.py report-done --report <报告文件> [--benchmark F]
  gate.py reset [--hard]

规则：
  - clarify-pass 要求 confidence >= 95（理解闭环：对用户真实需求有 95% 信心才停止提问）
  - review-pass 要求 confidence >= 95 且 checklist JSON 的 status == "pass"（强制机器检查）
  - 编写/评审前置要求 clarify 已通过（需求变更时从 writing 重新 clarify-pass）
  - test-* 仅在 phase == testing（即评审已通过）后可用
  - test-fail 会作废本轮评审通过标记并退回 writing（修改后必须重新评审）
输出：JSON 到 stdout（含 state / allowed / hint）；日志到 stderr。
退出码：0 成功；1 状态文件异常；2 参数或流转非法。
纯标准库，Python 3.9+。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

MIN_CONFIDENCE = 95  # 理解闭环与评审放行的最低置信度（%）
PHASES = ["clarify", "writing", "review", "testing", "report", "done"]

HINTS = {
    "clarify": "理解闭环：先提问（每次只问一个，围绕十要素），对用户真实需求有 95% 信心后 clarify-pass",
    "writing": "编写/修改 skill，完成后从 §4.1 机器检查开始走评审门；需求变更时重走理解闭环（clarify-pass）",
    "review": "继续评审（机器检查 + AI 双评审 + 置信度自评）",
    "testing": "评审已通过：执行测试门（准备用例/收环境信息/跑测试/落盘结果）",
    "report": "测试已通过：运行 gen_test_report.py 生成测试报告，然后 report-done",
    "done": "流程完成；如需再改动，先 reset 回到 writing（需求变更另走 clarify）",
}


def log(msg: str) -> None:
    print(f"[gate] {msg}", file=sys.stderr)


def die(code: int, message: str, hint: str = "", state: dict | None = None) -> int:
    out = {"status": "error", "error": {"message": message}}
    if hint:
        out["error"]["hint"] = hint
    if state:
        out["allowed"] = allowed_actions(state)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


def new_state(skill: Path, workspace: Path, name: str) -> dict:
    return {
        "skill": str(skill),
        "skill_name": name or skill.name,
        "workspace": str(workspace),
        "phase": "clarify",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "clarify": {"rounds": 0, "passed": False, "confidence": 0,
                    "qa_log": None, "history": []},
        "review": {"rounds": 0, "passed": False, "confidence": 0,
                   "checklist": None, "history": []},
        "test": {"rounds": 0, "passed": False, "history": []},
        "report": {"path": None, "benchmark": None},
    }


def load_state(workspace: Path) -> dict | None:
    f = workspace / "gate-state.json"
    if not f.is_file():
        return None
    try:
        state = json.loads(f.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        log(f"状态文件损坏，将拒绝操作：{exc}")
        return {"__broken__": True}
    if isinstance(state, dict) and "clarify" not in state:
        # 旧版状态迁移：视为已通过理解闭环
        state["clarify"] = {"rounds": 0, "passed": True, "confidence": MIN_CONFIDENCE,
                            "qa_log": None, "history": []}
    return state


def save_state(workspace: Path, state: dict) -> None:
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "gate-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def allowed_actions(state: dict) -> list[str]:
    phase = state.get("phase")
    acts = ["show", "reset"]
    if phase in ("clarify", "writing"):
        acts += ["clarify-pass", "clarify-fail"]
    if phase in ("writing", "review"):
        acts += ["review-pass", "review-fail"]
    elif phase == "testing":
        acts += ["test-pass", "test-fail"]
    elif phase == "report":
        acts += ["report-done"]
    return acts


def emit_ok(state: dict, message: str) -> int:
    out = {"status": "ok", "message": message, "state": _brief(state),
           "allowed": allowed_actions(state), "hint": HINTS.get(state["phase"], "")}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _brief(state: dict) -> dict:
    return {
        "phase": state["phase"],
        "skill_name": state["skill_name"],
        "skill": state["skill"],
        "clarify_rounds": state.get("clarify", {}).get("rounds", 0),
        "clarify_passed": state.get("clarify", {}).get("passed", True),
        "clarify_confidence": state.get("clarify", {}).get("confidence", 0),
        "review_rounds": state["review"]["rounds"],
        "review_passed": state["review"]["passed"],
        "confidence": state["review"]["confidence"],
        "test_rounds": state["test"]["rounds"],
        "test_passed": state["test"]["passed"],
        "report_path": state["report"]["path"],
    }


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def get_state_or_die(workspace: Path) -> tuple[dict | None, int]:
    state = load_state(workspace)
    if state is None:
        return None, die(2, f"未找到状态文件：{workspace}/gate-state.json",
                         "先运行: gate.py init --skill <target> --workspace <workspace>")
    if state.get("__broken__"):
        return None, die(1, f"状态文件损坏：{workspace}/gate-state.json",
                         "修复 JSON 或运行 gate.py reset --hard 重新初始化（历史会丢失）")
    return state, 0


def validate_checklist(path: str) -> tuple[bool, str]:
    """校验 review_checklist.py 的输出 JSON：存在且 status == pass。"""
    p = Path(path)
    if not p.is_file():
        return False, f"机器检查结果文件不存在：{p}（先运行 review_checklist.py --json <该路径>）"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"机器检查结果无法解析：{exc}"
    if data.get("status") != "pass":
        failed = data.get("summary", {}).get("failed", "?")
        return False, (f"机器检查未通过（failed={failed}），"
                       "修复 error 级问题并重跑 review_checklist.py 后再 review-pass")
    return True, ""


def read_notes(path: str | None, notes: str | None) -> str:
    if path:
        p = Path(path)
        if p.is_file():
            return p.read_text(encoding="utf-8-sig", errors="replace")[:8000]
        return f"(指定的文件不存在: {path})"
    return notes or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="skill-creator-plus 门禁状态机")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化状态（编写开始前）")
    p.add_argument("--skill", required=True, help="被创建/修改的 skill 目录")
    p.add_argument("--workspace", required=True, help="工作区目录")
    p.add_argument("--name", default=None, help="skill 名称（默认取目录名）")
    p.add_argument("--force", action="store_true", help="覆盖已有状态")

    sub.add_parser("show", help="查看当前状态与允许的操作").add_argument("--workspace", required=True)

    p = sub.add_parser("clarify-pass", help="理解闭环通过（对真实需求有 95%% 信心）")
    p.add_argument("--workspace", required=True)
    p.add_argument("--confidence", type=int, required=True, help="对用户真实需求的信心 0-100，须≥95")
    p.add_argument("--qa-file", default=None, help="问答记录 clarify-qa.md（可选，便于追溯）")
    p.add_argument("--notes", default=None, help="关键假设清单（需求复述+假设）")

    p = sub.add_parser("clarify-fail", help="仍有信息缺口，继续理解闭环提问")
    p.add_argument("--workspace", required=True)
    p.add_argument("--notes", default=None, help="缺口说明")

    p = sub.add_parser("review-pass", help="记录评审通过（置信度+机器清单强制校验）")
    p.add_argument("--workspace", required=True)
    p.add_argument("--confidence", type=int, required=True, help="自评置信度 0-100，须≥95")
    p.add_argument("--checklist", required=True, help="review_checklist.py 输出的 JSON 文件")
    p.add_argument("--notes", default=None)

    p = sub.add_parser("review-fail", help="记录评审未通过，退回编写")
    p.add_argument("--workspace", required=True)
    p.add_argument("--issues-file", default=None, help="问题清单文件（如 review-round-N.md）")
    p.add_argument("--notes", default=None)

    p = sub.add_parser("test-pass", help="记录测试通过，进入报告阶段")
    p.add_argument("--workspace", required=True)
    p.add_argument("--summary", default=None)

    p = sub.add_parser("test-fail", help="记录测试失败：退回编写，作废评审通过标记")
    p.add_argument("--workspace", required=True)
    p.add_argument("--failures-file", default=None, help="失败清单文件")
    p.add_argument("--notes", default=None)

    p = sub.add_parser("report-done", help="测试报告已生成，流程完成")
    p.add_argument("--workspace", required=True)
    p.add_argument("--report", required=True, help="报告文件路径（必须已存在）")
    p.add_argument("--benchmark", default=None, help="benchmark.json 路径（可选）")

    p = sub.add_parser("reset", help="回到编写阶段（清除通过标记，保留历史）")
    p.add_argument("--workspace", required=True)
    p.add_argument("--hard", action="store_true", help="删除状态文件重新开始")

    args = parser.parse_args()
    workspace = Path(getattr(args, "workspace", ".")).expanduser().resolve()

    if args.cmd == "init":
        if load_state(workspace) and not args.force:
            return die(2, f"状态已存在：{workspace}/gate-state.json",
                       "继续用 show 查看；确要重来加 --force（历史丢失）")
        skill = Path(args.skill).expanduser().resolve()
        if not skill.is_dir():
            return die(2, f"skill 目录不存在：{skill}", "检查 --skill 路径")
        state = new_state(skill, workspace, args.name or "")
        save_state(workspace, state)
        return emit_ok(state, "已初始化，进入理解闭环：先提问（每次只问一个），"
                              "对真实需求有 95% 信心后 clarify-pass")

    state, code = get_state_or_die(workspace)
    if state is None:
        return code

    if args.cmd == "show":
        print(json.dumps({"status": "ok", "state": state,
                          "allowed": allowed_actions(state),
                          "hint": HINTS.get(state["phase"], "")},
                         ensure_ascii=False, indent=2))
        return 0

    phase = state["phase"]

    if args.cmd in ("clarify-pass", "clarify-fail"):
        if phase not in ("clarify", "writing"):
            return die(2, f"当前阶段 {phase} 不允许记录理解闭环结果",
                       "需求变更时先 reset 回 writing，再重新 clarify-pass", state)
        if args.cmd == "clarify-pass":
            if args.confidence < MIN_CONFIDENCE:
                return die(2, f"对真实需求的信心 {args.confidence}% 低于门槛 {MIN_CONFIDENCE}%",
                           "继续理解闭环：每次只问一个问题（围绕十要素），只提问澄清不给方案；"
                           "或 clarify-fail 记录缺口", state)
            state["clarify"]["rounds"] += 1
            state["clarify"]["passed"] = True
            state["clarify"]["confidence"] = args.confidence
            if getattr(args, "qa_file", None):
                state["clarify"]["qa_log"] = str(Path(args.qa_file).resolve())
            state["clarify"]["history"].append(
                {"round": state["clarify"]["rounds"], "result": "pass",
                 "confidence": args.confidence, "time": now(),
                 "notes": (args.notes or "")[:2000]})
            state["phase"] = "writing"
            save_state(workspace, state)
            return emit_ok(state, f"理解闭环通过（第 {state['clarify']['rounds']} 轮，"
                                  f"信心 {args.confidence}%），进入编写；"
                                  "编写前须向用户复述需求+关键假设")
        state["clarify"]["rounds"] += 1
        state["clarify"]["passed"] = False
        state["clarify"]["history"].append(
            {"round": state["clarify"]["rounds"], "result": "fail",
             "time": now(), "notes": (args.notes or "")[:2000]})
        state["phase"] = "clarify"
        save_state(workspace, state)
        return emit_ok(state, "仍有信息缺口，继续理解闭环：每次只问一个问题")

    if args.cmd == "review-pass":
        if phase not in ("writing", "review"):
            return die(2, f"当前阶段 {phase} 不允许记录评审结果",
                       "测试失败后已自动退回 writing；若 skill 已修改，直接走新一轮评审", state)
        if not state.get("clarify", {}).get("passed", True):
            return die(2, "理解闭环未通过（需求未确认到 95% 信心）",
                       "先完成理解闭环并 clarify-pass", state)
        if args.confidence < MIN_CONFIDENCE:
            return die(2, f"置信度 {args.confidence}% 低于门槛 {MIN_CONFIDENCE}%",
                       "对照 references/review-guide.md 的判据补齐短板（负向用例/错误路径/"
                       "边界输入/需求逐条对照），或 review-fail 记录未通过原因", state)
        ok, why = validate_checklist(args.checklist)
        if not ok:
            return die(2, why, "", state)
        state["review"]["rounds"] += 1
        state["review"]["passed"] = True
        state["review"]["confidence"] = args.confidence
        state["review"]["checklist"] = str(Path(args.checklist).resolve())
        state["review"]["history"].append(
            {"round": state["review"]["rounds"], "result": "pass",
             "confidence": args.confidence, "time": now(),
             "notes": (args.notes or "")[:2000]})
        state["phase"] = "testing"
        save_state(workspace, state)
        return emit_ok(state, f"评审通过（第 {state['review']['rounds']} 轮，"
                              f"置信度 {args.confidence}%），进入测试门")

    if args.cmd == "review-fail":
        if phase not in ("writing", "review"):
            return die(2, f"当前阶段 {phase} 不允许记录评审结果", "", state)
        state["review"]["rounds"] += 1
        state["review"]["passed"] = False
        state["review"]["history"].append(
            {"round": state["review"]["rounds"], "result": "fail",
             "time": now(), "notes": read_notes(getattr(args, "issues_file", None), args.notes)})
        state["phase"] = "writing"
        save_state(workspace, state)
        return emit_ok(state, f"评审未通过（第 {state['review']['rounds']} 轮），"
                              "已退回编写；修改后重走完整评审")

    if args.cmd in ("test-pass", "test-fail"):
        if phase != "testing":
            return die(2, f"当前阶段 {phase} 不能记录测试结果",
                       "测试前必须 review-pass；测试失败会自动退回 writing，需先修改并重新评审", state)
        if args.cmd == "test-pass":
            state["test"]["rounds"] += 1
            state["test"]["passed"] = True
            state["test"]["history"].append(
                {"round": state["test"]["rounds"], "result": "pass",
                 "time": now(), "summary": (args.summary or "")[:2000]})
            state["phase"] = "report"
            save_state(workspace, state)
            return emit_ok(state, f"测试通过（第 {state['test']['rounds']} 轮），"
                                  "运行 gen_test_report.py 生成报告后 report-done")
        state["test"]["rounds"] += 1
        state["test"]["passed"] = False
        state["review"]["passed"] = False  # 强制：改完必须重新评审
        state["test"]["history"].append(
            {"round": state["test"]["rounds"], "result": "fail",
             "time": now(),
             "notes": read_notes(getattr(args, "failures_file", None), args.notes)})
        state["phase"] = "writing"
        save_state(workspace, state)
        return emit_ok(state, f"测试失败（第 {state['test']['rounds']} 轮）：已退回编写，"
                              "修改 skill 后必须重走完整评审（机器检查+双评审+95%置信）")

    if args.cmd == "report-done":
        if phase != "report":
            return die(2, f"当前阶段 {phase} 不能完成报告",
                       "报告仅在测试通过（test-pass）后可用", state)
        report = Path(args.report)
        if not report.is_file():
            return die(2, f"报告文件不存在：{report}",
                       "先运行 gen_test_report.py 生成测试报告", state)
        state["report"]["path"] = str(report.resolve())
        if args.benchmark:
            state["report"]["benchmark"] = str(Path(args.benchmark).resolve())
        state["phase"] = "done"
        save_state(workspace, state)
        return emit_ok(state, "测试报告已登记，流程完成；可继续打包交付（SKILL.md §7）")

    if args.cmd == "reset":
        if args.hard:
            f = workspace / "gate-state.json"
            if f.exists():
                f.unlink()
            print(json.dumps({"status": "ok", "message": "状态文件已删除"},
                             ensure_ascii=False))
            return 0
        state["phase"] = "writing"
        state["review"]["passed"] = False
        state["review"]["confidence"] = 0
        state["test"]["passed"] = False
        save_state(workspace, state)
        return emit_ok(state, "已回到编写阶段（历史保留）")

    return die(2, f"未知命令：{args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
