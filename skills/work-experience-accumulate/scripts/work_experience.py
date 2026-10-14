#!/usr/bin/env python3
"""work_experience.py — 工作经验采集、草稿状态和调度器。

依赖：Python 3.9+ 标准库；Git；外部 dws/禅道查询命令按配置提供。
用法：python3 work_experience.py <config-status|config-save|collect|draft-init|approve|verify-approved|schedule> ...
退出码：0 成功；2 参数或配置错误；3 外部数据源失败；4 未审核或审批不匹配。
所有确定性输出为 JSON stdout，诊断写 stderr。脚本不执行 shell 字符串。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

NAME = "work-experience-accumulate"
DEFAULT_CONFIG = {
    "schedule": {"frequency": "daily", "time": "09:00", "lookback_days": 1},
    "dingtalk": {"search_args": [], "notify_user_id": "", "notify_command": []},
    "zentao": {"query_command": [], "user_id": ""},
    "agent_command": [],
    "git_repositories": [],
    "agent_workspaces": [],
    "targets": {"skill": [], "workflow": [], "mcp": [], "knowledge": []},
}
SENSITIVE_WORDS = ("password", "passwd", "secret", "token", "authorization", "cookie")


def fail(code: int, message: str, hint: str = "") -> int:
    data = {"status": "error", "error": {"code": str(code), "message": message}}
    if hint:
        data["error"]["hint"] = hint
    print(json.dumps(data, ensure_ascii=False))
    return code


def ok(data: dict[str, Any]) -> int:
    print(json.dumps({"status": "ok", "data": data}, ensure_ascii=False))
    return 0


def base_dir(workdir: Path) -> Path:
    return workdir / ".agents" / NAME


def config_path(workdir: Path) -> Path:
    return base_dir(workdir) / "config.json"


def load_config(workdir: Path) -> dict[str, Any]:
    path = config_path(workdir)
    if not path.is_file():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"配置无法解析：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("配置根节点必须是对象")
    return value


def save_config(workdir: Path, value: dict[str, Any]) -> None:
    path = config_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_path(data: dict[str, Any], dotted: str) -> Any:
    value: Any = data
    for key in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def required_missing(config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    schedule = config.get("schedule", {})
    if schedule.get("frequency", "daily") not in {"daily", "weekly"}:
        missing.append("schedule.frequency= daily|weekly（Windows原生任务）")
    if not isinstance(schedule.get("lookback_days", 1), int) or schedule.get("lookback_days", 1) < 1:
        missing.append("schedule.lookback_days>=1")
    if not str(schedule.get("time", "09:00")):
        missing.append("schedule.time")
    if not str(get_path(config, "dingtalk.notify_user_id") or "").strip():
        missing.append("dingtalk.notify_user_id")
    repos = config.get("git_repositories")
    if not isinstance(repos, list) or not repos:
        missing.append("git_repositories")
    else:
        for index, repo in enumerate(repos):
            if not isinstance(repo, dict) or not str(repo.get("path", "")).strip():
                missing.append(f"git_repositories[{index}].path")
            if not isinstance(repo, dict) or not repo.get("branches"):
                missing.append(f"git_repositories[{index}].branches（必须显式指定）")
    if not isinstance(config.get("agent_workspaces"), list) or not config.get("agent_workspaces"):
        missing.append("agent_workspaces（至少一个）")
    zentao = config.get("zentao", {})
    if not isinstance(zentao.get("query_command"), list) or not zentao.get("query_command"):
        missing.append("zentao.query_command")
    if not str(zentao.get("user_id", "")).strip():
        missing.append("zentao.user_id")
    return missing


def cmd_config_status(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.workdir)
    except ValueError as exc:
        return fail(2, str(exc), "修复 config.json 后重试")
    safe = json.loads(json.dumps(config))
    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("***" if any(word in k.lower() for word in SENSITIVE_WORDS) else scrub(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    return ok({"config_file": str(config_path(args.workdir)), "missing": required_missing(config), "config": scrub(safe)})


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_config_save(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.workdir)
    except ValueError as exc:
        return fail(2, str(exc), "修复 config.json 后重试")
    for assignment in args.assignment:
        if "=" not in assignment:
            return fail(2, f"配置项格式错误：{assignment}", "使用 dotted.path=JSON值")
        dotted, raw = assignment.split("=", 1)
        keys = dotted.split(".")
        cursor: dict[str, Any] = config
        for key in keys[:-1]:
            child = cursor.get(key)
            if not isinstance(child, dict):
                child = {}
                cursor[key] = child
            cursor = child
        cursor[keys[-1]] = parse_value(raw)
    save_config(args.workdir, config)
    return ok({"config_file": str(config_path(args.workdir)), "missing": required_missing(config)})


def window(config: dict[str, Any], now: dt.datetime | None = None) -> tuple[str, str]:
    current = now or dt.datetime.now(dt.timezone.utc)
    days = int(config.get("schedule", {}).get("lookback_days", 1))
    end = current.replace(microsecond=0)
    start = end - dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()


def run_argv(argv: list[str], cwd: Path | None = None, timeout: int = 180) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True,
                              capture_output=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def scrub_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(word in lowered for word in SENSITIVE_WORDS):
            lines.append("[已脱敏的敏感字段]")
        else:
            lines.append(line[:2000])
    return "\n".join(lines)


def json_result(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": scrub_text(raw)}


def collect_dingtalk(config: dict[str, Any], start: str, end: str) -> tuple[Any, str | None]:
    args = ["dws", "chat", "+search-msg"] + [str(x) for x in config.get("dingtalk", {}).get("search_args", [])]
    args += ["--start", start, "--end", end, "--format", "json"]
    code, stdout, stderr = run_argv(args)
    if code:
        return {"command": args, "stderr": scrub_text(stderr)}, f"dws 采集失败，退出码 {code}"
    return json_result(stdout), None


def collect_zentao(config: dict[str, Any], start: str, end: str) -> tuple[Any, str | None]:
    source = config.get("zentao", {})
    argv = [str(x).format(start=start, end=end, user_id=str(source.get("user_id", ""))) for x in source.get("query_command", [])]
    code, stdout, stderr = run_argv(argv)
    if code:
        return {"command": argv, "stderr": scrub_text(stderr)}, f"禅道查询失败，退出码 {code}"
    return json_result(stdout), None


def collect_git(config: dict[str, Any], start: str, end: str) -> tuple[list[Any], list[str]]:
    results, errors = [], []
    for index, repo in enumerate(config.get("git_repositories", [])):
        path = Path(str(repo.get("path", ""))).expanduser()
        for branch in repo.get("branches", []):
            argv = ["git", "-C", str(path), "log", str(branch), "--since=" + start,
                    "--until=" + end, "--date=iso-strict", "--pretty=format:%H%x09%ad%x09%an%x09%s"]
            code, stdout, stderr = run_argv(argv)
            item = {"repository": str(path), "branch": branch, "commits": []}
            if code:
                errors.append(f"git[{index}] {path} {branch}: 退出码 {code}: {scrub_text(stderr)[:500]}")
            else:
                for line in stdout.splitlines():
                    fields = line.split("\t", 3)
                    if len(fields) == 4:
                        item["commits"].append(dict(zip(("commit", "date", "author", "subject"), fields)))
            results.append(item)
    return results, errors


def session_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".jsonl", ".json"}]


def extract_session_time(value: Any) -> dt.datetime | None:
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=dt.timezone.utc)
    return None


def collect_sessions(config: dict[str, Any], start: str, end: str) -> tuple[list[Any], list[str]]:
    start_dt = dt.datetime.fromisoformat(start)
    end_dt = dt.datetime.fromisoformat(end)
    results, errors = [], []
    for root_name in config.get("agent_workspaces", []):
        root = Path(str(root_name)).expanduser()
        for path in session_files(root):
            try:
                records = []
                if path.suffix.lower() == ".jsonl":
                    records = [json.loads(line) for line in path.read_text(encoding="utf-8-sig", errors="strict").splitlines() if line.strip()]
                else:
                    loaded = json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
                    records = loaded if isinstance(loaded, list) else [loaded]
                selected = []
                for record in records:
                    stamp = None
                    if isinstance(record, dict):
                        for key in ("timestamp", "time", "createdAt", "created_at", "date"):
                            stamp = extract_session_time(record.get(key))
                            if stamp:
                                break
                    if stamp and start_dt <= stamp < end_dt:
                        selected.append({"time": stamp.isoformat(), "type": record.get("type") if isinstance(record, dict) else None,
                                         "text": scrub_text(json.dumps(record, ensure_ascii=False))[:4000]})
                if selected:
                    results.append({"workspace": str(root), "file": str(path), "records": selected})
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"会话文件解析失败 {path}: {exc}")
    return results, errors


def run_dir(workdir: Path, end: str) -> Path:
    date = end[:10]
    return base_dir(workdir) / date / (dt.datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8])


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_collect(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.workdir)
    except ValueError as exc:
        return fail(2, str(exc), "修复配置后重试")
    missing = required_missing(config)
    if missing:
        return fail(2, "配置不完整：" + ", ".join(missing), "按顺序补齐缺失配置；Git 分支不能省略")
    start, end = window(config)
    target = Path(args.run).expanduser().resolve() if args.run else run_dir(args.workdir, end)
    work = target / "work"
    work.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    dingtalk, dingtalk_error = collect_dingtalk(config, start, end)
    if dingtalk_error: errors.append(dingtalk_error)
    zentao, zentao_error = collect_zentao(config, start, end)
    if zentao_error: errors.append(zentao_error)
    git_data, git_errors = collect_git(config, start, end)
    errors.extend(git_errors)
    sessions, session_errors = collect_sessions(config, start, end)
    errors.extend(session_errors)
    write_json(work / "dingtalk.json", dingtalk)
    write_json(work / "zentao.json", zentao)
    write_json(work / "git.json", git_data)
    write_json(work / "sessions.json", sessions)
    write_json(work / "errors.json", errors)
    manifest = {"window": {"start": start, "end": end},
                "sources": {"dingtalk": not bool(dingtalk_error), "zentao": not bool(zentao_error),
                            "git": not bool(git_errors), "sessions": not bool(session_errors)},
                "errors": len(errors)}
    write_json(work / "manifest.json", manifest)
    result = {"run_dir": str(target), "window": manifest["window"], "errors": errors,
              "sources": manifest["sources"]}
    if errors:
        print(json.dumps({"status": "partial", "data": result}, ensure_ascii=False))
        return 3
    return ok(result)


def cmd_draft_init(args: argparse.Namespace) -> int:
    run = Path(args.run).expanduser().resolve()
    work = run / "work"
    if not (work / "manifest.json").is_file():
        return fail(2, f"运行目录缺少 manifest.json：{run}", "先运行 collect")
    draft = run / "draft.md"
    if draft.exists() and not args.force:
        return fail(2, f"草稿已存在：{draft}", "确认不会覆盖后加 --force")
    text = """# 工作经验沉淀草稿\n\n> 状态：待用户审核。本文只提供沉淀原料，不修改任何目标产物。\n\n## 汇总窗口\n- 开始：待填写\n- 结束：待填写\n- 数据源完整性：待填写\n\n## <analysis>分析\n### 事实\n- 待填写。引用 `work/` 中的来源文件和记录标识。\n\n### 工作主题\n- 待填写。\n\n### 重复问题与可复用做法\n- 待填写。\n\n### 失败模式与决策依据\n- 待填写。\n\n## <conclusion>沉淀候选\n### skill\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n- 边界与反例：待填写。\n- 置信度：待填写。\n\n### 工作流\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n\n### MCP\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n\n### 知识库知识\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n\n## 审核说明\n- 本草稿不修改 skill、工作流、MCP 或知识库知识。\n- 用户审核通过后，必须先执行 `approve` 和 `verify-approved`。\n"""
    draft.write_text(text, encoding="utf-8")
    return ok({"draft": str(draft), "next": "AI补全草稿后通知用户审核"})


def cmd_approve(args: argparse.Namespace) -> int:
    run = Path(args.run).expanduser().resolve()
    draft = run / "draft.md"
    if not draft.is_file():
        return fail(2, f"草稿不存在：{draft}", "先生成草稿")
    digest = hashlib.sha256(draft.read_bytes()).hexdigest()
    approval = {"approved": True, "reviewer": args.reviewer, "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(), "draft_sha256": digest}
    write_json(run / "approval.json", approval)
    return ok(approval)


def cmd_verify(args: argparse.Namespace) -> int:
    run = Path(args.run).expanduser().resolve()
    draft, approval = run / "draft.md", run / "approval.json"
    if not draft.is_file() or not approval.is_file():
        return fail(4, "草稿尚未完成审核", "用户确认后运行 approve")
    try:
        data = json.loads(approval.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fail(4, "approval.json 无法解析", "重新执行 approve")
    digest = hashlib.sha256(draft.read_bytes()).hexdigest()
    if data.get("approved") is not True or not data.get("reviewer") or data.get("draft_sha256") != digest:
        return fail(4, "审核标记无效或草稿已变更", "重新审核当前草稿")
    return ok({"approved": True, "reviewer": data["reviewer"], "run": str(run)})


def schedule_command(workdir: Path) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "run-cycle", "--workdir", str(workdir)]


def ps_quote(value: str) -> str:
    """Quote a literal for a PowerShell single-quoted string."""
    return "'" + value.replace("'", "''") + "'"


def win_arg_quote(value: str) -> str:
    """Quote one argument using the Windows C runtime command-line rules."""
    return subprocess.list2cmdline([value])


def windows_task_name(config: dict[str, Any]) -> str:
    name = str(config.get("schedule", {}).get("task_name", "AI-Redfish-work-experience-accumulate"))
    if not name.strip() or any(c in name for c in '\\/:*?"<>|') or any(ord(c) < 32 for c in name):
        raise ValueError("task_name 必须是非空任务名称，不含目录分隔符或控制字符")
    return name


def validate_time(value: str) -> str:
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError(f"时间格式错误：{value}，必须是 HH:MM")
    try:
        parsed = dt.datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"时间格式错误：{value}，必须是 HH:MM") from exc
    return parsed.strftime("%H:%M")


def windows_task_preview(config: dict[str, Any], workdir: Path, time_value: str) -> dict[str, Any]:
    time_value = validate_time(time_value)
    frequency = str(config.get("schedule", {}).get("frequency", "daily"))
    if frequency == "daily":
        trigger = f"每日 {time_value}，StartWhenAvailable=true"
    elif frequency == "weekly":
        trigger = f"每周一 {time_value}，StartWhenAvailable=true"
    else:
        raise ValueError("Windows 原生任务只支持 daily 或 weekly；custom 需要明确实现规则")
    command = schedule_command(workdir)
    return {
        "task_name": windows_task_name(config),
        "trigger": trigger,
        "restart_behavior": "任务注册在 Windows 任务计划程序中；系统重启后重新登录时继续有效",
        "command": command,
        "logon_requirement": "当前用户需要登录；dws 和 Agent 使用当前用户配置",
    }


def install_windows_task(config: dict[str, Any], workdir: Path, time_value: str) -> tuple[bool, str]:
    """Register a persistent current-user Windows Scheduled Task."""
    preview = windows_task_preview(config, workdir, time_value)
    command = preview["command"]
    argument = subprocess.list2cmdline([str(part) for part in command[1:]])
    script = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$action = New-ScheduledTaskAction -Execute {ps_quote(str(command[0]))} -Argument {ps_quote(argument)} -WorkingDirectory {ps_quote(str(workdir))}",
        (f"$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact({ps_quote(time_value)}, 'HH:mm', $null))"
         if str(config.get("schedule", {}).get("frequency", "daily")) == "daily" else
         f"$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At ([datetime]::ParseExact({ps_quote(time_value)}, 'HH:mm', $null))"),
        "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)",
        "$userId = \"${env:USERDOMAIN}\\${env:USERNAME}\"",
        "$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited",
        f"Register-ScheduledTask -TaskName {ps_quote(preview['task_name'])} -TaskPath '\\' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null",
        f"$registered = Get-ScheduledTask -TaskName {ps_quote(preview['task_name'])} -TaskPath '\\' -ErrorAction Stop",
        "if (-not $registered.Settings.StartWhenAvailable) { throw 'StartWhenAvailable was not persisted' }",
    ])
    encoded = script.encode("utf-16le")
    import base64
    code, _, stderr = run_argv(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", base64.b64encode(encoded).decode("ascii")], timeout=60)
    if code:
        return False, scrub_text(stderr)[:1500] or "PowerShell 注册任务失败"
    return True, json.dumps(preview, ensure_ascii=False)


def cmd_run_cycle(args: argparse.Namespace) -> int:
    # 该入口只完成确定性步骤；AI 总结和通知仍受配置与审核门禁控制。
    collect_args = argparse.Namespace(workdir=args.workdir, run=None)
    code = cmd_collect(collect_args)
    if code not in (0, 3):
        return code
    # collect 输出为 JSON，但脚本接口不依赖 stdout 解析，按最新日期目录定位最新运行。
    candidates = sorted((base_dir(args.workdir) / dt.datetime.now().strftime("%Y-%m-%d")).glob("*/work/manifest.json"))
    if not candidates:
        return fail(3, "采集完成但找不到运行目录", "检查 .agents/work-experience-accumulate 目录")
    run = candidates[-1].parent.parent
    draft_code = cmd_draft_init(argparse.Namespace(run=str(run), force=False))
    if draft_code:
        return draft_code
    config = load_config(args.workdir)
    agent_command = config.get("agent_command", [])
    if not agent_command:
        return ok({"run_dir": str(run), "next": "agent_command 未配置；AI需补全草稿后发送通知"})
    argv = [str(part).format(run_dir=str(run), skill_dir=str(Path(__file__).resolve().parents[1])) for part in agent_command]
    agent_code, agent_out, agent_err = run_argv(argv, timeout=3600)
    if agent_code:
        return fail(3, "AI 草稿总结命令失败", scrub_text(agent_err)[:1000])
    draft = run / "draft.md"
    body = draft.read_text(encoding="utf-8") if draft.is_file() else ""
    if not body or "待填写" in body:
        return fail(3, "AI 总结未完成草稿必填内容", "检查 agent_command 是否按 skill 流程执行")
    notify_command = config.get("dingtalk", {}).get("notify_command", [])
    if not notify_command:
        return fail(3, "缺少钉钉通知命令", "配置经验证的 dws 通知命令；不得猜测接收人 ID")
    notify_argv = [str(part).format(user_id=config["dingtalk"]["notify_user_id"], text="沉淀草稿已经生成。", run_dir=str(run)) for part in notify_command]
    notify_code, _, notify_err = run_argv(notify_argv)
    if notify_code:
        return fail(3, "草稿已生成但钉钉通知失败", scrub_text(notify_err)[:1000])
    return ok({"run_dir": str(run), "draft": str(draft), "notified_user": config["dingtalk"]["notify_user_id"]})


def cmd_schedule(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.workdir)
    except ValueError as exc:
        return fail(2, str(exc), "修复配置后重试")
    frequency = config.get("schedule", {}).get("frequency", "daily")
    time_value = args.time or config.get("schedule", {}).get("time", "09:00")
    try:
        preview = windows_task_preview(config, args.workdir, time_value)
    except ValueError as exc:
        return fail(2, str(exc), "修正 schedule 配置后重试")
    if not args.confirm:
        return fail(2, "安装 Windows 定时任务需要明确确认", json.dumps(preview, ensure_ascii=False))
    if os.name != "nt":
        return fail(2, "Windows 原生任务必须由 Windows Python 执行", "请在 Windows PowerShell 或 cmd 中使用 python.exe/py.exe 重新运行本命令；不要使用 WSL Python")
    installed, detail = install_windows_task(config, args.workdir, time_value)
    if not installed:
        return fail(2, "Windows 任务计划程序注册失败", detail)
    marker = base_dir(args.workdir) / "schedule.json"
    write_json(marker, {"installed": True, "backend": "Windows Task Scheduler", "frequency": frequency, "time": time_value, "task_name": windows_task_name(config), "command": schedule_command(args.workdir), "preview": json.loads(detail)})
    return ok({"schedule_file": str(marker), "backend": "Windows Task Scheduler", "task_name": windows_task_name(config), "preview": json.loads(detail)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("config-status"); p.add_argument("--workdir", type=Path, required=True); p.set_defaults(func=cmd_config_status)
    p = sub.add_parser("config-save"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("assignment", nargs="+", help="dotted.path=value"); p.set_defaults(func=cmd_config_save)
    p = sub.add_parser("collect"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--run", default=None); p.set_defaults(func=cmd_collect)
    p = sub.add_parser("run-cycle"); p.add_argument("--workdir", type=Path, required=True); p.set_defaults(func=cmd_run_cycle)
    p = sub.add_parser("draft-init"); p.add_argument("--run", required=True); p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_draft_init)
    p = sub.add_parser("approve"); p.add_argument("--run", required=True); p.add_argument("--reviewer", required=True); p.set_defaults(func=cmd_approve)
    p = sub.add_parser("verify-approved"); p.add_argument("--run", required=True); p.set_defaults(func=cmd_verify)
    p = sub.add_parser("schedule"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--time"); p.add_argument("--confirm", action="store_true"); p.set_defaults(func=cmd_schedule)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if hasattr(args, "workdir"):
        args.workdir = args.workdir.expanduser().resolve()
    try:
        result = args.func(args)
        return result if isinstance(result, int) else 0
    except Exception as exc:
        print(f"[work-experience] 未处理错误：{exc}", file=sys.stderr)
        return fail(1, "脚本执行失败", "查看 stderr 后修复输入或环境")


if __name__ == "__main__":
    raise SystemExit(main())
