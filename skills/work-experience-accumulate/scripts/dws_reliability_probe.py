#!/usr/bin/env python3
"""dws_reliability_probe.py — 消息读取入口的可靠性采样工具。

用途：在 dws 故障时段，对同一时间窗口分别采样多条消息读取入口，比较各自的成功率，
为 references/dws-troubleshooting.md 提供证据。只读：不保存消息内容，只输出
计数、错误类别和耗时统计。

采样入口：
  search        dws chat +search-msg      （work-experience 的历史采集入口）
  list_all      dws chat message list-all （本地时间格式的跨会话读取）
  chat_messages dws chat +chat-messages   （zentao-bugfix 监听的拉取通道，可选，
                                           需 --conversation-id）

用法：
  python dws_reliability_probe.py --workdir <项目目录> \
      [--window-hours 24] [--rounds 5] [--entries search,list_all] \
      [--conversation-id <openDingTalkId>] [--out result.json]

输出：JSON。每行一次尝试（entry/ok/class/count/seconds），最后是按入口的汇总。
失败时只记录错误类别（shape/dws_error/unknown），不保留 dws 原始错误文本。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dingtalk_query as dq
import work_experience as we

ENTRIES = ("search", "list_all", "chat_messages")


def classify(out_bytes: int, err_text: str) -> str:
    """把一次尝试归为 ok / shape / dws_error:<码> / unknown，不保留原始文本。"""
    if out_bytes > 0:
        return "ok"
    if dq._is_missing_collection(err_text):
        return "shape"
    error = dq._dws_error(err_text)
    if error:
        return "dws_error:%s" % (error.get("server_error_code") or error.get("code") or "unknown")
    return "unknown"


def message_count(entry: str, stdout: str) -> int | None:
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    if entry == "search":
        count = data.get("count") if isinstance(data, dict) else None
        return count if isinstance(count, int) else None
    result = data.get("result") if isinstance(data, dict) else None
    conversations = result.get("conversationMessagesList") if isinstance(result, dict) else None
    if not isinstance(conversations, list):
        return None
    total = 0
    for conv in conversations:
        if isinstance(conv, dict) and isinstance(conv.get("messages"), list):
            total += len(conv["messages"])
    return total


def probe_once(entry: str, exe: str, profile: str, tz: dt.tzinfo, args: list[str],
               start: str, end: str, conversation_id: str,
               runner) -> dict:
    """执行一次采样。返回 {ok, class, count, seconds}；不保留原始输出。"""
    if entry == "search":
        argv = dq._search_argv(exe, profile, args, start, end)
    elif entry == "list_all":
        pairs = dict(zip(args[::2], args[1::2]))
        argv = dq._list_all_argv(exe, profile,
                                 dq.stamp(start).astimezone(tz).strftime(dq.LIST_ALL_FORMAT),
                                 dq.stamp(end).astimezone(tz).strftime(dq.LIST_ALL_FORMAT),
                                 pairs.get("--limit", "30"), pairs.get("--page-limit", "40"))
    elif entry == "chat_messages":
        argv = [exe, "chat", "+chat-messages", "--open-dingtalk-id", conversation_id,
                "--limit", "50", "-f", "json", "--profile", profile]
    else:
        raise ValueError("未知采样入口: %s" % entry)
    started = dt.datetime.now()
    code, stdout, stderr = runner(argv, timeout=600)
    seconds = round((dt.datetime.now() - started).total_seconds(), 1)
    out_bytes = len(stdout.encode("utf-8", errors="replace"))
    kind = classify(out_bytes, stderr)
    return {"entry": entry, "ok": kind == "ok", "class": kind,
            "count": message_count(entry, stdout) if kind == "ok" else None,
            "seconds": seconds}


def summarize(rows: list[dict]) -> dict:
    """按入口汇总：成功/失败次数、错误类别分布、成功时的消息数列表。"""
    summary: dict[str, dict] = {}
    for row in rows:
        entry = summary.setdefault(row["entry"], {"ok": 0, "fail": 0, "by_class": {}, "counts": []})
        if row["ok"]:
            entry["ok"] += 1
            if isinstance(row.get("count"), int):
                entry["counts"].append(row["count"])
        else:
            entry["fail"] += 1
            entry["by_class"][row["class"]] = entry["by_class"].get(row["class"], 0) + 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--entries", default="search,list_all")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    source = we.load_config(args.workdir).get("dingtalk", {})
    exe, profile, tz, dws_args = dq.settings(source)
    entries = [e.strip() for e in args.entries.split(",") if e.strip()]
    unknown = [e for e in entries if e not in ENTRIES]
    if unknown or not entries:
        parser.error("--entries 只支持: %s" % ", ".join(ENTRIES))
    if "chat_messages" in entries and not args.conversation_id:
        parser.error("采样 chat_messages 需要 --conversation-id")
    if args.rounds < 1 or args.rounds > 50:
        parser.error("--rounds 必须在 1-50 之间")
    if not (1 <= args.window_hours <= 168):
        parser.error("--window-hours 必须在 1-168 之间")

    end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    start = end - dt.timedelta(hours=args.window_hours)
    rows = []
    for round_no in range(1, args.rounds + 1):
        for entry in entries:
            row = probe_once(entry, exe, profile, tz, dws_args, start.isoformat(),
                             end.isoformat(), args.conversation_id, we.run_argv)
            row["round"] = round_no
            rows.append(row)
            print(json.dumps({"round": round_no, "entry": entry, "ok": row["ok"],
                              "class": row["class"], "count": row["count"],
                              "seconds": row["seconds"]}, ensure_ascii=False), file=sys.stderr)
    payload = {"window": {"start": start.isoformat(), "end": end.isoformat()},
               "window_hours": args.window_hours, "rounds": args.rounds,
               "profile": profile, "summary": summarize(rows), "attempts": rows}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
