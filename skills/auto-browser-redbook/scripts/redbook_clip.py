#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.45"]
# ///
"""redbook_clip.py — 小红书单篇笔记沉淀（CDP 附着真实 Chrome）。

用途：抓取指定笔记页的标题/作者/正文/图片/实况照片/视频/话题标签，
输出 note.md + 媒体。
边界：只抓取用户主动指定的单篇（--url 或 --tab 当前页）；
不滚动、不批量、不自动浏览。

用法：
  uv run redbook_clip.py --url "<笔记链接>" [--out DIR] [--port 9342] [--timeout SEC]
  uv run redbook_clip.py --tab <标题或URL子串>     # 抓当前浏览器已打开的笔记页
  uv run redbook_clip.py --list [--port 9342]      # 列出已开标签页

链接需带 xsec_token（分享/复制链接自带）；拿不到 token 时先在浏览器手动
打开笔记页，再用 --tab 抓当前页。

输出：JSON 到 stdout（status/dir/files/failures），日志到 stderr。
退出码：0 成功；2 失败。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

XHS_REFERER = "https://www.xiaohongshu.com/"
XHS_HOST_RE = r"(xiaohongshu\.com|xhslink\.com|xhs\.com)"
DEFAULT_OUT_NAME = "clips"
DOWNLOAD_TIMEOUT_SEC = 600

# 注入页面执行的提取函数。优先读 __INITIAL_STATE__（SSR 全量数据），DOM 兜底。
# 与 AgentPhoto xhs-clip-extension/background.js 的 PAGE_EXTRACT 保持同构，
# 含：水合等待（15s）、wrongNote 错存校验、多代视频流结构兼容、实况照片、blocked/notScoped 检测。
EXTRACT_JS = r"""
async () => {
  const currentNoteId = () => {
    const m = location.pathname.match(/\/(?:explore|discovery\/item)\/([0-9a-f]{24})/i)
      || location.pathname.match(/\/([0-9a-f]{24})(?:\/|$)/i);
    return m ? m[1].toLowerCase() : '';
  };
  // 等待目标笔记水合：短链/SPA 跳转后 pathname 才变为 /explore/<id>，noteDetailMap 滞后填充
  let mUrl = currentNoteId();
  {
    const deadline = Date.now() + 15000;
    while (mUrl && Date.now() <= deadline) {
      const map = ((window.__INITIAL_STATE__ || {}).note || {}).noteDetailMap || {};
      if (Object.keys(map).some((k) => k && map[k] && map[k].note
          && k.toLowerCase() === mUrl)) break;
      const nowId = currentNoteId();
      if (nowId === mUrl) await new Promise((r) => setTimeout(r, 400));
      else mUrl = nowId;
    }
  }
  const hit = {};
  const q = (sels, validate) => {
    for (const s of sels) {
      try {
        const el = document.querySelector(s);
        if (el && (!validate || validate(el))) { hit[s] = true; return el; }
      } catch (e) { /* invalid selector */ }
    }
    return null;
  };
  const httpsUrl = (u) => (u || '').replace(/^http:\/\//i, 'https://');
  const cleanText = (t) => (t || '').replace(/\[(话题|活动|地点|视频)\]#/g, '').trim();
  const ogTitle = document.querySelector('meta[property="og:title"]');
  const titleEl = q(['#detail-title', '.note-content .title', 'h1']);
  const domTitle = ((titleEl && titleEl.innerText) || (ogTitle && ogTitle.content) ||
    document.title || '').replace(/\s*-\s*小红书\s*$/, '').trim();
  const notComment = (el) => !/comment/i.test(`${el.className} ${el.id}`);
  const descEl = q(['#detail-desc', '.note-text', '.desc', 'article', 'meta[name="description"]'], notComment);
  const domText = descEl ?
    cleanText((descEl.innerText || '').trim() || (descEl.content || '').trim()) : '';
  const authorEl = q(['.author-wrapper .username', '[class*="author"] .username',
    '[class*="author"] [class*="name"]']);
  const domAuthor = authorEl ? (authorEl.innerText || '').trim() : '';
  const isMeta = !!(descEl && descEl.tagName === 'META');
  // 内容容器：标题+正文最小公共祖先，向上找到第一个含大图的层级；
  // 推荐流/侧栏的大图集合不在该容器内，不会被带走
  let root = document.body;
  if (descEl && !isMeta) {
    let base = descEl;
    if (titleEl) {
      let n = descEl;
      while (n && !n.contains(titleEl)) n = n.parentElement;
      if (n) base = n;
    }
    const bigCount = (el) => [...el.querySelectorAll('img')].filter((i) => {
      const w = i.naturalWidth || 0;
      if (w > 0 && w < 200) return false;
      return !/avatar|icon|emoji|logo|qrcode/i.test(i.currentSrc || i.src || '');
    }).length;
    root = base;
    let node = base;
    while (node && node.parentElement && node.parentElement !== document.documentElement
      && bigCount(node) === 0) {
      root = node.parentElement;
      node = root;
    }
  }
  const seen = new Set();
  const domImages = [];
  for (const img of root.querySelectorAll('img')) {
    const src = img.currentSrc || img.src || '';
    if (!src) continue;
    if (!src.startsWith('data:') && !/^https?:/i.test(src)) continue;
    const w = img.naturalWidth || 0;
    if (w > 0 && w < 50) continue;
    if (/avatar|icon|emoji|logo|qrcode/i.test(src)) continue;
    const key = src.startsWith('data:') ? src : src.split('?')[0];
    if (seen.has(key)) continue;
    seen.add(key);
    domImages.push(src);
  }
  // __INITIAL_STATE__ 提取：流字段新版为 EF4(mp4 含音轨)/EF5(fmp4)，
  // 旧版 h264/h265/av1 一并兼容；Live Photo 在 imageList 项的 videoUrl
  let st = null;
  let noteMatched = !mUrl;
  let extractedNoteId = '';
  try {
    const noteState = (window.__INITIAL_STATE__ || {}).note || {};
    const map = noteState.noteDetailMap || {};
    let keys = Object.keys(map).filter((k) => k && map[k] && map[k].note);
    if (mUrl) {
      const hitKey = keys.find((k) => k.toLowerCase() === mUrl);
      if (hitKey) {
        keys = [hitKey];
        noteMatched = true;
      } else if (keys.length) {
        // 状态里没有目标笔记：不猜，由 DOM 兜底（st 保持 null）
        keys = [];
      }
    }
    for (const k of keys) {
      const n = map[k].note;
      if (!n.desc && !(n.imageList || []).length && !n.video) continue;
      const images = [];
      for (const im of n.imageList || []) {
        if (!im) continue;
        const url = httpsUrl(im.urlDefault ||
          ((im.infoList || []).filter(Boolean).map((s) => s.url).filter(Boolean).pop()) || '');
        if (!url && !im.videoUrl) continue;
        images.push({ url, live: !!im.livePhoto, liveVideo: httpsUrl(im.videoUrl) });
      }
      let video = null;
      let videoDiag = null;
      const videoRaw = n.video || null;
      const stream = (videoRaw && videoRaw.media && videoRaw.media.stream) || {};
      const cands = [];
      const streamKeys = Object.keys(stream);
      for (const key of streamKeys) {
        const group = stream[key];
        if (Array.isArray(group)) {
          for (const s of group || []) {
            if (s && (s.masterUrl || (s.backupUrls || []).length)) cands.push(s);
          }
        } else if (group && typeof group === 'object') {
          if (group.masterUrl || (group.backupUrls || []).length) {
            cands.push(group);
          } else {
            for (const s of Object.values(group)) {
              if (s && typeof s === 'object' && (s.masterUrl || (s.backupUrls || []).length)) cands.push(s);
            }
          }
        }
      }
      if (cands.length) {
        // mp4 容器（含音轨）优先，再按 weight（画质权重）取最高
        cands.sort((a, b) => (((b.format === 'mp4') ? 1 : 0) - ((a.format === 'mp4') ? 1 : 0)) ||
          ((b.weight || 0) - (a.weight || 0)));
        const best = cands[0];
        video = { urls: [best.masterUrl].concat(best.backupUrls || []).filter(Boolean).map(httpsUrl),
          format: best.format || 'mp4', size: best.size || 0,
          width: best.width || 0, height: best.height || 0 };
      } else if (videoRaw) {
        videoDiag = { hasVideoField: true,
          mediaKeys: videoRaw.media ? Object.keys(videoRaw.media) : null,
          streamKeys, cands: 0 };
      }
      const tags = ((n.tagList || []).filter(Boolean).map((t) => t && t.name)
        .filter(Boolean));
      st = { title: (n.title || '').trim(), text: cleanText(n.desc),
        author: ((n.user && n.user.nickname) || '').trim(), noteType: n.type || '',
        images, video, tags, videoDiag,
        videoRawJson: videoDiag ? JSON.stringify(videoRaw).slice(0, 2000) : '' };
      extractedNoteId = k;
      break;
    }
    if (mUrl && !noteMatched && st) {
      // 状态水合出的不是链接对应的笔记：宁可不保存，也不存成别的文章
      return { wrongNote: true, wanted: mUrl, got: extractedNoteId, url: location.href };
    }
  } catch (e) { /* state 不可用时走 DOM 兜底 */ }
  const images = st && (st.images.length || st.video) ? st.images
    : domImages.map((s) => ({ url: s, live: false, liveVideo: '' }));
  return { title: (st && st.title) || domTitle,
    author: (st && st.author) || domAuthor,
    text: (st && st.text) || domText,
    images, video: st ? st.video : null, noteType: st ? st.noteType : '',
    tags: st ? (st.tags || []) : [],
    videoDiag: st ? (st.videoDiag || null) : null,
    videoRawJson: st ? (st.videoRawJson || '') : '',
    fromState: !!st, url: location.href,
    blocked: /website-login\/error|error_code=/.test(location.href) ||
      /存在风险|请登录/.test((document.body && document.body.innerText || '').slice(0, 500)),
    notScoped: !st && root === document.body && /xiaohongshu\.com/i.test(location.hostname) };
}
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="小红书单篇笔记沉淀")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--url", help="笔记链接（需带 xsec_token）")
    g.add_argument("--tab", help="按标题或 URL 子串指定浏览器已打开的笔记页")
    ap.add_argument("--out", default=None, help="输出根目录（默认 <cwd>/clips）")
    ap.add_argument("--port", type=int, default=9342, help="CDP 调试端口（默认 9342）")
    ap.add_argument("--timeout", type=int, default=DOWNLOAD_TIMEOUT_SEC,
                    help="单个文件下载超时秒数（默认 600）")
    ap.add_argument("--list", action="store_true", help="列出浏览器已开标签页后退出")
    return ap.parse_args(argv)


def download(url: str, dest: Path, timeout_sec: int) -> int:
    """流式下载；带小红书 Referer 与浏览器 UA。返回字节数。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": c.BROWSER_UA,
        "Referer": XHS_REFERER,
    })
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest.stat().st_size


def yml_str(v) -> str:
    """front matter 字符串统一 JSON 双引号写法（YAML 兼容）。"""
    return json.dumps("" if v is None else str(v), ensure_ascii=False)


def build_note(data: dict, media_lines: list[str], rel_path: str) -> str:
    fm = [
        "---",
        "platform: RedNote",
        f"type: {'video' if data.get('noteType') == 'video' else 'image-text'}",
        f"title: {yml_str(data.get('title', ''))}",
        f"author: {yml_str(data.get('author', ''))}",
        f"url: {yml_str(data.get('url', ''))}",
        f"captured_at: {yml_str(c.now_stamp())}",
        f"path: {yml_str(rel_path)}",
        f"tags: {json.dumps(data.get('tags') or [], ensure_ascii=False)}",
        "---",
        "",
    ]
    tail = []
    if data.get("videoDiag") and not data.get("video"):
        tail = ["", "", f"<!-- video-diag: {json.dumps(data.get('videoDiag'))} "
                f"video-raw: {data.get('videoRawJson', '')} -->"]
    body = [f"# {data.get('title') or '未命名笔记'}", ""]
    if media_lines:
        body += [*media_lines, ""]
    body += [data.get("text") or "（未提取到正文，DOM 选择器可能已变化）"]
    return "\n".join(fm + body + tail)


def video_tag(name: str) -> list[str]:
    """视频用 <video> 标签：图片语法多数渲染器不能播视频。"""
    return [f'<video src="{name}" controls width="100%"></video>', "",
            f"[{name}]({name})（预览器不支持内联播放时点此打开）"]


def next_seq(platform_dir: Path, date_str: str, slug: str) -> str:
    """同一天同标题序号递增（-01 → -02），文件系统实查。"""
    n = 1
    while (platform_dir / date_str / f"{slug}-{n:02d}").exists():
        n += 1
    return f"{n:02d}"


def wait_ready(page, timeout_sec: float = 30.0) -> bool:
    """轮询等待页面加载完成与笔记容器出现；超时返回 False（由调用方报错）。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            info = page.evaluate(
                "() => ({ ready: document.readyState,"
                " hasDesc: !!document.querySelector('#detail-desc, .note-text, article') })")
            if info.get("ready") == "complete" and info.get("hasDesc"):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def save_flow(page, data: dict, out_root: Path, timeout_sec: int) -> dict:
    """下载媒体并落盘 note.md。"""
    import re
    date_str = c.local_date_str()
    slug = c.slugify(data.get("title", ""))
    seq = next_seq(out_root / "RedNote", date_str, slug)
    dir_name = f"{slug}-{seq}"
    dir_path = out_root / "RedNote" / date_str / dir_name
    rel_path = f"RedNote/{date_str}/{dir_name}"
    dir_path.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    img_names: list[str] = []
    n = 0
    for im in data.get("images") or []:
        n += 1
        base = f"img-{n:02d}"
        if im.get("url"):
            ext = "jpg"
            m = re.search(r"\.(jpe?g|webp|png|gif|avif)(?:\?|$)", im["url"], re.I)
            if m:
                ext = m.group(1).lower().replace("jpeg", "jpg")
            try:
                size = download(im["url"], dir_path / f"{base}.{ext}", timeout_sec)
                img_names.append(f"{base}.{ext}")
                c.log(f"图片{n}: {size / 1024:.0f}KB")
            except Exception as e:
                failures.append(f"图片{n}: {e}")
        if im.get("liveVideo"):
            try:
                size = download(im["liveVideo"], dir_path / f"{base}-live.mp4", timeout_sec)
                img_names.append(f"{base}-live.mp4")
                c.log(f"实况视频{n}: {size / 1e6:.1f}MB")
            except Exception as e:
                failures.append(f"实况照片{n}: {e}")

    video_name = ""
    if data.get("video") and data["video"].get("urls"):
        vname = f"video.{data['video']['format'] if data['video'].get('format') == 'mp4' else 'm4s'}"
        for u in data["video"]["urls"]:
            try:
                size = download(u, dir_path / vname, timeout_sec)
                video_name = vname
                c.log(f"视频: {size / 1e6:.1f}MB")
                break
            except Exception as e:
                failures.append(f"视频: {e}，尝试备用直链")
        if not video_name:
            failures.append("视频: 全部候选直链下载失败")
    elif data.get("videoDiag"):
        (dir_path / "dump-video.json").write_text(
            json.dumps(data["videoDiag"], ensure_ascii=False) + "\n"
            + (data.get("videoRawJson") or ""), encoding="utf-8")
        c.log("视频流未解析出，已落 dump-video.json")

    # 媒体区：视频优先（视频笔记不放封面图），实况视频保留
    media_lines: list[str] = []
    if video_name:
        media_lines += video_tag(video_name)
    for name in img_names:
        if video_name and not name.endswith("-live.mp4"):
            continue
        if name.endswith("-live.mp4"):
            media_lines += video_tag(name)
        else:
            media_lines.append(f"![{name.rsplit('.', 1)[0]}]({name})")

    note = build_note(data, media_lines, rel_path)
    (dir_path / "note.md").write_text(note, encoding="utf-8")

    files = img_names + ([video_name] if video_name else []) + ["note.md"]
    if failures:
        c.log("部分失败:\n  " + "\n  ".join(failures))
    return {
        "status": "ok",
        "dir": str(dir_path),
        "rel_path": rel_path,
        "title": data.get("title", ""),
        "note_type": data.get("noteType", ""),
        "files": files,
        "failures": failures,
    }


def list_pages(context) -> list[dict]:
    return [{"title": p.title(), "url": p.url}
            for p in context.pages if p.url.startswith(("http:", "https:"))]


def main() -> int:
    import re
    c.setup_utf8()
    args = parse_args(sys.argv[1:])
    out_root = Path(args.out).expanduser() if args.out else Path.cwd() / DEFAULT_OUT_NAME

    if not args.url and not args.tab and not args.list:
        c.emit_json(c.fail("bad-args",
                           "缺少 --url / --tab / --list 之一",
                           "--url 需带 xsec_token 的笔记链接；无 token 时先在浏览器打开笔记，用 --tab"))
        return 2
    if args.url and not re.search(XHS_HOST_RE, args.url, re.I):
        c.emit_json(c.fail("bad-url", f"链接不是小红书页面: {args.url}",
                           "需要 xiaohongshu.com 域名的笔记链接（带 xsec_token）"))
        return 2

    import browser_session as bs
    try:
        bs.ensure_session(args.port, bs.DEFAULT_PROFILE)
    except RuntimeError as e:
        c.emit_json(c.fail("session-error", str(e), "先 uv run browser_session.py ensure"))
        return 2

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(c.cdp_url(args.port))
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        if args.list:
            c.emit_json({"status": "ok", "pages": list_pages(context)})
            return 0

        page = None
        try:
            if args.url:
                page = context.new_page()
                page.set_default_timeout(60_000)
                c.log(f"打开笔记页：{args.url}")
                page.goto(args.url, wait_until="domcontentloaded")
                wait_ready(page, 20.0)
                time.sleep(1.0)
            else:
                pages = [pg for pg in context.pages
                         if re.search(XHS_HOST_RE, pg.url, re.I)]
                if args.tab:
                    f = args.tab.lower()
                    pages = [pg for pg in pages
                             if f in pg.url.lower() or f in pg.title().lower()]
                if len(pages) == 0:
                    c.emit_json(c.fail(
                        "no-page", "未找到小红书标签页",
                        "先在浏览器打开笔记页（uv run browser_session.py ensure 启动的窗口）；"
                        "--list 查看已开标签页"))
                    return 2
                if len(pages) > 1:
                    c.emit_json(c.fail(
                        "ambiguous", "匹配到多个标签页，请用更精确的 --tab 子串",
                        "; ".join(f"{pg.title()[:30]} | {pg.url[:60]}" for pg in pages)))
                    return 2
                page = pages[0]
                c.log(f"使用已开标签页：{page.title()[:40]}")
                page.bring_to_front()

            data = page.evaluate(EXTRACT_JS)
            if not data:
                raise RuntimeError("页面提取返回为空")
            if data.get("wrongNote"):
                raise RuntimeError(
                    f"页面状态里没有链接对应的笔记（链接指向 {data.get('wanted')}，"
                    f"页面给出 {data.get('got')}）。等页面加载完成后重试，或确认是笔记详情页")
            if data.get("blocked"):
                raise RuntimeError("页面是登录/风控页：请在测试 Chrome 里登录小红书后重试")
            if data.get("notScoped"):
                raise RuntimeError("未识别到笔记正文：请在单篇笔记详情页打开后再执行")
            c.log(f"提取成功: 「{data.get('title', '')}」 类型={data.get('noteType') or '图文'} "
                  f"正文 {len(data.get('text') or '')} 字，"
                  f"图片 {len(data.get('images') or [])}，"
                  f"视频 {'有' if data.get('video') else '无'}")
            result = save_flow(page, data, out_root, args.timeout)
            if args.url:
                page.close()
        except RuntimeError:
            if page is not None and args.url:
                try:
                    page.close()
                except Exception:
                    pass
            raise
        except Exception as e:
            c.emit_json(c.fail("clip-error", str(e),
                               "查看 stderr 日志定位；确认浏览器会话与登录态后重试"))
            return 2
    c.emit_json(result)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        c.setup_utf8()
        c.emit_json(c.fail("clip-error", str(e), "按 message 提示处理后重试"))
        sys.exit(2)
