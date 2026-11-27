#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright"]
# ///
"""Boss直聘自动投递：按 .env 筛选条件遍历搜索结果，逐个「点卡片→详情面板→立即沟通」，达到当日上限停止。

用法：uv run boss_apply.py [--limit N] [--dry-run]
产物：.agents/out/YYYYMMDD/auto-browser-boss/apply-YYYYMMDD.jsonl（YYYYMMDD 为当天日期目录）
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
    print(f"[配置] {len(pairs)} 组合：{' / '.join(q + '@' + c for q, c in pairs)} | 今日已投={done_today}/{daily_limit}")
    if done_today >= daily_limit:
        print("[结果] 已达当日上限，无需投递。")
        return

    bc.start_chrome()
    h = bc.connect()

    # —— 接管模式：脚本永不导航（导航已被风控拦截）。使用用户手动打开的搜索页投递 ——
    from urllib.parse import urlparse, parse_qs
    page = None
    cur_query, cur_city = "", ""
    for pg in h.browser.contexts[0].pages:
        if "/web/geek/jobs" in pg.url and "query=" in pg.url:
            qs = parse_qs(urlparse(pg.url).query)
            cur_query = (qs.get("query") or [""])[0]
            cur_city = (qs.get("city") or [""])[0]
            page = pg
            break
    if page is None:
        url = f"{bc.JOBS_URL}?query={queries[0]}&city={cities[0]}"
        print("[需要手动导航] 未发现已打开的搜索页。请在调试 Chrome 手动打开：")
        print(f"  {url}")
        print("打开后说「继续」，脚本接管当前页投递；换城市/岗位也由你手动切换。")
        h.browser.close()
        h.pw.stop()
        return

    query, city = cur_query, cur_city
    if (query, city) not in pairs:
        print(f"[提示] 当前页 {query}@{city} 不在配置组合内，按当前页继续投递。")
    print(f"[接管] 使用手动打开的搜索页：{query}@{city}，脚本不导航。")

    # 轮询等卡片渲染（用户刚打开时可能还在渲染）
    cards = []
    for _ in range(6):
        page.wait_for_timeout(3000)
        if bc.risk_check(page) == "login":
            print("[风控] 页面被弹到登录/验证页。停止，人工处理后再触发。")
            h.browser.close()
            h.pw.stop()
            return
        cards = bc.ev(page, JS_CARDS) or []
        if cards:
            break
    print(f"[列表] {query}@{city} 解析到 {len(cards)} 个职位卡")

    if args.dry_run:
        for c in cards[: args.limit or 10]:
            print(f"  - {c['job']} {c['salary']} {c['area']} | {c['company']} | {','.join(c['tags'])}")
        print("[dry-run] 结束，未投递。")
        h.browser.close()
        h.pw.stop()
        return

    budget = min(args.limit or 10 ** 9, daily_limit - done_today)
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
            rec = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "job": cards[idx]["job"], "salary": cards[idx]["salary"],
                "area": cards[idx]["area"], "tags": cards[idx]["tags"],
                "company": cards[idx]["company"], "hr": extra.get("hr", ""),
                "url": href, "btn": r2,
                "query": query, "city": city,
            }
            bc.append_jsonl(f"apply-{time.strftime('%Y%m%d')}.jsonl", rec)
            print(f"  [投递 {applied}] {cards[idx]['job']} {cards[idx]['salary']} | {cards[idx]['company']}")
            idx += 1
            if applied < budget and idx < len(cards):
                bc.rand_delay(delay_min, delay_max)

    if applied < budget and idx >= len(cards):
        print("[分页] 本页职位已用尽。请手动翻页或切换其他组合的搜索页，然后说「继续」再跑一轮。")

    print(f"[结果] 本次投递 {applied} 个，跳过 {skipped}，今日累计 {done_today + applied}/{daily_limit}。")
    print(f"[记录] {bc.day_dir() / ('apply-' + time.strftime('%Y%m%d') + '.jsonl')}")
    h.browser.close()
    h.pw.stop()


if __name__ == "__main__":
    main()
