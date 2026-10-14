"""Normalize dws +search-msg evidence; dws owns all pagination, never poll here."""
from __future__ import annotations

import datetime as dt
import json
import re
import time


class QueryError(ValueError):
    pass


def stamp(value, timezone=None):
    if not isinstance(value, str):
        raise QueryError("钉钉时间字段无效")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QueryError("钉钉时间字段无效") from None
    if parsed.tzinfo is None:
        if timezone is None:
            raise QueryError("钉钉时间缺少已验证时区")
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(dt.timezone.utc)


def settings(source):
    if not isinstance(source, dict) or source.get("scope") != "all_accessible":
        raise QueryError("当前钉钉采集仅支持明确配置的 all_accessible 范围")
    executable = source.get("executable")
    profile = source.get("profile")
    user = source.get("notify_user_id")
    if not isinstance(executable, str) or not executable.strip():
        raise QueryError("dingtalk.executable 未配置")
    if (not isinstance(profile, str) or profile.count(":") != 1
            or any(not part.strip() for part in profile.split(":"))
            or profile.split(":")[1] != user or "," in profile):
        raise QueryError("钉钉 profile 必须为已确认的 corpId:userId，并匹配配置用户")
    offset = source.get("message_timezone")
    if not isinstance(offset, str) or not re.fullmatch(r"[+-](?:0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00", offset):
        raise QueryError("dingtalk.message_timezone 必须为已验证的固定时间偏移")
    timezone = dt.timezone(dt.timedelta(minutes=(int(offset[1:3]) * 60 + int(offset[4:])) * (-1 if offset[0] == "-" else 1)))
    # Only performance knobs. No scope, output, identity or time overrides.
    args = source.get("search_args", [])
    allowed = {"--limit": (1, 30), "--page-limit": (1, 40)}
    if not isinstance(args, list) or len(args) % 2:
        raise QueryError("dingtalk.search_args 必须为分页参数和值组成的数组")
    options = {"--limit": "30", "--page-limit": "40"}
    seen = set()
    for flag, value in zip(args[::2], args[1::2]):
        if (not isinstance(flag, str) or flag not in allowed or flag in seen
                or not isinstance(value, str) or not value.isdecimal()):
            raise QueryError("钉钉采集拒绝未批准的参数或重复参数")
        lower, upper = allowed[flag]
        if not lower <= int(value) <= upper:
            raise QueryError("钉钉分页参数超出安全范围")
        seen.add(flag)
        options[flag] = value
    for key, lower, upper, default in (("fallback_window_hours", 1, 24, 3),
                                       ("split_max_depth", 0, 3, 2),
                                       ("shape_retries", 0, 3, 2),
                                       ("max_sub_windows", 2, 24, 12)):
        value = source.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise QueryError("dingtalk.%s 必须是 %d-%d 的整数" % (key, lower, upper))
    return executable, profile, timezone, [x for kv in options.items() for x in kv]


def excerpt(text):
    """Heuristic redaction, not a guarantee that arbitrary private text is safe."""
    if not isinstance(text, str):
        raise QueryError("钉钉消息文本字段无效")
    lines = []
    for line in text.splitlines():
        if re.search(r"password|passwd|secret|token|authorization|cookie|api[_-]?key|bearer|密码|口令|密钥|令牌", line, re.I):
            lines.append("[已脱敏的敏感字段]")
        else:
            line = re.sub(r"https?://[^\s<>]+", "[链接已省略]", line, flags=re.I)
            line = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已脱敏]", line)
            line = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已脱敏]", line)
            lines.append(line)
    return "\n".join(lines)[:1000]


def normalize(raw, source, start, end):
    _, profile, timezone, _ = settings(source)
    start_dt, end_dt = stamp(start), stamp(end)
    if start_dt >= end_dt:
        raise QueryError("钉钉时间窗口无效")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise QueryError("dws 输出不是有效 JSON；不保留原始响应") from None
    if not isinstance(data, dict) or data.get("contractVersion") != "im.message-list.v1":
        raise QueryError("dws 消息查询契约缺失或不兼容")
    qr = data.get("queryRange")
    if (not isinstance(qr, dict) or qr.get("semantics") != "[start,end)"
            or stamp(qr.get("startTime")) != start_dt or stamp(qr.get("endTime")) != end_dt):
        raise QueryError("dws 返回的时间窗口不匹配")
    rows = data.get("messages")
    failures, warnings = data.get("failures"), data.get("warnings")
    if not isinstance(rows, list) or not isinstance(failures, list) or not isinstance(warnings, list):
        raise QueryError("dws 消息列表或完整性字段无效")
    counters = ("count", "enrichedCount", "failedCount", "warningCount", "pagesFetched")
    if any(type(data.get(k)) is not int or data[k] < 0 for k in counters):
        raise QueryError("dws 统计字段无效")
    if (data["count"] != len(rows) or data["failedCount"] != len(failures)
            or data["warningCount"] != len(warnings) or data["enrichedCount"] > len(rows)):
        raise QueryError("dws 消息统计不一致")
    flags = ("complete", "paginationKnown", "hasMore", "partial", "truncated",
             "truncatedByPageLimit", "truncatedByResultLimit")
    if any(type(data.get(k)) is not bool for k in flags):
        raise QueryError("dws 完整性标记缺失或无效")
    complete = (data["complete"] and data["paginationKnown"] and not any(data[k] for k in flags[2:])
                and not failures and not warnings and data["enrichedCount"] == len(rows))
    records, seen = [], set()
    duplicates = outside = 0
    for row in rows:
        if not isinstance(row, dict):
            raise QueryError("dws 消息记录结构无效")
        for key in ("messageId", "conversationId", "senderId"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise QueryError("dws 消息缺少稳定标识")
        created = stamp(row.get("createTime"), timezone)
        if row.get("time") is not None and stamp(row["time"], timezone) != created:
            raise QueryError("dws 消息时间字段不一致")
        if not start_dt <= created < end_dt:
            outside += 1
            continue
        key = (row["conversationId"], row["messageId"])
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        records.append({"message_id": row["messageId"], "conversation_id": row["conversationId"],
                        "sender_id": row["senderId"], "time": created.isoformat(),
                        "excerpt": excerpt(row.get("text")), "content_is_untrusted_data": True})
    return {"window": {"start": start, "end": end}, "profile": profile,
            "scope": "all_accessible", "scope_basis": "current_profile_searchable_messages",
            "message_timezone": source["message_timezone"], "complete": complete,
            "collection_strategy": "single", "sub_windows": 1,
            "pages_fetched": data["pagesFetched"], "returned_count": len(rows),
            "failed_count": len(failures), "warning_count": len(warnings),
            "duplicates_skipped": duplicates, "outside_window_skipped": outside,
            "records": records, "redaction": "heuristic_excerpt_not_semantic_summary"}


def _dws_error(stderr):
    """Read a single JSON error after optional CLI warning lines; never persist it."""
    if not isinstance(stderr, str) or len(stderr) > 100000:
        return {}
    try:
        data = json.loads(stderr[stderr.find('{'):])
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    error = data.get("error")
    if isinstance(error, dict):
        return error
    # dws common errors may use the top-level success/code/message envelope.
    if data.get("success") is False:
        return {key: data.get(key) for key in ("code", "message", "retryable",
                                                "retry_after_seconds", "next_retry_at",
                                                "server_error_code", "category", "reason")
                if key in data}
    return {}


MISSING_COLLECTION_TEXT = "下游缺少明确的集合字段"
# 已实测：该错误对同一账号、同一参数、同一窗口独立随机出现，与窗口宽度、
# `-v/--debug`、dws Skill 安装状态无关。固定退避重试是有界且只读的处置。
SHAPE_RETRY_SECONDS = (5, 10, 20)


def _shape_delays(source):
    return list(SHAPE_RETRY_SECONDS[:int(source.get("shape_retries", 2))])


def _is_missing_collection(stderr):
    error = _dws_error(stderr)
    message = error.get("message")
    return (error.get("reason") == "missing_collection"
            or (isinstance(message, str) and MISSING_COLLECTION_TEXT in message)
            or MISSING_COLLECTION_TEXT in (stderr or ""))


def _retryable_dws_error(stderr):
    """返回 (是否重试, 等待秒数)。认证/权限/参数错误永不重试。"""
    error = _dws_error(stderr)
    if error.get("category") in ("auth", "permission", "validation"):
        return False, 0
    if error.get("reason") == "confirmation_required":
        return False, 0
    if _is_missing_collection(stderr):
        # 已观测到：同一命令、同一账号、同一窗口有成功也有失败，属于下游信封不稳定。
        # 只读查询无副作用，允许按退避序列重试（次数由 dingtalk.shape_retries 控制）。
        return True, 5
    if error.get("retryable") is not True:
        return False, 0
    import math
    delays = []
    if "retry_after_seconds" in error:
        value = error["retry_after_seconds"]
        if isinstance(value, bool):
            return False, 0
        try:
            delay = float(value)
        except (TypeError, ValueError):
            return False, 0
        if not math.isfinite(delay) or delay < 0:
            return False, 0
        delays.append(delay)
    if "next_retry_at" in error:
        try:
            retry_at = stamp(error["next_retry_at"])
        except QueryError:
            return False, 0
        delays.append(max(0, (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds()))
    # Long/invalid server delays stop this run, never clamp to an earlier retry.
    delay = max(delays) if delays else (30 if error.get("server_error_code") == "RATE_LIMIT_ERROR" else 1)
    return (True, delay) if delay <= 60 else (False, 0)


def _dws_failure_message(stderr):
    error = _dws_error(stderr)
    message = error.get("message", "")
    if _is_missing_collection(stderr):
        return "dws 下游消息集合字段缺失；无法判断结果是否为空；未将其解释为空记录"
    if error.get("server_error_code") == "RATE_LIMIT_ERROR":
        return "dws 消息查询受服务端限流；本次来源不完整；未将其解释为空记录"
    if error.get("category") in ("auth", "permission"):
        return "dws 消息查询认证或权限失败；本次来源不完整；未将其解释为空记录"
    return "dws 采集失败；未保留原始错误或消息"


def _search(source, start, end, runner, exe, profile, args, retry_shape=True):
    """对 [start, end) 执行一次已验证查询。返回 (data, error, shape_failure)。

    retry_shape=False 时不再重试「下游集合字段缺失」：子窗口已经是在降级路径上，
    逐个重复重试只会成倍增加调用。服务端明确给出的限流等待仍然生效。
    """
    argv = [exe, "chat", "+search-msg", *args, "--page-all", "--order", "asc",
            "--no-reactions", "--start", start, "--end", end,
            "--profile", profile, "--format", "json"]
    delays = _shape_delays(source) if retry_shape else []
    used = 0
    server_retried = False
    while True:
        code, stdout, stderr = runner(argv, timeout=600)
        if not code:
            return normalize(stdout, source, start, end), None, False
        text = stdout + "\n" + stderr
        shape = _is_missing_collection(text)
        retryable, server_delay = _retryable_dws_error(text)
        if not retryable or not (not stdout.strip() or _dws_error(stdout)):
            break
        if shape:
            if used >= len(delays):
                break
            delay = delays[used]
            used += 1
        else:
            if server_retried:
                break
            server_retried = True
            delay = server_delay
        time.sleep(delay)
    return None, _dws_failure_message(text), _is_missing_collection(text)


def _sub_windows(start, end, hours, max_windows):
    """把 [start, end) 切成连续子窗口，总数不超过 max_windows 且恰好覆盖全区间。

    不能恰好覆盖时返回空列表，由调用方失败关闭。
    """
    start_dt, end_dt = stamp(start), stamp(end)
    total = end_dt - start_dt
    if total <= dt.timedelta(0):
        return []
    step = dt.timedelta(hours=max(1, int(hours)))
    if -(-total // step) > max_windows:
        step = dt.timedelta(seconds=-(-int(total.total_seconds()) // max_windows))
    bounds, cursor = [], start_dt
    while cursor < end_dt and len(bounds) < max_windows:
        nxt = min(cursor + step, end_dt)
        bounds.append((cursor.isoformat(), nxt.isoformat()))
        cursor = nxt
    if cursor < end_dt or len(bounds) < 2:
        return []
    return bounds


def _merge(parts, source, start, end, failed_windows):
    """合并子窗口结果：跨窗口按 (conversationId, messageId) 去重，保留全量计数。

    完整性只在「无失败切片且每个切片自身完整」时为真：只要有一个切片失败，
    即使已取得的记录都合法，也不得声称 complete。
    """
    records, seen = [], set()
    pages = returned = failed = warned = duplicates = outside = 0
    for part in parts:
        pages += part["pages_fetched"]
        returned += part["returned_count"]
        failed += part["failed_count"]
        warned += part["warning_count"]
        duplicates += part["duplicates_skipped"]
        outside += part["outside_window_skipped"]
        for row in part["records"]:
            key = (row["conversation_id"], row["message_id"])
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            records.append(row)
    records.sort(key=lambda row: (row["time"], row["conversation_id"], row["message_id"]))
    return {"window": {"start": start, "end": end}, "profile": source.get("profile"),
            "scope": "all_accessible", "scope_basis": "current_profile_searchable_messages",
            "message_timezone": source.get("message_timezone"),
            "complete": failed_windows == 0 and all(part["complete"] for part in parts),
            "collection_strategy": "split", "sub_windows": len(parts),
            "failed_windows": failed_windows,
            "pages_fetched": pages, "returned_count": returned, "failed_count": failed,
            "warning_count": warned, "duplicates_skipped": duplicates,
            "outside_window_skipped": outside, "records": records,
            "redaction": "heuristic_excerpt_not_semantic_summary"}


def _collect_range(source, start, end, runner, exe, profile, args, depth, state):
    """查询 [start, end)，已知形状失败时二分降级；depth 限制还可以二分几次。

    端到端观测：同一账号、同一命令的宽窗口会间歇性返回「下游缺少明确的集合字段」。
    出现该错误时把区间切成窄片重查，已观测到能取回数据（同一 6h 区间连续两次失败，
    拆成两个 3h 后成功）。根因仍在上游/dws，尚未完全确定，所以这里只做有界只读降级：
    全部切片仍失败时按原诊断失败关闭，并保留已取得证据。
    """
    if state["queries"] >= state["budget"]:
        state["failures"] += 1
        return []
    state["queries"] += 1
    try:
        data, _error, shape = _search(source, start, end, runner, exe, profile, args,
                                      retry_shape=False)
    except QueryError:
        data, shape = None, False
    if data is not None:
        if not data["complete"]:
            state["failures"] += 1
        state["shape_streak"] = 0
        return [data]
    if shape and depth > 0:
        start_dt, end_dt = stamp(start), stamp(end)
        mid = start_dt + (end_dt - start_dt) / 2
        if start_dt < mid < end_dt:
            left = _collect_range(source, start_dt.isoformat(), mid.isoformat(), runner,
                                  exe, profile, args, depth - 1, state)
            right = _collect_range(source, mid.isoformat(), end_dt.isoformat(), runner,
                                   exe, profile, args, depth - 1, state)
            return left + right
    state["failures"] += 1
    if shape:
        state["shape_streak"] = state.get("shape_streak", 0) + 1
    else:
        state["shape_streak"] = 0
    return []


def collect(source, start, end, runner):
    empty = {"complete": False, "records": []}
    try:
        exe, profile, _, args = settings(source)
        if stamp(start) >= stamp(end):
            raise QueryError("钉钉时间窗口无效")
        code, stdout, _ = runner([exe, "auth", "status", "--profile", profile, "--format", "json"])
        try:
            auth = json.loads(stdout) if code == 0 else None
        except ValueError:
            auth = None
        corp, user = profile.split(":")
        if (not isinstance(auth, dict) or auth.get("authenticated") is not True
                or auth.get("corp_id") != corp or auth.get("user_id") != user):
            raise QueryError("dws 未认证或账号不匹配；停止采集")
        try:
            data, error, shape_failure = _search(source, start, end, runner, exe, profile, args)
        except QueryError as exc:
            data, error, shape_failure = None, str(exc), False
        if error is None:
            if not data["complete"]:
                return data, "dws 查询不完整：分页截断、富化失败或完整性警告；仅保留已取得证据"
            return data, None
        # 已观测到：宽窗口触发下游集合字段缺失，窄窗口正常。只读降级：
        # 按有界子窗口覆盖同一区间再合并，不改变请求区间语义。
        if shape_failure:
            top = _sub_windows(start, end, source.get("fallback_window_hours", 3),
                               source.get("max_sub_windows", 12))
            budget = 2 * max(2, int(source.get("max_sub_windows", 12)))
            state = {"queries": 0, "failures": 0, "budget": budget, "shape_streak": 0}
            depth = int(source.get("split_max_depth", 2))
            parts = []
            for sub_start, sub_end in top:
                # 熔断：连续多次形状失败且一无所获时，判定上游处于故障时段，
                # 停止剩余切片，避免对已降级的上游继续无效调用。
                if state.get("shape_streak", 0) >= 8 and not parts:
                    break
                parts.extend(_collect_range(source, sub_start, sub_end, runner, exe, profile,
                                            args, depth, state))
            if not parts:
                raise QueryError(error)
            merged = _merge(parts, source, start, end, state["failures"])
            if state["failures"]:
                return merged, ("dws 分窗采集不完整（%d 个切片失败或不完整）；"
                                "仅保留已取得证据" % state["failures"])
            if not merged["complete"]:
                return merged, "dws 分窗采集不完整：存在截断、富化失败或完整性警告；仅保留已取得证据"
            return merged, None
        raise QueryError(error)
    except QueryError as exc:
        return empty, str(exc)
