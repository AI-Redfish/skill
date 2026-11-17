#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright"]
# ///
"""Boss直聘自动投递：按 .env 筛选条件遍历搜索结果，逐个「点卡片→详情面板→立即沟通」，达到当日上限停止。

用法：uv run boss_apply.py [--limit N] [--dry-run]
产物：.agents/out/auto-browser-boss/apply-YYYYMMDD.jsonl
已知限制：薪资数字被 Boss 字体混淆（.job-salary 文本为 -K），记录保留原样。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_common as bc  # noqa: E402

# ---------------- 选择器常量（失效时与 references/selectors.md 同步更新） ----------------
SEL = {
    "job_cards": "li.job-card-box",
    "card_link": "a.job-name[href*='/job_detail/']",
    "card_salary": ".job-salary",
    "card_location": ".company-location",
    "card_company": ".boss-name",
    "card_tags": ".job-info .tag-list li",
    "detail_panel": ".job-detail-box",
    "detail_chat_btn": ".job-detail-op a.op-btn.op-btn-chat",
}

JS_CARDS = r"""() => {
  const cards = document.querySelectorAll('""" + SEL["job_cards"] + r"""');
  return [...cards].map(c => {
    const g = s => { const e = c.querySelector(s); return e ? e.innerText.trim() : ''; };
    const link = c.querySelector("a[href*='/job_detail/']");
    return {
      job: g('.job-name'), salary: g('.job-salary'), area: g('.company-location'),
      tags: [...c.querySelectorAll('.job-info .tag-list li')].map(e => e.innerText.trim()),
      company: g('.boss-name'), href: link ? link.href : '',
    };
  });
}"""

# 投递链：点卡片(选中,右侧详情打开) → 等详情面板 → 点「立即沟通」
JS_CLICK_CARD = r"""(i) => {
  const cards = document.querySelectorAll('""" + SEL["job_cards"] + r"""');
  const c = cards[i];
  if (!c) return 'no_card';
  c.click();
  return 'clicked';
}"""

JS_DETAIL_CHAT = r"""() => {
  const btn = document.querySelector('""" + SEL["detail_chat_btn"] + r"""');
  if (!btn) return 'no_detail_btn';
  const txt = (btn.innerText || '').trim();
  if (/已沟通|继续沟通/.test(txt)) return 'already_' + txt;
  btn.click();
  return 'chat_clicked';
}"""

JS_MODAL = r"""() => {
  // 沟通后可能弹出确认面板，有则点确认
  const btns = [...document.querySelectorAll('button, [class*="dialog"] a, [class*="dialog"] span')];
  const target = btns.find(b => /^(继续沟通|打招呼|发送|确定)$/.test((b.innerText || '').trim()));
  if (target) { target.click(); return 'modal_clicked'; }
  return 'none';
}"""

JS_DETAIL_INFO = r"""() => {
  // 详情面板补充信息（HR 名等，失败不影响主流程）
  const panel = document.querySelector('.job-detail-box') || document.body;
  const g = s => { const e = panel.querySelector(s); return e ? e.innerText.trim().slice(0, 60) : ''; };
  return {hr: g('.start-chat-btn'), jobFull: g('.name')};
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多投递数（0=只按每日上限）")
    ap.add_argument("--dry-run", action="store_true", help="只读列表不实际投递")
    ap.add_argument("--query", default="", help="岗位名（覆盖 .env，单组合运行）")
    ap.add_argument("--city", default="", help="城市编码（覆盖 .env，单组合运行）")
    args = ap.parse_args()

    env = bc.load_env()
    queries = [q.strip() for q in (args.query or env["BOSS_QUERY"]).split(",") if q.strip()]
    cities = [c.strip() for c in (args.city or env["BOSS_CITY_CODE"]).split(",") if c.strip()]
    if args.query or args.city:
        # 命令行指定时只跑该组合（推荐：避免连续切换搜索页触发风控）
        pairs = [(args.query or queries[0], args.city or cities[0])]
    else:
        pairs = [(q, c) for q in queries for c in cities]
    if not queries or not cities:
        raise SystemExit("缺少 BOSS_QUERY / BOSS_CITY_CODE：请在 .agents/.env 配置（逗号分隔多值）")
    daily_limit = int(env.get("BOSS_DAILY_LIMIT", "50"))
    delay_min = float(env.get("BOSS_DELAY_MIN", 3))
    delay_max = float(env.get("BOSS_DELAY_MAX", 8))
    done_today = bc.today_count("apply")
    pairs = [(q, c) for q in queries for c in cities]
    print(f"[配置] {len(pairs)} 组合：{' / '.join(q + '@' + c for q, c in pairs)} | 今日已投={done_today}/{daily_limit}")
    if done_today >= daily_limit:
        print("[结果] 已达当日上限，无需投递。")
        return

    bc.start_chrome()
    h = bc.connect()
    page = h.page

    budget_total = min(args.limit or 10 ** 9, daily_limit - done_today)
    applied_total, skipped_total = 0, 0

    for pi, (query, city) in enumerate(pairs):
        if applied_total >= budget_total:
            break
        if pi > 0:
            # 组合切换间隔至少 15 秒，降低连续导航风控风险
            bc.rand_delay(max(delay_max, 15), max(delay_max, 15) + 10)
        url = f"{bc.JOBS_URL}?query={query}&city={city}"
        if env.get("BOSS_SALARY"):
            url += f"&salary={env['BOSS_SALARY']}"
        if env.get("BOSS_EXPERIENCE"):
            url += f"&experience={env['BOSS_EXPERIENCE']}"
        if env.get("BOSS_DEGREE"):
            url += f"&degree={env['BOSS_DEGREE']}"

        st = bc.risk_check(page)
        if st == "login":
            print("[风控] 页面要求重新验证（bticket）。停止，请人工在 Chrome 完成验证后重试。")
            break
        try:
            # SPA 会拦截同域 goto，先跳空白页强制全新加载
            page.goto("about:blank", wait_until="commit", timeout=15000)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[导航] {query}@{city} goto 失败：{str(e)[:60]}，跳过该组合。")
            continue

        # 轮询等卡片渲染（实测 4s 不够，需 8s+）
        cards = []
        for _ in range(6):
            page.wait_for_timeout(3000)
            if bc.risk_check(page) == "login":
                print("[风控] goto 后被弹到登录页。停止，人工验证后重试。")
                return
            cards = bc.ev(page, JS_CARDS) or []
            if cards:
                break
        print(f"[组合 {pi + 1}/{len(pairs)}] {query}@{city} 解析到 {len(cards)} 个职位卡")

        if args.dry_run:
            for c in cards[: args.limit or 5]:
                print(f"  - {c['job']} {c['salary']} {c['area']} | {c['company']} | {','.join(c['tags'])}")
            continue

        budget = budget_total - applied_total
        applied, skipped = 0, 0
        idx = 0
        while applied < budget and idx < len(cards):
            href = cards[idx]["href"]
            try:
                page.evaluate(JS_CLICK_CARD, idx)
            except Exception:
                # 卡片点击会触发 SPA 重建（execution context destroyed），点击本身已生效
                page.wait_for_timeout(3000)
            page.wait_for_timeout(1200)
            r2 = None
            for _ in range(3):
                try:
                    r2 = page.evaluate(JS_DETAIL_CHAT)
                    break
                except Exception:
                    page.wait_for_timeout(3000)  # 页面重建中，等待后重试
            if r2 is None:
                print(f"  [异常] 详情按钮读取失败：{cards[idx]['job']}")
                idx += 1; skipped += 1; continue
            if r2 == "no_detail_btn":
                idx += 1; skipped += 1; continue
            if r2.startswith("already_"):
                print(f"  [{idx}] 已沟通，跳过：{cards[idx]['job']}")
                idx += 1; continue
            page.wait_for_timeout(1200)
            try:
                page.evaluate(JS_MODAL)
            except Exception:
                pass
            extra = bc.ev(page, JS_DETAIL_INFO, retries=2)
            applied += 1
            applied_total += 1
            rec = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "job": cards[idx]["job"], "salary": cards[idx]["salary"],
                "area": cards[idx]["area"], "tags": cards[idx]["tags"],
                "company": cards[idx]["company"], "hr": extra.get("hr", ""),
                "url": href, "btn": r2,
                "query": query, "city": city,
            }
            bc.append_jsonl(f"apply-{time.strftime('%Y%m%d')}.jsonl", rec)
            print(f"  [投递 {applied_total}] {cards[idx]['job']} {cards[idx]['salary']} | {cards[idx]['company']}")
            idx += 1
            if applied < budget and idx < len(cards):
                bc.rand_delay(delay_min, delay_max)

        skipped_total += skipped
        if applied < budget and idx >= len(cards):
            print(f"  [分页] {query}@{city} 本页职位已用尽，未自动翻页。如需继续请手动翻页后再触发。")

    if not args.dry_run:
        print(f"[结果] 本次投递 {applied_total} 个，跳过 {skipped_total}，今日累计 {done_today + applied_total}/{daily_limit}。")
        print(f"[记录] {bc.out_dir() / ('apply-' + time.strftime('%Y%m%d') + '.jsonl')}")
    else:
        print("[dry-run] 结束，未投递。")
    h.browser.close()
    h.pw.stop()


if __name__ == "__main__":
    main()
