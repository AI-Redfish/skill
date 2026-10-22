#!/usr/bin/env python3
"""agentr_todo.py — AgentR 待办创建适配器。

通过 AgentR Node 本地服务 HTTP 接口（默认 http://127.0.0.1:8320/todos）创建审核待办。
只创建，不更新、不删除；幂等：调用方检查 work/todo.json 成功标记后跳过。
仅使用 Python 标准库；失败不抛异常，返回 (state, error)。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

DEFAULT_TITLE = "沉淀草稿待审核 {date}（{window_start}–{window_end}）"
DEFAULT_DESCRIPTION = """工作经验沉淀草稿已生成，等待审核。

- 汇总窗口：{window_start} ~ {window_end}
- 数据源完整性：{sources_note}
- 草稿：{draft}
- 汇总报告：{report}
- 运行目录：{run_dir}

审核通过后需执行 approve / verify-approved 才会生成正式产物。
"""
MAX_TITLE = 200
MAX_DESCRIPTION = 20000


def validate_endpoint(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("agentr_todo.endpoint 必须是 http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("agentr_todo.endpoint 不得包含凭据、查询参数或片段")
    if re.search(r"password|passwd|secret|token|authorization|cookie", url, re.I):
        raise ValueError("agentr_todo.endpoint 疑似包含敏感信息")
    return url.rstrip("/")


def post_json(url: str, payload: dict[str, Any], timeout: int) -> tuple[int, Any]:
    """默认 HTTP 实现；测试可注入同名签名的 fake。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        raw = response.read().decode("utf-8", errors="replace")
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw[:2000]


def create(todo_config: dict[str, Any], context: dict[str, str],
           post_json_fn: Callable[..., tuple[int, Any]],
           write_json_fn: Callable[[Any, Any], None],
           marker_path: Any) -> tuple[dict[str, Any] | None, str | None]:
    """创建待办并写入 marker_path；返回 (state, error)。"""
    try:
        endpoint = validate_endpoint(todo_config.get("endpoint", "http://127.0.0.1:8320/todos"))
    except ValueError as exc:
        return None, str(exc)
    timeout = todo_config.get("timeout_seconds", 15)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        return None, "agentr_todo.timeout_seconds 必须是 1–120 的整数"
    values = {key: str(value or "") for key, value in context.items()}
    try:
        title = str(todo_config.get("title_template", DEFAULT_TITLE)).format(**values).strip()
        description = str(todo_config.get("description_template", DEFAULT_DESCRIPTION)).format(**values).strip()
    except (KeyError, IndexError, ValueError):
        return None, "agentr_todo 模板占位符无效；允许 " + ", ".join(sorted(values))
    if not title or len(title) > MAX_TITLE:
        return None, f"待办标题为空或超过 {MAX_TITLE} 字符"
    if len(description) > MAX_DESCRIPTION:
        return None, f"待办描述超过 {MAX_DESCRIPTION} 字符"
    payload: dict[str, Any] = {"title": title, "description": description}
    assignee = str(todo_config.get("assignee", "") or "").strip()
    if assignee:
        payload["assignee"] = assignee
    try:
        status, response = post_json_fn(endpoint, payload, timeout)
    except (OSError, ValueError) as exc:  # urllib.error.URLError 是 OSError 子类
        return None, "AgentR 待办接口请求失败：" + type(exc).__name__
    if not 200 <= status < 300:
        return None, f"AgentR 待办接口返回 HTTP {status}；未保存原始响应"
    item = response.get("item") if isinstance(response, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
        return None, "AgentR 待办接口响应缺少 item.id；未保存原始响应"
    state = {"created": True, "id": item["id"], "endpoint": endpoint, "title": title,
             "created_at": datetime.now(timezone.utc).isoformat()}
    write_json_fn(marker_path, state)
    return state, None
