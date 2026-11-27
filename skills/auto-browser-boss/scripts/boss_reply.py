#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright"]
# ///
"""Boss直聘自动回复：读取聊天页会话，FAQ 关键词匹配自动回复，答不了的记录并上报。

前置：用户已在 Chrome 手动打开聊天页 /web/geek/chat（脚本不 goto 聊天页——风控拦截）。
用法：uv run boss_reply.py [--dry-run]
产物：.agents/out/YYYYMMDD/auto-browser-boss/unmatched-YYYYMMDD.jsonl（YYYYMMDD 为当天日期目录）
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_common as bc  # noqa: E402

# ---------------- 选择器常量（失效时与 references/selectors.md 同步更新） ----------------
SEL = {
    "conv_container": ".chat-conversation",
    "conv_items": ".chat-conversation li",
    "unread_tab": None,      # 顶部「未读」tab：按文本匹配
    "input": '[contenteditable="true"]',
    "send_btn_text": "发送",
    "msg_bubble": None,      # 精确 class 未验证：候选见 selectors.md
}

JS_CONV_LIST = r"""() => {
  const items = document.querySelectorAll('.chat-conversation li');
  return [...items].map(li => ({
    text: (li.innerText || '').replace(/\s+/g, ' ').slice(0, 120),
    hasUnread: !!li.querySelector('[class*="unread"], [class*="badge"]'),
    unreadNum: (li.querySelector('[class*="unread"], [class*="badge"]') || {}).innerText || '',
  }));
}"""

JS_PICK_UNREAD = r"""() => {
  // 优先点「未读」tab；无则返回全量列表由脚本处理
  const tabs = [...document.querySelectorAll('a, span, div, li')].filter(e => (e.innerText || '').trim() === '未读' && e.children.length === 0);
  if (tabs.length) { tabs[0].click(); return 'unread_tab_clicked'; }
  return 'no_tab';
}"""

JS_CLICK_CONV = r"""(i) => {
  const items = document.querySelectorAll('.chat-conversation li');
  const li = items[i];
  if (!li) return 'no_item';
  li.click();
  return 'clicked';
}"""

JS_READ_LAST_MSGS = r"""() => {
  // 气泡精确结构未验证：取消息区文本 + contenteditable 状态
  const r = {editableCount: document.querySelectorAll('[contenteditable="true"]').length};
  // 候选气泡容器，取最后一个（消息区在右侧）
  const cands = document.querySelectorAll('[class*="msg-item"], [class*="bubble"], .message-item, .kb-chat__list li');
  r.bubbleCount = cands.length;
  r.lastTexts = [...cands].slice(-6).map(e => {
    const cls = typeof e.className === 'string' ? e.className : '';
    return {cls: cls.slice(0, 60), text: (e.innerText || '').replace(/\s+/g, ' ').slice(0, 200)};
  });
  const send = [...document.querySelectorAll('a,button,span,div')].filter(e => (e.innerText || '').trim() === '发送' && e.children.length === 0);
  r.sendBtn = send.length ? {tag: send[0].tagName, cls: (typeof send[0].className === 'string' ? send[0].className : '').slice(0, 60)} : null;
  return r;
}"""

JS_SEND = r"""(text) => {
  const box = document.querySelector('[contenteditable="true"]');
  if (!box) return 'no_input';
  box.focus();
  // 模拟输入（触发 Vue/React 监听）
  document.execCommand('insertText', false, text);
  const send = [...document.querySelectorAll('a,button,span,div')].filter(e => (e.innerText || '').trim() === '发送' && e.children.length === 0);
  if (!send.length) return 'no_send_btn';
  send[0].click();
  return 'sent';
}"""


def load_faq() -> list[dict]:
    """解析 faq.md：`关键词: a|b` + `回复: text` 成对条目。"""
    f = bc.workspace_root() / ".agents" / "data" / "auto-browser-boss" / "faq.md"
    if not f.exists():
        print(f"[缺失] FAQ 文件不存在：{f}")
        print("请先与 AI 共建该文件（每条目两行：关键词: xxx|yyy / 回复: zzz），再重跑。")
        sys.exit(2)
    faqs, cur = [], {}
    for line in f.read_text(encoding="utf-8").splitlines():
        m1 = re.match(r"关键词[:：]\s*(.+)", line.strip())
        m2 = re.match(r"回复[:：]\s*(.+)", line.strip())
        if m1:
            cur = {"kw": [k.strip() for k in re.split(r"[|｜]", m1.group(1)) if k.strip()]}
        elif m2 and cur.get("kw"):
            cur["reply"] = m2.group(1).strip()
            faqs.append(cur)
            cur = {}
    return faqs


def match_faq(text: str, faqs: list[dict]):
    for f in faqs:
        for kw in f["kw"]:
            if kw and kw in text:
                return f
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只读会话与匹配结果，不发送")
    args = ap.parse_args()

    faqs = load_faq()
    print(f"[FAQ] 载入 {len(faqs)} 条规则")

    bc.start_chrome()
    h = bc.connect()
    page = h.page

    st = bc.risk_check(page)
    if st == "login":
        print("[风控] 当前页面要求重新验证（bticket）。请人工在 Chrome 完成登录并打开聊天页后重跑。")
        return
    if st != "ok":
        print(f"[提示] 未找到聊天页（当前 {page.url[:60]}）。")
        print("请人工在 Chrome 点击「消息」打开聊天页 https://www.zhipin.com/web/geek/chat ，")
        print("保持该标签打开，然后重跑本脚本（脚本不自动 goto 聊天页——风控拦截）。")
        return

    # 等会话列表渲染
    convs = []
    for _ in range(6):
        convs = bc.ev(page, JS_CONV_LIST) or []
        if convs:
            break
        page.wait_for_timeout(3000)
    if not convs:
        print("[空] 会话列表未解析到条目。若页面显示正常，说明选择器失效，请更新 selectors.md。")
        return
    print(f"[列表] 会话 {len(convs)} 个")

    # 优先未读 tab；MVP 回退为全量扫描最近会话
    mode = bc.ev(page, JS_PICK_UNREAD, retries=2)
    if mode == "unread_tab_clicked":
        page.wait_for_timeout(2500)
        convs = bc.ev(page, JS_CONV_LIST) or []
        print(f"[未读tab] 过滤后会话 {len(convs)} 个")

    replied, unmatched, skipped = 0, 0, 0
    n = min(len(convs), 20)  # 单次最多处理 20 个会话
    for i in range(n):
        info = convs[i]
        page.evaluate(f"window.__ci = {i}")
        r = bc.ev(page, JS_CLICK_CONV, retries=2)
        if r != "clicked":
            skipped += 1
            continue
        page.wait_for_timeout(2500)

        # 被踢检测：聊天页被跳走即停
        if bc.risk_check(page) != "ok":
            print("[风控] 聊天页被强制跳转，停止本次回复（当天建议不再重试）。")
            break

        detail = bc.ev(page, JS_READ_LAST_MSGS)
        texts = detail.get("lastTexts") or []
        last_from_hr = texts[-1] if texts else None

        if args.dry_run:
            print(f"  [{i}] {info['text'][:50]} | 未读={info['unreadNum'] or '-'} | 末条={last_from_hr['text'][:40] if last_from_hr else '-'}")
            continue

        if not last_from_hr or not detail.get("sendBtn"):
            skipped += 1
            continue
        faq = match_faq(last_from_hr["text"], faqs)
        if not faq:
            unmatched += 1
            bc.append_jsonl(f"unmatched-{time.strftime('%Y%m%d')}.jsonl", {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "conv": info["text"],
                "lastMsg": last_from_hr["text"],
            })
            print(f"  [{i}] 未匹配：{info['text'][:40]}")
            continue
        try:
            r2 = page.evaluate(JS_SEND, faq["reply"])
        except Exception as e:  # noqa: BLE001
            r2 = f"error: {str(e)[:50]}"
        if r2 == "sent":
            replied += 1
            print(f"  [{i}] 已回复：{info['text'][:40]} -> {faq['reply'][:30]}")
        else:
            unmatched += 1
            bc.append_jsonl(f"unmatched-{time.strftime('%Y%m%d')}.jsonl", {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "conv": info["text"], "lastMsg": last_from_hr["text"], "sendErr": r2,
            })
            print(f"  [{i}] 发送失败({r2})：{info['text'][:40]}")
        bc.rand_delay(5, 12)

    if args.dry_run:
        print("[dry-run] 结束，未发送。")
    else:
        print(f"[结果] 回复 {replied} | 未匹配/失败 {unmatched} | 跳过 {skipped}")
        if unmatched:
            print(f"[上报] 未回复会话见 {bc.day_dir() / ('unmatched-' + time.strftime('%Y%m%d') + '.jsonl')}")
    h.browser.close()
    h.pw.stop()


if __name__ == "__main__":
    main()
