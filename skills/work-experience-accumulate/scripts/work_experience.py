#!/usr/bin/env python3
"""work_experience.py — 工作经验采集、草稿状态和调度器。

依赖：Python 3.9+ 标准库；Git；外部 dws/禅道查询命令按配置提供。
用法：python3 work_experience.py <子命令> ...
  config-status   检查配置完整性与路径风险
  config-save     dotted.path=JSON值... 写入配置
  dingtalk-preview / zentao-preview / git-preview   单来源只读预览
  collect         按共享窗口采集四类来源
  draft-init      生成草稿模板
  run-cycle       采集 + 有界投影 + Agent 总结 + report.html + 钉钉通知 + AgentR 待办
  report          从草稿渲染总结 HTML（report.html）
  notify-draft    对已完成的草稿发一次本人通知
  todo-create     为已有草稿在 AgentR 创建/重试审核待办
  approve / verify-approved   审核闭环
  schedule        注册 Windows 定时任务（需 --confirm）
  schedule-status 只读核对任务注册与执行状态
退出码：0 成功；2 参数或配置错误；3 外部数据源失败或不完整；4 未审核或审批不匹配。
所有确定性输出为 JSON stdout，诊断写 stderr。脚本不执行 shell 字符串。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

NAME = "work-experience-accumulate"
DEFAULT_CONFIG = {
    "schedule": {"frequency": "daily", "time": "18:30", "window_mode": "daily_fixed",
                 "daily_window_start": "06:00", "daily_window_end": "18:30", "lookback_days": 1},
    "dingtalk": {"search_args": [], "notify_user_id": "", "notify_command": []},
    "zentao": {"query_command": [], "user_id": ""},
    "agentr_todo": {"enabled": False, "endpoint": "http://127.0.0.1:8320/todos", "timeout_seconds": 15},
    "agent_command": [],
    "git_repositories": [],
    "agent_workspaces": [],
    "targets": {"skill": [], "workflow": [], "mcp": [], "knowledge": []},
}
SENSITIVE_WORDS = ("password", "passwd", "secret", "token", "authorization", "cookie")
AGENT_REQUIRED_MARKERS = (
    "# 工作经验沉淀草稿",
    "## <analysis>分析",
    "### 工作项清单",
    "### 聊天记录逐条细节",
    "## 待确定事项",
    "## <conclusion>沉淀候选",
    "### 触发方式与辅助设计",
    "## 审核说明",
)
AGENT_SAFETY_FLAGS = (
    "--no-tools", "--no-extensions", "--no-context-files", "--no-skills",
    "--no-prompt-templates", "--no-themes", "--no-session", "--no-approve",
)


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


BRANCH_RULE_KEYS = ("remote_prefixes", "local_name_contains", "remote_name_contains")


def validate_branch_config(repo: dict[str, Any]) -> None:
    branches = repo.get("branches", [])
    if not isinstance(branches, list) or any(not isinstance(b, str) or not b.strip() for b in branches):
        raise ValueError("branches 必须为非空分支名组成的数组")
    rules = repo.get("branch_selection", {})
    if not isinstance(rules, dict) or set(rules) - set(BRANCH_RULE_KEYS):
        raise ValueError("branch_selection 包含未知规则或不是对象")
    for key, values in rules.items():
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(key + " 必须为非空字符串组成的数组")
    if not branches and not any(rules.values()):
        raise ValueError("必须显式指定分支名或分支匹配规则")
    emails = repo.get("author_emails", [])
    if not isinstance(emails, list) or any(not isinstance(e, str) or not e.strip() for e in emails):
        raise ValueError("author_emails 必须为非空邮箱组成的数组")
    if "deduplicate_commits" in repo and not isinstance(repo["deduplicate_commits"], bool):
        raise ValueError("deduplicate_commits 必须为布尔值")
    uncommitted = repo.get("uncommitted", {})
    if not isinstance(uncommitted, dict):
        raise ValueError("uncommitted 必须为对象")
    if "enabled" in uncommitted and not isinstance(uncommitted["enabled"], bool):
        raise ValueError("uncommitted.enabled 必须为布尔值")
    if uncommitted.get("enabled", False):
        if uncommitted.get("time_filter", "file_mtime_in_window") != "file_mtime_in_window":
            raise ValueError("uncommitted.time_filter 必须为 file_mtime_in_window")
        if uncommitted.get("classification", "candidate") != "candidate":
            raise ValueError("uncommitted.classification 必须为 candidate")
        for key in ("author_verified", "change_time_verified"):
            if uncommitted.get(key, False) is not False:
                raise ValueError(f"uncommitted.{key} 必须为 false")


def schedule_settings(config: dict[str, Any]) -> dict[str, Any]:
    """合并默认调度配置；缺失键回退默认值，只拦截显式非法值。"""
    merged = dict(DEFAULT_CONFIG["schedule"])
    provided = config.get("schedule", {})
    if isinstance(provided, dict):
        merged.update(provided)
    return merged


def required_missing(config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    schedule = schedule_settings(config)
    mode = schedule.get("window_mode", "daily_fixed")
    if mode not in {"daily_fixed", "lookback"}:
        missing.append("schedule.window_mode= daily_fixed|lookback")
    if mode == "daily_fixed":
        for key in ("daily_window_start", "daily_window_end"):
            try:
                validate_time(str(schedule.get(key, "")))
            except ValueError:
                missing.append(f"schedule.{key}= HH:MM（24 小时制）")
        if (not any("daily_window" in item for item in missing)
                and schedule.get("daily_window_start") == schedule.get("daily_window_end")):
            missing.append("schedule.daily_window_start/end 不能相同")
    if schedule.get("frequency", "daily") not in {"daily", "weekly"}:
        missing.append("schedule.frequency= daily|weekly（Windows原生任务）")
    if mode == "lookback" and (not isinstance(schedule.get("lookback_days", 1), int) or schedule.get("lookback_days", 1) < 1):
        missing.append("schedule.lookback_days>=1")
    try:
        validate_time(str(schedule.get("time", "09:00")))
    except ValueError:
        missing.append("schedule.time= HH:MM（24 小时制）")
    if not str(get_path(config, "dingtalk.notify_user_id") or "").strip():
        missing.append("dingtalk.notify_user_id")
    repos = config.get("git_repositories")
    if not isinstance(repos, list) or not repos:
        missing.append("git_repositories")
    else:
        for index, repo in enumerate(repos):
            if not isinstance(repo, dict) or not str(repo.get("path", "")).strip():
                missing.append(f"git_repositories[{index}].path")
            if isinstance(repo, dict):
                try:
                    validate_branch_config(repo)
                except ValueError as exc:
                    missing.append(f"git_repositories[{index}]: {exc}")
    if not isinstance(config.get("agent_workspaces"), list) or not config.get("agent_workspaces"):
        missing.append("agent_workspaces（至少一个）")
    agent_command = config.get("agent_command", [])
    if agent_command:
        if (not isinstance(agent_command, list)
                or any(not isinstance(part, str) or not part.strip() for part in agent_command)):
            missing.append("agent_command 必须为非空字符串数组")
        else:
            missing_flags = [flag for flag in AGENT_SAFETY_FLAGS if flag not in agent_command]
            if missing_flags:
                missing.append("agent_command 缺少安全参数：" + ", ".join(missing_flags))
            if not any(part.startswith("@{run_dir}/work/") for part in agent_command):
                missing.append("agent_command 必须通过 @{run_dir}/work/ 注入证据")
    zentao = config.get("zentao", {})
    if (not isinstance(zentao.get("query_command"), list) or not zentao.get("query_command")
            or any(not isinstance(x, str) or not x.strip() for x in zentao.get("query_command", []))):
        missing.append("zentao.query_command")
    if not str(zentao.get("user_id", "")).strip():
        missing.append("zentao.user_id")
    return missing


def config_warnings(config: dict[str, Any]) -> list[str]:
    """非致命配置风险：只报路径不存在，不改写配置、不阻断采集。

    路径按当前运行平台的语义判断，因此应当在目标平台上执行本命令。
    """
    warnings: list[str] = []

    def check(label: str, value: Any) -> None:
        if isinstance(value, str) and value.strip() and not Path(value).expanduser().is_dir():
            warnings.append(f"{label} 不存在或不是目录：{value}")

    for index, repo in enumerate(config.get("git_repositories") or []):
        if isinstance(repo, dict):
            check(f"git_repositories[{index}].path", str(repo.get("path", "")).strip())
    for index, path in enumerate(config.get("agent_workspaces") or []):
        check(f"agent_workspaces[{index}]", path)
    targets = config.get("targets") or {}
    if isinstance(targets, dict):
        for kind, paths in targets.items():
            for index, path in enumerate(paths if isinstance(paths, list) else []):
                check(f"targets.{kind}[{index}]", path)
    return warnings


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
    return ok({"config_file": str(config_path(args.workdir)), "platform": sys.platform,
               "missing": required_missing(config), "warnings": config_warnings(config),
               "config": scrub(safe)})


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


def explicit_window(start: str | None, end: str | None) -> tuple[str, str] | None:
    """校验显式窗口；未提供时返回 None（沿用默认回溯窗口）。

    用途：定时采集失败后，可对同一历史窗口补采，避免窗口随时间滑动。
    """
    if not start and not end:
        return None
    if not start or not end:
        raise ValueError("--start 与 --end 必须同时提供")
    def parse(value: str) -> dt.datetime:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("时间必须带时区偏移，例如 2026-10-14T04:00:00+00:00")
        return parsed
    begin, finish = parse(start), parse(end)
    if begin >= finish:
        raise ValueError("--start 必须早于 --end")
    return begin.isoformat(), finish.isoformat()


def window(config: dict[str, Any], now: dt.datetime | None = None,
           tz: dt.tzinfo | None = None) -> tuple[str, str]:
    """统一采集窗口。daily_fixed（默认）：本地时间当天 [start, end)；
    当前时间早于今天的 end 时回退到昨天窗口；start>=end 支持跨午夜。
    lookback：兼容旧的回溯天数滑动窗口。输出统一 UTC。"""
    current = now or dt.datetime.now(dt.timezone.utc)
    schedule = schedule_settings(config)
    mode = schedule.get("window_mode", "daily_fixed")
    if mode == "lookback":
        days = int(schedule.get("lookback_days", 1))
        end = current.replace(microsecond=0)
        return (end - dt.timedelta(days=days)).isoformat(), end.isoformat()
    local_tz = tz or dt.datetime.now().astimezone().tzinfo
    local = current.astimezone(local_tz)
    start_parts = validate_time(str(schedule.get("daily_window_start", "06:00"))).split(":")
    end_parts = validate_time(str(schedule.get("daily_window_end", "18:30"))).split(":")
    end = local.replace(hour=int(end_parts[0]), minute=int(end_parts[1]), second=0, microsecond=0)
    if end > local:  # 触发前手动补跑：使用最近一个完整窗口
        end -= dt.timedelta(days=1)
    start = end.replace(hour=int(start_parts[0]), minute=int(start_parts[1]))
    if start >= end:  # 跨午夜窗口（如 22:00–06:00）
        start -= dt.timedelta(days=1)
    return start.astimezone(dt.timezone.utc).isoformat(), end.astimezone(dt.timezone.utc).isoformat()


def run_argv(argv: list[str], cwd: Path | None = None, timeout: int = 180) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True,
                              capture_output=True, timeout=timeout, check=False,
                              encoding="utf-8", errors="replace")
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
    from dingtalk_query import collect
    return collect(config.get("dingtalk", {}), start, end, run_argv)


def cmd_dingtalk_preview(args: argparse.Namespace) -> int:
    config = load_config(args.workdir)
    start, end = window(config)
    try:
        explicit = explicit_window(getattr(args, "start", None), getattr(args, "end", None))
    except ValueError as exc:
        return fail(2, str(exc), "示例：--start 2026-10-14T04:00:00+00:00 --end 2026-10-14T12:00:00+00:00")
    if explicit:
        start, end = explicit
    data, error = collect_dingtalk(config, start, end)
    summary = {k: v for k, v in data.items() if k not in ("records",)}
    summary["matched_count"] = len(data["records"])
    if error:
        summary["error"] = error
    print(json.dumps({"status": "partial" if error else "ok", "data": summary}, ensure_ascii=False))
    return 3 if error else 0


def collect_zentao(config: dict[str, Any], start: str, end: str) -> tuple[Any, str | None]:
    """Require the adapter envelope; never preserve raw error output or argv."""
    source = config.get("zentao", {})
    user_id = source.get("user_id", "")
    command = source.get("query_command", [])
    def rejected(message):
        return {"complete": False, "records": []}, message
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
        return rejected("禅道查询命令未配置或无效")
    try:
        argv = [x.format(start=start, end=end, user_id=user_id) for x in command]
    except (ValueError, KeyError, IndexError):
        return rejected("禅道查询命令占位符无效")
    code, stdout, _stderr = run_argv(argv, timeout=540)
    if code:
        return rejected(f"禅道查询失败，退出码 {code}；未保存原始错误")
    try:
        from zentao_query import QueryError, positive_id, selected, timestamp
        result = json.loads(stdout)
        if not isinstance(result, dict) or result.get("status") != "ok":
            return rejected("禅道适配器未返回成功状态")
        data = result.get("data")
        if (not isinstance(data, dict) or data.get("complete") is not True
                or data.get("user_id") != user_id
                or data.get("window") != {"start": start, "end": end}
                or data.get("time_basis") != "resolvedDate"
                or data.get("scope") != "all_accessible_products"
                or not isinstance(data.get("records"), list)):
            return rejected("禅道适配器结果不完整或账号、时间窗口不匹配")
        counters = ("products_scanned", "bugs_scanned", "changed_candidates_skipped", "requests")
        if any(type(data.get(k)) is not int or data[k] < 0 for k in counters):
            return rejected("禅道适配器统计字段无效")
        # Only known fields cross the collection boundary, even with a custom command.
        fields = {"id", "product", "status", "resolvedBy", "resolvedDate", "title", "resolution", "url"}
        seen = set()
        for row in data["records"]:
            if not isinstance(row, dict) or set(row) != fields:
                return rejected("禅道适配器记录字段无效")
            bug_id = positive_id(row["id"])
            positive_id(row["product"])
            if bug_id in seen or not selected({**row, "deleted": False}, user_id, timestamp(start), timestamp(end)):
                return rejected("禅道适配器记录重复或不符合筛选条件")
            if any(not isinstance(row[k], str) for k in ("title", "resolution", "url")):
                return rejected("禅道适配器文本字段无效")
            row["title"] = scrub_text(row["title"])[:500]
            row["resolution"] = scrub_text(row["resolution"])[:500]
            seen.add(bug_id)
        allowed = {"window", "user_id", "scope", "time_basis", "complete", "products_scanned",
                   "bugs_scanned", "changed_candidates_skipped", "requests", "records"}
        return {k: v for k, v in data.items() if k in allowed}, None
    except (json.JSONDecodeError, ValueError, TypeError, QueryError):
        return rejected("禅道适配器输出无效；未保存原始响应")


def cmd_zentao_preview(args: argparse.Namespace) -> int:
    config = load_config(args.workdir)
    start, end = window(config)
    data, error = collect_zentao(config, start, end)
    if error:
        return fail(3, error, "检查认证、接口兼容性和分页；不要将失败解释为空结果")
    return ok({"window": data["window"], "user_id": data["user_id"], "complete": data["complete"],
               "scope": data["scope"], "products_scanned": data.get("products_scanned"),
               "bugs_scanned": data.get("bugs_scanned"), "requests": data.get("requests"),
               "matched_count": len(data["records"]), "bug_ids": [r["id"] for r in data["records"]],
               "changed_candidates_skipped": data.get("changed_candidates_skipped")})


def discover_branches(repo: dict[str, Any]) -> list[dict[str, str]]:
    """Select full refs every run; remote refs are local snapshots, no fetch."""
    validate_branch_config(repo)
    path = Path(repo["path"]).expanduser()
    code, out, err = run_argv(["git", "--no-optional-locks", "-C", str(path), "for-each-ref",
                               "--format=%(refname)%09%(symref)", "refs/heads/", "refs/remotes/"])
    if code:
        raise ValueError("Git 分支查询失败: " + scrub_text(err)[:500])
    refs = []
    for line in out.splitlines():
        ref, _, symbolic = line.partition("\t")
        if symbolic:  # origin/HEAD is an alias, never a branch.
            continue
        if ref.startswith("refs/heads/"):
            refs.append({"ref": ref, "branch": ref[len("refs/heads/"):], "kind": "local"})
        elif ref.startswith("refs/remotes/"):
            refs.append({"ref": ref, "branch": ref[len("refs/remotes/"):], "kind": "remote"})
    selected = {}
    for branch in repo.get("branches", []):
        hits = [r for r in refs if branch in (r["ref"], r["branch"])]
        if len(hits) != 1:
            raise ValueError("明确分支不存在或名称歧义: " + branch)
        selected[hits[0]["ref"]] = hits[0]
    rules = repo.get("branch_selection", {})
    for ref in refs:
        name = ref["branch"]
        if ref["kind"] == "local":
            match = any(word in name for word in rules.get("local_name_contains", []))
        else:
            match = (any(name.startswith(prefix) for prefix in rules.get("remote_prefixes", [])) or
                     any(word in name.partition("/")[2] for word in rules.get("remote_name_contains", [])))
        if match:
            selected[ref["ref"]] = ref
    if not selected:
        raise ValueError("没有匹配分支；不回退当前分支")
    return [selected[k] for k in sorted(selected)]


def collect_uncommitted(repo: dict[str, Any], start: str, end: str) -> tuple[dict[str, Any] | None, str | None]:
    """Collect existing working-tree paths by mtime without reading file contents."""
    settings = repo.get("uncommitted", {})
    if not settings.get("enabled", False):
        return None, None
    path = Path(str(repo.get("path", ""))).expanduser()
    argv = ["git", "--no-optional-locks", "-C", str(path), "status",
            "--porcelain=v1", "-z", "--untracked-files=all"]
    code, stdout, stderr = run_argv(argv)
    if code:
        return None, f"Git 未提交改动查询失败: 退出码 {code}: {scrub_text(stderr)[:500]}"
    if stdout and not stdout.endswith("\x00"):
        return None, "Git 未提交改动记录缺少 NUL 结束符"
    entries: list[dict[str, Any]] = []
    parts = stdout.split("\x00")
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        if len(raw) < 4 or raw[2] != " ":
            return None, "Git 未提交改动记录格式无效"
        status = raw[:2]
        if any(c not in " MADRCU?!T" for c in status):
            return None, "Git 未提交改动状态无效"
        relative = raw[3:]
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            return None, "Git 未提交改动路径不在工作区内"
        previous = None
        if "R" in status or "C" in status:
            if index >= len(parts) or not parts[index]:
                return None, "Git 重命名或复制记录缺少原路径"
            previous = parts[index]
            index += 1
        entries.append({"status": status, "path": relative, "previous_path": previous})
    start_dt, end_dt = dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end)
    files: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for entry in entries:
        file_path = path / Path(entry["path"])
        try:
            file_stat = file_path.lstat()
            if not (stat.S_ISREG(file_stat.st_mode) or stat.S_ISLNK(file_stat.st_mode)):
                excluded.append({**entry, "file_mtime": None, "reason": "not_regular_file_or_symlink"})
                continue
            stamp = dt.datetime.fromtimestamp(file_stat.st_mtime, tz=dt.timezone.utc)
            file_mtime = stamp.isoformat()
        except (OSError, ValueError):
            excluded.append({**entry, "file_mtime": None, "reason": "file_missing_or_unreadable"})
            continue
        record = {
            **entry,
            "file_mtime": file_mtime,
            "classification": "candidate",
            "author_verified": False,
            "change_time_verified": False,
        }
        if start_dt <= stamp < end_dt:
            files.append(record)
        else:
            excluded.append({**record, "reason": "file_mtime_outside_window"})
    return {
        "repository": str(path),
        "source": "uncommitted",
        "kind": "working_tree",
        "time_basis": "file_mtime",
        "window": {"start": start, "end": end},
        "classification": "candidate",
        "author_verified": False,
        "change_time_verified": False,
        "files": files,
        "excluded": excluded,
    }, None


def collect_git(config: dict[str, Any], start: str, end: str) -> tuple[list[Any], list[str]]:
    results, errors = [], []
    start_dt, end_dt = dt.datetime.fromisoformat(start), dt.datetime.fromisoformat(end)
    for index, repo in enumerate(config.get("git_repositories", [])):
        path = Path(str(repo.get("path", ""))).expanduser()
        try:
            branches = discover_branches(repo)
        except ValueError as exc:
            errors.append(f"git[{index}] {path}: {exc}")
            continue
        emails = {e.casefold() for e in repo.get("author_emails", [])}
        seen = {}
        for branch in branches:
            argv = ["git", "--no-optional-locks", "-C", str(path), "log",
                    "--since-as-filter=" + start, "--until=" + end,
                    "--pretty=format:%H%x09%aI%x09%an%x09%ae%x09%cI%x09%s", branch["ref"], "--"]
            code, stdout, stderr = run_argv(argv)
            item = {"repository": str(path), **branch, "commits": [], "duplicate_commit_ids": [],
                    "ref_source": "local_git_refs", "time_basis": "committer_date"}
            if code:
                errors.append(f"git[{index}] {path} {branch['branch']}: 退出码 {code}: {scrub_text(stderr)[:500]}")
            else:
                for line in stdout.splitlines():
                    fields = line.split("\t", 5)
                    if len(fields) != 6:
                        errors.append(f"git[{index}] {branch['branch']}: 提交记录格式无效")
                        continue
                    commit = dict(zip(("commit", "date", "author", "author_email", "committed_at", "subject"), fields))
                    try:
                        stamp = dt.datetime.fromisoformat(commit["committed_at"])
                        in_window = start_dt <= stamp < end_dt
                    except (ValueError, TypeError):
                        errors.append(f"git[{index}] {commit['commit']}: 提交时间无效")
                        continue
                    if not in_window or (emails and commit["author_email"].casefold() not in emails):
                        continue
                    if repo.get("deduplicate_commits", True) and commit["commit"] in seen:
                        seen[commit["commit"]]["branches"].append(branch["branch"])
                        item["duplicate_commit_ids"].append(commit["commit"])
                        continue
                    commit["branches"] = [branch["branch"]]
                    item["commits"].append(commit)
                    seen[commit["commit"]] = commit
            results.append(item)
        uncommitted, uncommitted_error = collect_uncommitted(repo, start, end)
        if uncommitted_error:
            errors.append(f"git[{index}] {path}: {uncommitted_error}")
        elif uncommitted is not None:
            results.append(uncommitted)
    return results, errors


def cmd_git_preview(args: argparse.Namespace) -> int:
    """Read-only Git validation, no other sources, no output files."""
    config = load_config(args.workdir)
    start, end = window(config)
    records, errors = collect_git(config, start, end)
    summary = [{"repository": r["repository"], "branch": r.get("branch"), "kind": r["kind"],
                "commits": len(r.get("commits", [])), "duplicates": len(r.get("duplicate_commit_ids", [])),
                "uncommitted_files": len(r.get("files", [])), "uncommitted_excluded": len(r.get("excluded", []))}
               for r in records]
    print(json.dumps({"status": "partial" if errors else "ok", "data": {
        "window": {"start": start, "end": end}, "branches": summary,
        "unique_commits": sum(len(r.get("commits", [])) for r in records), "errors": errors,
        "uncommitted_collected": any(r.get("source") == "uncommitted" for r in records)}}, ensure_ascii=False))
    return 3 if errors else 0


def session_files(root: Path) -> list[Path]:
    """List only pi's persisted JSONL sessions, never arbitrary project JSON."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.jsonl") if p.is_file())


def extract_session_time(value: Any) -> dt.datetime | None:
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=dt.timezone.utc)
    return None


def normalized_path(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(Path(value).expanduser().resolve(strict=False))))


def discover_agent_workspaces(config: dict[str, Any]) -> tuple[list[Path], list[str]]:
    """Refresh configured worktrees without changing refs, branches, or files."""
    names = config.get("agent_workspaces", [])
    if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names):
        return [], ["Agent 工作空间配置无效"]
    paths: dict[str, Path] = {}
    for name in names:
        path = Path(name).expanduser()
        paths[normalized_path(path)] = path
    discovery = config.get("agent_workspace_discovery", {})
    errors: list[str] = []
    if discovery.get("include_all_registered_worktrees", False):
        repository = discovery.get("repository")
        if not isinstance(repository, str) or not repository.strip():
            errors.append("Agent worktree 发现缺少 repository")
        else:
            repo = Path(repository).expanduser()
            code, stdout, stderr = run_argv([
                "git", "--no-optional-locks", "-C", str(repo), "worktree", "list", "--porcelain"
            ])
            if code:
                errors.append("Agent worktree 发现失败：" + scrub_text(stderr)[:500])
            else:
                current: Path | None = None
                for line in stdout.splitlines() + [""]:
                    if line.startswith("worktree "):
                        current = Path(line[9:].strip())
                    elif not line.strip() and current is not None:
                        if current.is_dir():
                            paths[normalized_path(current)] = current
                        current = None
    return [paths[key] for key in sorted(paths)], errors


def session_root(config: dict[str, Any]) -> Path:
    configured = config.get("agent_session_dir")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser()
    from_environment = os.environ.get("PI_CODING_AGENT_SESSION_DIR")
    if from_environment:
        return Path(from_environment).expanduser()
    return Path.home() / ".pi" / "agent" / "sessions"


def session_text(message: dict[str, Any]) -> str:
    role = message.get("role")
    if role in {"user", "assistant"}:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
    return ""


def session_record(entry: dict[str, Any], stamp: dt.datetime) -> dict[str, Any] | None:
    if entry.get("type") == "message" and isinstance(entry.get("message"), dict):
        message = entry["message"]
        if message.get("role") not in {"user", "assistant"}:
            return None
        text = session_text(message)
        kind = message.get("role")
    elif entry.get("type") in {"compaction", "branch_summary"}:
        text = entry.get("summary", "")
        kind = entry.get("type")
    else:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    return {"time": stamp.isoformat(), "type": kind, "text": scrub_text(text)[:4000]}


def read_pi_session(path: Path, workspaces: dict[str, Path], start_dt: dt.datetime,
                    end_dt: dt.datetime) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict") as stream:
            first = stream.readline()
            header = json.loads(first)
            if not isinstance(header, dict) or header.get("type") != "session":
                return None, None
            cwd = header.get("cwd")
            if not isinstance(cwd, str) or normalized_path(cwd) not in workspaces:
                return None, None
            selected: list[dict[str, Any]] = []
            for line in stream:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError("会话条目必须是对象")
                stamp = extract_session_time(entry.get("timestamp"))
                if stamp and start_dt <= stamp < end_dt:
                    item = session_record(entry, stamp)
                    if item:
                        selected.append(item)
        if not selected:
            return None, None
        return {"session_id": header.get("id", ""), "workspace": str(workspaces[normalized_path(cwd)]),
                "file": str(path), "records": selected}, None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, f"pi 会话文件解析失败 {path}：{type(exc).__name__}"


def collect_sessions(config: dict[str, Any], start: str, end: str) -> tuple[list[Any], list[str]]:
    start_dt = dt.datetime.fromisoformat(start)
    end_dt = dt.datetime.fromisoformat(end)
    roots, errors = discover_agent_workspaces(config)
    workspaces = {normalized_path(root): root for root in roots}
    results: list[Any] = []
    root = session_root(config)
    if not root.is_dir():
        errors.append("pi 会话目录不存在；无法确认会话来源完整性")
        return results, errors
    for path in session_files(root):
        record, error = read_pi_session(path, workspaces, start_dt, end_dt)
        if error:
            errors.append(error)
        elif record:
            results.append(record)
    return results, errors


def run_dir(workdir: Path, end: str) -> Path:
    date = end[:10]
    return base_dir(workdir) / date / (dt.datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8])


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def cmd_collect(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.workdir)
    except ValueError as exc:
        return fail(2, str(exc), "修复配置后重试")
    missing = required_missing(config)
    if missing:
        return fail(2, "配置不完整：" + ", ".join(missing), "按顺序补齐缺失配置；Git 分支不能省略")
    start, end = window(config)
    try:
        explicit = explicit_window(getattr(args, "start", None), getattr(args, "end", None))
    except ValueError as exc:
        return fail(2, str(exc), "示例：--start 2026-10-14T04:00:00+00:00 --end 2026-10-14T12:00:00+00:00")
    if explicit:
        start, end = explicit
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
    text = """# 工作经验沉淀草稿\n\n> 状态：待用户审核。本文只提供沉淀原料，不修改任何目标产物。\n\n## 汇总窗口\n- 开始：待填写\n- 结束：待填写\n- 数据源完整性：待填写\n\n## <analysis>分析\n### 事实\n- 待填写。引用 `work/` 中的来源文件和记录标识。\n\n### 工作项清单\n逐项列出本窗口内的每项工作，不确定的内容在“待确定”列标注，不得省略。\n\n| 序号 | 工作项 | 做了什么 | 来源证据 | AI 可提效 | 提效方式 | 是否沉淀 | 沉淀目标 | 触发方式 | 待确定项 |\n|---|---|---|---|---|---|---|---|---|---|\n| 1 | 待填写 | 待填写 | 待填写 | 是/否/待确定 | 待填写 | 是/否/待确定 | skill/工作流/MCP/知识库/无 | 定时/自动/手动/待确定 | 待填写 |\n\n### 聊天记录逐条细节\n逐条审阅聊天记录，单条消息里的问题排查、结论、决策也可沉淀为知识；无法判断的标注待确定。\n\n| 时间 | 会话标识 | 消息要点 | 可沉淀知识/思路 | 待确定标注 |\n|---|---|---|---|---|\n| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |\n\n### 工作主题\n- 待填写。\n\n### 重复问题与可复用做法\n- 待填写。\n\n### 失败模式与决策依据\n- 待填写。\n\n## 待确定事项\n集中列出所有不确定的事实、推断和归属；每条写明不确定原因和建议的核实路径；无则写“无”。\n\n- 待填写。\n\n## <conclusion>沉淀候选\n### skill\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n- 边界与反例：待填写。\n- 置信度：待填写。\n\n### 触发方式与辅助设计\n逐个候选说明：触发方式（定时 / 事件自动 / 手动唤起）、使用入口、如何高效辅助人、以及不增设触发时的替代用法。\n\n- 待填写。\n\n### 工作流\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n\n### MCP\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n\n### 知识库知识\n- 目标：新增 / 优化 / 不建议。\n- 沉淀原料：待填写。\n- 证据：待填写。\n\n## 审核说明\n- 本草稿不修改 skill、工作流、MCP 或知识库知识。\n- 用户审核通过后，必须先执行 `approve` 和 `verify-approved`。\n- 汇总报告 `report.html` 由草稿渲染生成，内容以本草稿为准。\n"""
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


def query_windows_task(name: str) -> tuple[dict[str, Any], str | None]:
    """只读取 Windows 任务计划程序状态；不注册、不修改、不删除任务。"""
    script = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$t = Get-ScheduledTask -TaskName {ps_quote(name)} -TaskPath '\\' -ErrorAction Stop",
        f"$i = Get-ScheduledTaskInfo -TaskName {ps_quote(name)} -TaskPath '\\' -ErrorAction Stop",
        "$o = [pscustomobject]@{",
        "  State = [string]$t.State",
        "  LogonType = [string]$t.Principal.LogonType",
        "  RunLevel = [string]$t.Principal.RunLevel",
        "  StartWhenAvailable = [bool]$t.Settings.StartWhenAvailable",
        "  LastRunTime = $(if ($i.LastRunTime) { $i.LastRunTime.ToString('o') } else { $null })",
        "  NextRunTime = $(if ($i.NextRunTime) { $i.NextRunTime.ToString('o') } else { $null })",
        "  LastTaskResult = $i.LastTaskResult",
        "}",
        "$o | ConvertTo-Json -Compress",
    ])
    import base64
    code, stdout, stderr = run_argv(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", base64.b64encode(script.encode("utf-16le")).decode("ascii")], timeout=60)
    if code:
        # 任务不存在是状态，不是查询失败；其它失败不保留原始输出。
        if "No MSFT_ScheduledTask" in (stderr or ""):
            return {"registered": False, "state": "not-installed"}, None
        return {"registered": False}, "查询 Windows 任务状态失败；未保留原始错误"
    try:
        raw = json.loads(stdout[stdout.find("{"):])
    except (ValueError, TypeError):
        return {"registered": False}, "Windows 任务状态输出无法解析"
    if not isinstance(raw, dict):
        return {"registered": False}, "Windows 任务状态输出结构无效"
    mapping = {"State": "state", "LogonType": "logon_type", "RunLevel": "run_level",
               "StartWhenAvailable": "start_when_available", "LastRunTime": "last_run_time",
               "NextRunTime": "next_run_time", "LastTaskResult": "last_task_result"}
    info: dict[str, Any] = {mapping[k]: raw[k] for k in mapping if k in raw}
    info["registered"] = True
    last = info.get("last_run_time")
    info["never_run"] = not isinstance(last, str) or not last or last.startswith("1899-12-30")
    return info, None


def cmd_schedule_status(args: argparse.Namespace) -> int:
    """只读核对定时任务：本地标记 + 实际注册状态 + 最近一次执行结果。"""
    try:
        config = load_config(args.workdir)
        name = windows_task_name(config)
    except ValueError as exc:
        return fail(2, str(exc), "修正 config.json 后重试")
    marker = base_dir(args.workdir) / "schedule.json"
    status: dict[str, Any] = {"task_name": name, "marker_file": str(marker), "marker": None}
    if marker.is_file():
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8-sig"))
            status["marker"] = recorded if isinstance(recorded, dict) else None
        except (OSError, json.JSONDecodeError):
            status["marker"] = None
    if os.name != "nt":
        status["error"] = "Windows 原生任务状态只能在 Windows Python 下查询"
        print(json.dumps({"status": "partial", "data": status}, ensure_ascii=False))
        return 3
    info, error = query_windows_task(name)
    status.update(info)
    if error:
        status["error"] = error
        print(json.dumps({"status": "partial", "data": status}, ensure_ascii=False))
        return 3
    return ok(status)


def format_agent_command(command: Any, run: Path) -> tuple[list[str] | None, str | None]:
    if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part.strip() for part in command):
        return None, "agent_command 必须是非空字符串数组"
    try:
        argv = [part.format(run_dir=str(run), skill_dir=str(Path(__file__).resolve().parents[1])) for part in command]
    except (KeyError, ValueError, IndexError):
        return None, "agent_command 占位符无效"
    missing = [flag for flag in AGENT_SAFETY_FLAGS if flag not in argv]
    if missing:
        return None, "agent_command 缺少安全参数：" + ", ".join(missing)
    return argv, None


def validate_agent_output(output: str) -> tuple[str | None, str | None]:
    if not output or len(output) > 300_000:
        return None, "AI 总结输出为空或超过 300000 字符"
    body = output.strip()
    if (any(marker not in body for marker in AGENT_REQUIRED_MARKERS)
            or "待填写" in body or "work/" not in body
            or "待用户审核" not in body):
        return None, "AI 总结未完成草稿必填内容或缺少 work/ 来源引用"
    return body + "\n", None


def prepare_agent_input(run: Path) -> dict[str, Any]:
    """Bounded evidence projection; full evidence remains in work/*.json."""
    from collections import Counter
    from dingtalk_query import excerpt
    work = run / "work"
    data = {name: json.loads((work / (name + '.json')).read_text(encoding='utf-8'))
            for name in ('manifest', 'dingtalk', 'zentao', 'git', 'sessions', 'errors')}
    git_data = []
    for original in data['git']:
        row = dict(original)
        excluded = row.pop('excluded', [])
        if excluded:
            row['excluded_count'] = len(excluded)
            row['excluded_reasons'] = dict(Counter(x.get('reason', 'unknown') for x in excluded))
        git_data.append(row)
    data['git'] = git_data
    truncations = {'sessions': 0, 'dingtalk': 0}
    for name, budget in (('sessions', 110000), ('dingtalk', 60000)):
        used = 0
        if name == 'sessions':
            for session in data[name]:
                selected = []
                for original in session['records']:
                    row = dict(original)
                    row['text'] = excerpt(row['text'])
                    row['content_is_untrusted_data'] = True
                    size = len(json.dumps(row, ensure_ascii=False))
                    if used + size > budget:
                        truncations[name] += 1
                    else:
                        selected.append(row)
                        used += size
                session['records'] = selected
        else:
            selected = []
            for row in data[name].get('records', []):
                size = len(json.dumps(row, ensure_ascii=False))
                if used + size > budget:
                    truncations[name] += 1
                else:
                    selected.append(row)
                    used += size
            data[name]['records'] = selected
    bundle = {'content_is_untrusted_data': True, 'source_files': {name: 'work/' + name + '.json' for name in data},
              'manifest_semantics': 'sources=true means collection succeeded, not merely enabled; false means failed/incomplete',
              'projection': {'omitted_records': truncations, 'text_excerpt_max_chars': 1000,
                             'git_exclusions': 'counts_only; original work/git.json contains full exclusions',
                             'session_semantics': 'all recorded branches; summaries may describe events outside window; not proof of actual changes'},
              'sources': data}
    # Apply heuristic redaction to all strings, not just chat/session bodies.
    def redact(value):
        if isinstance(value, str):
            if re.search(r'password|passwd|secret|token|authorization|cookie|api[_-]?key|bearer|密码|口令|密钥|令牌|sk-[A-Za-z0-9]{12,}', value, re.I):
                return '[敏感文本已省略]'
            return value
        if isinstance(value, list):
            return [redact(x) for x in value]
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()}
        return value
    bundle = redact(bundle)
    if len(json.dumps(bundle, ensure_ascii=False)) > 220000:
        raise ValueError('总结证据超过安全预算；不能静默丢弃更多来源')
    write_json(work / 'agent-input.json', bundle)
    return bundle


def local_label(iso: str) -> str:
    try:
        return dt.datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def create_agentr_todo(config: dict[str, Any], run: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """草稿就绪后在 AgentR 创建审核待办；幂等：成功一次后跳过。"""
    todo_cfg = config.get("agentr_todo", {})
    if not isinstance(todo_cfg, dict) or not todo_cfg.get("enabled", False):
        return None, None
    marker = run / "work" / "todo.json"
    if marker.is_file():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8-sig"))
            if isinstance(previous, dict) and previous.get("created") is True:
                return {"id": previous.get("id"), "skipped": "already_created"}, None
        except (OSError, json.JSONDecodeError):
            pass
    draft, report = run / "draft.md", run / "report.html"
    if not draft.is_file():
        return None, "草稿不存在，无法创建待办"
    window_info = manifest.get("window", {})
    failed = [k for k, v in manifest.get("sources", {}).items() if not v]
    context = {
        "date": (window_info.get("end", "") or dt.datetime.now(dt.timezone.utc).isoformat())[:10],
        "window_start": local_label(window_info.get("start", "")),
        "window_end": local_label(window_info.get("end", "")),
        "run_dir": str(run), "draft": str(draft),
        "report": str(report) if report.is_file() else "（未生成）",
        "sources_note": ("来源失败：" + "、".join(failed)) if failed else "全部来源采集成功",
    }
    import agentr_todo
    return agentr_todo.create(todo_cfg, context, agentr_todo.post_json, write_json, marker)


def _md_inline(text: str) -> str:
    import html as html_module
    escaped = html_module.escape(text, quote=False)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _md_cell(text: str) -> str:
    return (f'<td class="uncertain">{_md_inline(text)}</td>' if "待确定" in text
            else f"<td>{_md_inline(text)}</td>")


def render_markdown_html(markdown: str, title: str, window_note: str) -> str:
    """把草稿 Markdown 渲染为自包含总结 HTML；含“待确定”的单元格/段落高亮。"""
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_md_inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if (stripped.startswith("|") and index + 1 < len(lines)
                and re.match(r"^\|[\s:|-]+\|?$", lines[index + 1].strip())):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            index += 2
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([c.strip() for c in lines[index].strip().strip("|").split("|")])
                index += 1
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{_md_inline(c)}</th>" for c in header)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(_md_cell(c) for c in row) + "</tr>" for row in rows)
                       + "</tbody></table>")
            continue
        if stripped.startswith("> "):
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip("> "))
                index += 1
            content = _md_inline(" ".join(quote))
            cls = ' class="uncertain"' if "待确定" in content else ""
            out.append(f"<blockquote{cls}>{content}</blockquote>")
            continue
        if re.match(r"^-\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            items = []
            while index < len(lines) and (re.match(r"^-\s+", lines[index].strip()) or re.match(r"^\d+\.\s+", lines[index].strip())):
                item_text = re.sub(r"^(-|\d+\.)\s+", "", lines[index].strip())
                cls = ' class="uncertain"' if "待确定" in item_text else ""
                items.append(f"<li{cls}>{_md_inline(item_text)}</li>")
                index += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        out.append(f"<p>{_md_inline(stripped)}</p>")
        index += 1
    style = (
        "body{font-family:'Microsoft YaHei',system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:24px;color:#1f2933;}"
        "h1{font-size:1.6em;border-bottom:2px solid #2563eb;padding-bottom:8px;}"
        "h2{font-size:1.3em;border-bottom:1px solid #d5dbe1;padding-bottom:6px;margin-top:32px;}"
        "h3{font-size:1.1em;margin-top:24px;}"
        "table{border-collapse:collapse;width:100%;margin:12px 0;font-size:0.92em;}"
        "th,td{border:1px solid #cbd2d9;padding:6px 8px;text-align:left;vertical-align:top;}"
        "th{background:#e4e9ee;}"
        "td.uncertain,li.uncertain{background:#fff3cd;}"
        "blockquote{background:#f0f4f8;border-left:4px solid #2563eb;margin:12px 0;padding:8px 12px;}"
        "blockquote.uncertain{background:#fff3cd;border-left-color:#d97706;}"
        "code{background:#f0f4f8;padding:1px 4px;border-radius:3px;}"
        ".meta{color:#616e7c;font-size:0.9em;}"
    )
    return ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head><meta charset=\"utf-8\">\n"
            f"<title>{_md_inline(title)}</title>\n<style>{style}</style></head>\n<body>\n"
            f"<h1>{_md_inline(title)}</h1>\n<p class=\"meta\">{_md_inline(window_note)}</p>\n"
            + "\n".join(out) + "\n</body></html>\n")


def render_report(run: Path) -> Path:
    draft, manifest_file = run / "draft.md", run / "work" / "manifest.json"
    if not draft.is_file():
        raise ValueError(f"草稿不存在：{draft}")
    markdown = draft.read_text(encoding="utf-8-sig")
    window_note = ""
    if manifest_file.is_file():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        window_info = manifest.get("window", {})
        window_note = "汇总窗口：{} ~ {}（UTC）；来源状态：{}".format(
            window_info.get("start", ""), window_info.get("end", ""),
            "，".join(f"{k}={'成功' if v else '失败'}" for k, v in manifest.get("sources", {}).items()))
    title = next((line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")), "工作经验沉淀报告")
    report = run / "report.html"
    report.write_text(render_markdown_html(markdown, title, window_note), encoding="utf-8")
    return report


def cmd_report(args: argparse.Namespace) -> int:
    run = Path(args.run).expanduser().resolve()
    try:
        report = render_report(run)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return fail(2, f"报告生成失败：{exc}", "确认 draft.md 与 work/manifest.json 存在后重试")
    return ok({"report": str(report), "run_dir": str(run)})


def cmd_notify_draft(args: argparse.Namespace) -> int:
    run = Path(args.run).resolve()
    draft = run / 'draft.md'
    if not draft.is_file():
        return fail(2, f'草稿不存在：{draft}', '先运行 draft-init 或 run-cycle 生成草稿')
    body = draft.read_text(encoding='utf-8')
    _, error = validate_agent_output(body)
    if error:
        return fail(3, error)
    from dingtalk_notify import notify
    state, error = notify(load_config(args.workdir)['dingtalk'], run, run_argv, write_json)
    if error:
        return fail(3, error)
    return ok({'run_dir': str(run), 'notified_user': state['user_id'], 'delivered': state['delivered']})


def cmd_run_cycle(args: argparse.Namespace) -> int:
    config = load_config(args.workdir)
    existing = getattr(args, 'run', None)
    if existing:
        run = Path(existing).expanduser().resolve()
        if not run.is_relative_to(base_dir(args.workdir).resolve()):
            return fail(2, '运行目录不在本项目采集目录内')
    else:
        _, end = window(config)
        run = run_dir(args.workdir, end)
        code = cmd_collect(argparse.Namespace(workdir=args.workdir, run=str(run)))
        if code not in (0, 3):
            return code
    manifest_path = run / 'work' / 'manifest.json'
    if not manifest_path.is_file():
        return fail(2, f'运行目录缺少 work/manifest.json：{run}',
                    '先用 collect --run <运行目录> 生成证据，再运行 run-cycle --run')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    try:
        prepare_agent_input(run)
    except (OSError, ValueError, json.JSONDecodeError):
        return fail(2, '证据投影失败：来源文件缺失或证据超过安全预算',
                    '先重新采集；确认 work/ 下六个来源文件完整后再重试')
    draft = run / 'draft.md'
    if (run / 'approval.json').exists() or (run / 'work' / 'notification.json').exists():
        return fail(2, '运行目录已审核或已尝试通知；禁止自动覆盖草稿')
    if not draft.exists():
        code = cmd_draft_init(argparse.Namespace(run=str(run), force=False))
        if code:
            return code
    argv, error = format_agent_command(config.get('agent_command', []), run)
    if error:
        return fail(2, error)
    agent_code, output, _ = run_argv(argv, cwd=args.workdir, timeout=3600)
    if agent_code:
        return fail(3, 'AI 草稿总结命令失败；未保存原始错误')
    body, error = validate_agent_output(output)
    if error:
        return fail(3, error)
    if any(not value for value in manifest['sources'].values()):
        failure = '、'.join(k for k, value in manifest['sources'].items() if not value)
        body += '\n> 采集器复核：来源不完整：' + failure + '。不能将失败解释为空记录。\n'
    tmp = draft.with_suffix('.tmp')
    tmp.write_text(body, encoding='utf-8')
    tmp.replace(draft)
    cycle_errors: list[dict[str, str]] = []
    report_path = None
    try:
        report_path = render_report(run)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        cycle_errors.append({"stage": "report", "message": str(exc)})
    if not getattr(args, 'no_notify', False):
        code = cmd_notify_draft(argparse.Namespace(workdir=args.workdir, run=str(run)))
        if code:
            cycle_errors.append({"stage": "dingtalk_notify", "message": "钉钉通知未确认送达；草稿保留，可用 notify-draft 重试"})
    todo_state, todo_error = create_agentr_todo(config, run, manifest)
    if todo_error:
        cycle_errors.append({"stage": "agentr_todo", "message": todo_error})
    result = {'run_dir': str(run), 'draft': str(draft),
              'report': str(report_path) if report_path else None,
              'sources': manifest['sources'], 'todo': todo_state,
              'errors': cycle_errors,
              'notification_enabled': not getattr(args, 'no_notify', False)}
    if cycle_errors or not all(manifest['sources'].values()):
        print(json.dumps({'status': 'partial', 'data': result}, ensure_ascii=False))
        return 3
    return ok(result)


def cmd_todo_create(args: argparse.Namespace) -> int:
    config = load_config(args.workdir)
    run = Path(args.run).expanduser().resolve()
    manifest_file = run / 'work' / 'manifest.json'
    if not manifest_file.is_file():
        return fail(2, f'运行目录缺少 work/manifest.json：{run}', '先运行 collect')
    manifest = json.loads(manifest_file.read_text(encoding='utf-8-sig'))
    state, error = create_agentr_todo(config, run, manifest)
    if error:
        return fail(3, error, '修正 agentr_todo 配置或确认 AgentR 服务可用后重试')
    return ok({'run_dir': str(run), 'todo': state})


def cmd_schedule(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.workdir)
    except ValueError as exc:
        return fail(2, str(exc), "修复配置后重试")
    frequency = config.get("schedule", {}).get("frequency", "daily")
    time_value = args.time or config.get("schedule", {}).get("time", "18:30")
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
    p = sub.add_parser("dingtalk-preview"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--start"); p.add_argument("--end"); p.set_defaults(func=cmd_dingtalk_preview)
    p = sub.add_parser("zentao-preview"); p.add_argument("--workdir", type=Path, required=True); p.set_defaults(func=cmd_zentao_preview)
    p = sub.add_parser("git-preview"); p.add_argument("--workdir", type=Path, required=True); p.set_defaults(func=cmd_git_preview)
    p = sub.add_parser("collect"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--run", default=None); p.add_argument("--start"); p.add_argument("--end"); p.set_defaults(func=cmd_collect)
    p = sub.add_parser("run-cycle"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--run"); p.add_argument("--no-notify", action="store_true"); p.set_defaults(func=cmd_run_cycle)
    p = sub.add_parser("notify-draft"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--run", required=True); p.set_defaults(func=cmd_notify_draft)
    p = sub.add_parser("draft-init"); p.add_argument("--run", required=True); p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_draft_init)
    p = sub.add_parser("approve"); p.add_argument("--run", required=True); p.add_argument("--reviewer", required=True); p.set_defaults(func=cmd_approve)
    p = sub.add_parser("verify-approved"); p.add_argument("--run", required=True); p.set_defaults(func=cmd_verify)
    p = sub.add_parser("report"); p.add_argument("--run", required=True); p.set_defaults(func=cmd_report)
    p = sub.add_parser("todo-create"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--run", required=True); p.set_defaults(func=cmd_todo_create)
    p = sub.add_parser("schedule"); p.add_argument("--workdir", type=Path, required=True); p.add_argument("--time"); p.add_argument("--confirm", action="store_true"); p.set_defaults(func=cmd_schedule)
    p = sub.add_parser("schedule-status"); p.add_argument("--workdir", type=Path, required=True); p.set_defaults(func=cmd_schedule_status)
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
