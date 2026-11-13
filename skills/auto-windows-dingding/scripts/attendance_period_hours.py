#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""考勤周期工时核算：应需工时 / 应累计工时 / 实际打卡时长 / 每日扣休后达标核对。

用法示例:
  python3 attendance_period_hours.py --org 中科医信 --start 2026-10-26 --end 2026-11-25
  python3 attendance_period_hours.py --profile corpId:userId --start ... --end ... \
      [--daily-hours 8] [--deduct-hours 1.5] [--today 2026-11-12] [--json]

所有数据通过本机关已登录的 DWS 账号实时查询；只读，不写任何考勤配置。
"""

import argparse
import datetime as dt
import json
import subprocess
import sys

TZ = dt.timezone(dt.timedelta(hours=8))  # 钉钉考勤统一为东八区

STANDARD_TYPES = ("OnDuty", "OffDuty")


def ms_to_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, TZ).date()


def ms_to_hm(ms):
    return dt.datetime.fromtimestamp(ms / 1000, TZ).strftime("%H:%M")


def run_dws(profile, args):
    """执行 dws 并解析 JSON；错误即抛异常，不静默兜底。profile 为 None 时不带选择器。"""
    cmd = ["dws"] + (["--profile", profile] if profile else []) + args + ["--format", "json"]
    # dws 输出恒为 UTF-8；Windows 默认 GBK 会解码失败，必须显式指定
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if p.returncode != 0:
        raise RuntimeError("命令失败: %s\n%s" % (" ".join(cmd), (p.stderr or p.stdout)[:500]))
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("非 JSON 输出: %s\n%s" % (" ".join(cmd), p.stdout[:500]))


# ---- 身份与 profile 解析 ----------------------------------------------------

def resolve_profile(args):
    """返回 (selector, corpName)。--profile 优先；--org 按组织名唯一匹配；默认 currentProfile。"""
    out = run_dws(None, ["profile", "list"])
    profiles = out.get("profiles") or []
    if args.profile:
        sel = args.profile
        matched = [p for p in profiles if p["profile"] == sel]
        return sel, (matched[0]["corpName"] if matched else sel)
    if args.org:
        cands = [p for p in profiles if p.get("corpName") == args.org]
        if not cands:
            names = sorted({p.get("corpName", "?") for p in profiles})
            raise SystemExit("本机未登录组织「%s」。已登录: %s；如需新增请先 dws auth login --device"
                             % (args.org, ", ".join(names) or "(无)"))
        orgs = {p["corpId"] for p in cands}
        if len(orgs) > 1:
            raise SystemExit("组织名「%s」重名，请改用 --profile corpId:userId（见 dws profile list）" % args.org)
        cur = [p for p in cands if p.get("isOrgCurrent") or p.get("isCurrent")]
        if len(cur) > 1 or (len(cur) == 0 and len(cands) > 1):
            raise SystemExit("组织「%s」有多个账号且无默认账号，请指定 --profile corpId:userId" % args.org)
        p = cur[0] if cur else cands[0]
        return p["profile"], p["corpName"]
    sel = out.get("currentProfile")
    if not sel:
        if len(profiles) == 1:
            sel = profiles[0]["profile"]
        else:
            raise SystemExit("未找到当前 profile，请用 --org 或 --profile 指定")
    matched = [p for p in profiles if p["profile"] == sel]
    return sel, (matched[0]["corpName"] if matched else sel)


def get_self(profile):
    out = run_dws(profile, ["contact", "user", "get-self"])
    m = out["result"][0]["orgEmployeeModel"]
    return m["userId"], m.get("orgUserName") or "", m.get("orgName") or ""


# ---- 数据拉取 --------------------------------------------------------------

def fetch_schedule(profile, user, start, end):
    """排班 -> ({date: {"rest","on","off","cls"}}, 无排班覆盖的日期数)。只查询已导入排班，不写。"""
    out = run_dws(profile, ["attendance", "schedule", "get", "--users", user,
                            "--start", start.isoformat(), "--end", end.isoformat()])
    items = out.get("result") or []
    days = {}
    covered = set()
    for s in items:
        if not s.get("workDate"):
            continue
        d = ms_to_date(s["workDate"])
        if not (start <= d <= end):
            continue
        covered.add(d)
        info = days.setdefault(d, {"rest": True, "on": None, "off": None, "cls": s.get("className")})
        if s.get("isRest") == "N":
            info["rest"] = False
            t = s.get("checkDateTime") or s.get("checkTimeForFlex")
            if t:
                if s.get("checkType") == "OnDuty":
                    info["on"] = t if info["on"] is None else min(info["on"], t)
                elif s.get("checkType") == "OffDuty":
                    info["off"] = t if info["off"] is None else max(info["off"], t)
    total_days = (end - start).days + 1
    return days, total_days - len(covered)


def fetch_records(profile, user, start, end):
    """打卡流水。窗口≤28天且请求 end=窗口末+1 天（+check-record 实测不含结束日）。"""
    days, invalid = {}, []
    cur = start
    while cur <= end:
        w_end = min(end, cur + dt.timedelta(days=27))
        out = run_dws(profile, ["attendance", "+check-record", "--users", user,
                                "--start", cur.isoformat(),
                                "--end", (w_end + dt.timedelta(days=1)).isoformat()])
        for r in out.get("data", {}).get("records", []) or []:
            ct, t = r.get("checkType"), r.get("userCheckTime")
            if ct in STANDARD_TYPES and t and r.get("workDate"):
                d = ms_to_date(r["workDate"])
                if start <= d <= end:
                    e = days.setdefault(d, {"on": [], "off": []})
                    e["on" if ct == "OnDuty" else "off"].append((t, r.get("sourceType")))
            else:
                msg = ""
                try:
                    msg = json.loads(r.get("features") or "{}").get("errMsg", "")
                except (ValueError, TypeError):
                    pass
                invalid.append({"date": ms_to_date(r["workDate"]).isoformat() if r.get("workDate") else None,
                                "errMsg": msg})
        cur = w_end + dt.timedelta(days=1)
    return days, invalid


def fetch_approvals(profile, user, start, end):
    """请假/加班/出差外出/补卡审批 -> {date: [item...]}（status 非空时按≈已通过 4 采信）。"""
    days = {}
    cur = start
    while cur <= end:
        w_end = min(end, cur + dt.timedelta(days=27))
        out = run_dws(profile, ["attendance", "+list-approve", "--users", user,
                                "--types", "overtime,trip,leave,patch",
                                "--start", cur.isoformat(),
                                "--end", (w_end + dt.timedelta(days=1)).isoformat()])
        for a in out.get("data", {}).get("approvals", []) or []:
            if a.get("status") not in (None, 4):
                continue
            if not a.get("beginTime"):
                continue
            b = ms_to_date(a["beginTime"])
            e = ms_to_date(a.get("endTime") or a["beginTime"])
            d = b
            while d <= min(e, end):
                if d >= start:
                    days.setdefault(d, []).append(a)
                d += dt.timedelta(days=1)
        cur = w_end + dt.timedelta(days=1)
    return days


def leave_hours(a, daily_hours):
    du = (a.get("durationUnit") or "").upper()
    try:
        v = float(a.get("duration"))
    except (TypeError, ValueError):
        return None
    return v * daily_hours if du == "DAY" else v


# ---- 核算与输出 -------------------------------------------------------------

def analyze(schedule, records, approvals, invalid, missing_sched_days,
            start, end, today, daily_hours, deduct_hours):
    warnings = []
    if not schedule:
        warnings.append("排班接口未返回数据，工作日按周一至周五估算，请以考勤组实际排班为准")
    cur, workdays = start, []
    while cur <= end:
        if cur in schedule:
            if not schedule[cur]["rest"]:
                workdays.append(cur)
        elif cur.weekday() < 5:
            workdays.append(cur)
        cur += dt.timedelta(days=1)
    if missing_sched_days and schedule:
        warnings.append("有 %d 天无排班记录（含周末），已按非工作日处理" % missing_sched_days)

    through = min(today, end)
    rows = []
    for d in workdays:
        if d > through:
            continue
        r = records.get(d, {"on": [], "off": []})
        on_ts = [t for t, _ in r["on"]]
        off_ts = [t for t, _ in r["off"]]
        notes = []
        if on_ts and any(src == "APPROVE" for t, src in r["on"] if t == min(on_ts)):
            notes.append("上班卡=补卡")
        leave_h = 0.0
        for a in approvals.get(d, []):
            if "请假" in (a.get("tagName") or ""):
                lh = leave_hours(a, daily_hours)
                if lh:
                    leave_h += lh
                    notes.append("请假%s(%s %s起)" % (a.get("subType") or a.get("tagName"),
                                                      a.get("duration") or "?",
                                                      ms_to_hm(a["beginTime"])))
            if a.get("tagName") == "补卡申请":
                notes.append("含补卡申请")
        if on_ts and off_ts:
            span = (max(off_ts) - min(on_ts)) / 3600000
            net = span - deduct_hours
        else:
            span = net = None
            notes.append("缺" + ("上班卡" if not on_ts else "") + ("下班卡" if not off_ts else ""))
        need = daily_hours - (leave_h if on_ts else min(leave_h, daily_hours))
        if need <= 0 and not on_ts:
            status = "全天请假"
            ok = True
        elif net is None:
            status, ok = ("部分请假" if leave_h else "无打卡"), False
        else:
            ok = net >= need - 1e-9
            status = "满足" if ok else ("请假未补足" if leave_h else "不满足")
        rows.append({"date": d.isoformat(),
                     "on": ms_to_hm(min(on_ts)) if on_ts else None,
                     "off": ms_to_hm(max(off_ts)) if off_ts else None,
                     "span": round(span, 2) if span is not None else None,
                     "net": round(net, 2) if net is not None else None,
                     "need": round(need, 2), "status": status, "ok": ok,
                     "note": "；".join(notes)})

    done_workdays = len(rows)
    clocked = [x for x in rows if x["span"] is not None]
    total_span = round(sum(x["span"] for x in clocked), 2)
    total_net = round(sum(x["net"] for x in clocked), 2)
    return {
        "period": [start.isoformat(), end.isoformat()], "through": through.isoformat(),
        "daily_hours": daily_hours, "deduct_hours": deduct_hours,
        "workdays_total": len(workdays), "need_total_hours": len(workdays) * daily_hours,
        "workdays_done": done_workdays, "need_done_hours": round(done_workdays * daily_hours, 2),
        "clocked_days": len(clocked), "total_span_hours": total_span,
        "total_net_hours": total_net,
        "pass_days": sum(1 for x in rows if x["ok"]),
        "fail_days": [x["date"] for x in rows if not x["ok"]],
        "rows": rows, "invalid_records": invalid, "warnings": warnings,
    }


def render(res):
    s = res["summary"]
    out = []
    out.append("### 结论")
    out.append("- 周期 %s ~ %s 工作日 **%d 天**，按 %.0f 小时/天共需 **%.0f 小时**"
               % (s["period"][0], s["period"][1], s["workdays_total"],
                  s["daily_hours"], s["need_total_hours"]))
    out.append("- 截止 %s 已过工作日 %d 天，应累计 **%.0f 小时**"
               % (s["through"], s["workdays_done"], s["need_done_hours"]))
    out.append("- 实际打卡 %d 天，打卡跨度合计 **%.2f 小时**；每天扣 %.1f 小时后净值 **%.2f 小时**"
               % (s["clocked_days"], s["total_span_hours"], s["deduct_hours"], s["total_net_hours"]))
    out.append("- 每日扣休后满足 %.0f 小时：应打卡 %d 天中 **%d 天满足**；不达标/待核日：%s"
               % (s["daily_hours"], s["workdays_done"], s["pass_days"],
                  "、".join(s["fail_days"]) or "无"))
    out.append("\n### 逐日明细")
    out.append("| 日期 | 上班 | 下班 | 跨度h | 扣%.1fh后 | 当日应达 | 判定 | 备注 |" % s["deduct_hours"])
    out.append("|---|---|---|---|---|---|---|---|")
    for r in s["rows"]:
        span_s = "%.2f" % r["span"] if r["span"] is not None else "-"
        net_s = "%.2f" % r["net"] if r["net"] is not None else "-"
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["date"], r["on"] or "-", r["off"] or "-",
            span_s, net_s,
            ("%g" % r["need"]), ("✔ " if r["ok"] else "✘ ") + r["status"], r["note"] or ""))
    for w in s["warnings"]:
        out.append("\n> 注意：%s" % w)
    for i in s["invalid_records"]:
        if i.get("errMsg"):
            out.append("\n> 异常流水 %s：%s" % (i["date"], i["errMsg"]))
    return "\n".join(out)


def parse_date(s):
    return dt.date.fromisoformat(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", help="目标组织名（须为本机已登录 profile）")
    ap.add_argument("--profile", help="稳定选择器 corpId:userId（优先于 --org）")
    ap.add_argument("--user", help="指定 userId（默认为该 profile 登录用户本人）")
    ap.add_argument("--start", required=True, type=parse_date)
    ap.add_argument("--end", required=True, type=parse_date)
    ap.add_argument("--today", type=parse_date, help="“截止目前”基准日（默认真实今天）")
    ap.add_argument("--daily-hours", type=float, default=8.0)
    ap.add_argument("--deduct-hours", type=float, default=1.5)
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    a = ap.parse_args()
    # 控制台/管道在 Windows 默认 GBK，报告含 ✔/✘ 等字符，统一改用 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if a.end < a.start:
        raise SystemExit("--end 必须不早于 --start")

    selector, corp = resolve_profile(a)
    user, uname, org = get_self(selector)
    if a.org and org != a.org:
        raise SystemExit("profile %s 实际组织为「%s」，与 --org「%s」不符" % (selector, org, a.org))
    print("[身份] 组织: %s | 用户: %s (%s)" % (org, uname, user), file=sys.stderr)
    uid = a.user or user

    schedule, missing = fetch_schedule(selector, uid, a.start, a.end)
    records, invalid = fetch_records(selector, uid, a.start, a.end)
    approvals = fetch_approvals(selector, uid, a.start, a.end)
    today = a.today or dt.datetime.now(TZ).date()
    summary = analyze(schedule, records, approvals, invalid, missing,
                      a.start, a.end, today, a.daily_hours, a.deduct_hours)
    res = {"identity": {"corp": org, "user": uname, "userId": user}, "summary": summary}
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))


if __name__ == "__main__":
    main()
