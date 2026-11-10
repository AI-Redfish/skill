#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.45"]
# ///
"""bili_clip.py — B 站单篇视频沉淀（CDP 附着真实 Chrome）。

用途：打开指定视频页，读取 __INITIAL_STATE__.videoData 与页面内 playurl API
（带登录 cookie 拿最高画质），下载封面与 DASH 音视频分离流，ffmpeg 合并为
video.mp4，输出 note.md + 媒体。
边界：只抓取用户指定的单篇链接；不滚动、不批量、不自动浏览。

用法：
  uv run bili_clip.py --url <视频链接> [--out DIR] [--page N] [--port 9341] [--timeout SEC]
  uv run bili_clip.py --merge <目录>          # 对目录内已有分离流补合并
  uv run bili_clip.py --list [--port 9341]    # 列出浏览器已开标签页

输出：JSON 到 stdout（status/dir/files/quality/failures），日志到 stderr。
退出码：0 成功；2 失败。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

BILI_REFERER = "https://www.bilibili.com/"
BILI_URL_RE = re.compile(r"bilibili\.com", re.I)
DEFAULT_OUT_NAME = "clips"
DOWNLOAD_TIMEOUT_SEC = 600

# 注入页面执行的提取函数。页面上下文 fetch 自带登录 cookie 与 Referer，
# 可拿到账号可见的最高画质。逻辑与 AgentPhoto bili 扩展 PAGE_EXTRACT_BILI 同构。
EXTRACT_JS = r"""
async (wantPage) => {
  const st = window.__INITIAL_STATE__ || {};
  const vd = st.videoData || {};
  const bvid = vd.bvid || (location.pathname.match(/\/video\/(BV[0-9A-Za-z]+)/i) || [])[1] || '';
  if (!bvid) return { notFound: true, url: location.href };
  const QN = { 127: '8K 超高清', 126: '杜比视界', 125: 'HDR 真彩', 120: '4K 超清',
    116: '1080P 60帧', 112: '1080P 高码率', 80: '1080P 高清', 74: '720P 60帧',
    64: '720P 高清', 32: '480P 清晰', 16: '360P 流畅' };
  const pages = (vd.pages || []).map((p) => ({ page: p.page, cid: p.cid, part: (p.part || '').trim() }));
  let target = pages.find((p) => p.page === wantPage) || pages[0] || { cid: vd.cid || 0, page: 1, part: '' };
  const cid = target.cid || vd.cid || 0;
  const out = {
    bvid, cid,
    title: (vd.title || '').replace(/<[^>]+>/g, '').trim(),
    author: (vd.owner && vd.owner.name) || '',
    text: (vd.desc || '').trim(),
    cover: vd.pic || '',
    duration: vd.duration || 0,
    pages,
    page: target.page || 1,
    pagePart: target.part || '',
    tags: [], video: null, url: location.href,
  };
  try {
    const r = await fetch(
      `https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&qn=0&fnval=16&fourk=1`,
      { credentials: 'include' });
    const j = await r.json();
    const dash = (j.data && j.data.dash) || null;
    if (dash) {
      const pick = (arr, prefer) => {
        if (!arr || !arr.length) return null;
        const maxId = Math.max(...arr.map((v) => v.id || 0));
        const top = arr.filter((v) => (v.id || 0) === maxId);
        return top.find((v) => prefer.test(v.codecs || '')) || top[0];
      };
      const bv = pick(dash.video, /avc/i);
      const ba = pick(dash.audio, /mp4a/i) || (dash.audio && dash.audio[0]) || null;
      const u = (s) => (s && (s.baseUrl || s.base_url)) || '';
      const us = (s) => (s && (s.backupUrl || s.backup_url)) || [];
      if (bv) {
        out.video = {
          videoUrl: u(bv), backupUrls: us(bv),
          audioUrl: ba ? u(ba) : '', audioBackupUrls: ba ? us(ba) : [],
          quality: QN[bv.id] || `${bv.id}`,
          width: bv.width || 0, height: bv.height || 0,
          codecs: bv.codecs || '', audioId: ba ? (ba.id || 0) : 0,
        };
      }
    }
  } catch (e) { /* playurl 失败时仍保存元数据与封面 */ }
  try {
    const r = await fetch(`https://api.bilibili.com/x/web-interface/view/detail?bvid=${bvid}`,
      { credentials: 'include' });
    const j = await r.json();
    out.tags = (((j.data || {}).Tags) || []).map((t) => t && t.tag_name)
      .filter(Boolean).slice(0, 20);
  } catch (e) { /* tags 可缺省 */ }
  return out;
}
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="B 站单篇视频沉淀")
    ap.add_argument("--url", help="视频页链接（https://www.bilibili.com/video/BV...）")
    ap.add_argument("--out", default=None, help="输出根目录（默认 <cwd>/clips）")
    ap.add_argument("--page", type=int, default=1, help="分P 页码（默认 1）")
    ap.add_argument("--port", type=int, default=9341, help="CDP 调试端口（默认 9341）")
    ap.add_argument("--timeout", type=int, default=DOWNLOAD_TIMEOUT_SEC,
                    help="单个文件下载超时秒数（默认 600）")
    ap.add_argument("--merge", default=None, help="只对目录内 video.m4s/audio.m4s 执行合并")
    ap.add_argument("--list", action="store_true", help="列出浏览器已开标签页后退出")
    return ap.parse_args(argv)


def download(url: str, dest: Path, timeout_sec: int) -> int:
    """流式下载；bilivideo CDN 校验 Referer，缺失即 403。返回字节数。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": c.BROWSER_UA,
        "Referer": BILI_REFERER,
    })
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest.stat().st_size


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def merge_dir(dir_path: Path) -> dict:
    """合并目录内 video.m4s + audio.m4s → video.mp4（流复制），成功后删分离流。"""
    video = dir_path / "video.m4s"
    audio = dir_path / "audio.m4s"
    out = dir_path / "video.mp4"
    has_v, has_a = video.exists(), audio.exists()
    if not has_v and not has_a:
        if out.exists():
            return {"merged": False, "reason": "already-merged"}
        return {"merged": False, "reason": "no-streams"}
    args = ["ffmpeg", "-y"]
    if has_v:
        args += ["-i", str(video)]
    if has_a:
        args += ["-i", str(audio)]
    args += ["-c", "copy", "-movflags", "+faststart", str(out)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("ffmpeg 合并失败: " + "\n".join((r.stderr or "").splitlines()[-5:]))
    try:
        if has_v:
            video.unlink()
        if has_a:
            audio.unlink()
    except OSError:
        pass
    return {"merged": True, "out": str(out)}


def yml_str(v) -> str:
    """front matter 字符串统一 JSON 双引号写法（YAML 兼容）。"""
    return json.dumps("" if v is None else str(v), ensure_ascii=False)


def build_note(data: dict, cover_name: str, video_line: str, pages_lines: list[str],
               rel_path: str) -> str:
    v = data.get("video") or {}
    fm = [
        "---",
        "platform: Bilibili",
        "type: video",
        f"title: {yml_str(data.get('title', ''))}",
        f"author: {yml_str(data.get('author', ''))}",
        f"url: {yml_str(data.get('url', ''))}",
        f"captured_at: {yml_str(c.now_stamp())}",
        f"path: {yml_str(rel_path)}",
        f"tags: {json.dumps(data.get('tags') or [], ensure_ascii=False)}",
        f"video_quality: {yml_str(v.get('quality', ''))}",
        f"width: {v.get('width', 0)}",
        f"height: {v.get('height', 0)}",
        f"duration: {data.get('duration', 0)}",
        f"page: {data.get('page', 1)}",
        "---",
        "",
    ]
    body = [
        "# 正文",
        "",
        data.get("text") or "（无简介）",
        "",
        "",
        "# 封面",
        "",
        f"![cover]({cover_name})" if cover_name else "（无封面）",
        "",
        "",
    ]
    if pages_lines:
        body += ["# 分P列表", "", *pages_lines, "", ""]
    body += ["# 视频", "", video_line, ""]
    return "\n".join(fm + body)


def next_seq(platform_dir: Path, date_str: str, slug: str) -> str:
    """同一天同标题序号递增（-01 → -02），文件系统实查。"""
    n = 1
    while (platform_dir / date_str / f"{slug}-{n:02d}").exists():
        n += 1
    return f"{n:02d}"


def wait_ready(page, timeout_sec: float = 30.0) -> bool:
    """轮询等待 __INITIAL_STATE__.videoData 就绪。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            ok = page.evaluate(
                "() => { const v = (window.__INITIAL_STATE__||{}).videoData||{};"
                " return !!(v.bvid && v.cid); }")
            if ok:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def clip_flow(page, url: str, out_root: Path, args) -> dict:
    page.set_default_timeout(60_000)
    c.log(f"打开视频页：{url}")
    page.goto(url, wait_until="domcontentloaded")
    if not wait_ready(page):
        raise RuntimeError(
            "__INITIAL_STATE__.videoData 未就绪（问题）；"
            "链接不是视频播放页或页面未加载完（原因）；"
            "确认链接为 https://www.bilibili.com/video/BV... 后重试（行动）")
    data = page.evaluate(EXTRACT_JS, args.page)
    if not data:
        raise RuntimeError("页面提取返回为空")
    if data.get("notFound"):
        raise RuntimeError("未识别到视频数据：请在视频播放页（/video/BV...）使用")
    page.close()

    date_str = c.local_date_str()
    slug = c.slugify(data.get("title", ""))
    seq = next_seq(out_root / "Bilibili", date_str, slug)
    dir_name = f"{slug}-{seq}"
    dir_path = out_root / "Bilibili" / date_str / dir_name
    rel_path = f"Bilibili/{date_str}/{dir_name}"
    dir_path.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    files: list[str] = []

    # 1. 封面
    cover_name = ""
    if data.get("cover"):
        try:
            cover_name = "cover.jpg"
            download(data["cover"], dir_path / cover_name, args.timeout)
            files.append(cover_name)
        except Exception as e:
            cover_name = ""
            failures.append(f"封面: {e}")
            (dir_path / "cover.jpg").unlink(missing_ok=True)

    # 2. DASH 分离流（直链有时效，提取后立即下载；失败逐个换备用直链）
    v = data.get("video") or {}
    if v.get("videoUrl"):
        for u in [v["videoUrl"], *v.get("backupUrls", [])]:
            try:
                size = download(u, dir_path / "video.m4s", args.timeout)
                files.append("video.m4s")
                c.log(f"视频流下载完成：{size / 1e6:.1f}MB")
                break
            except Exception as e:
                failures.append(f"视频流: {e}")
    if v.get("audioUrl"):
        for u in [v["audioUrl"], *v.get("audioBackupUrls", [])]:
            try:
                download(u, dir_path / "audio.m4s", args.timeout)
                files.append("audio.m4s")
                break
            except Exception as e:
                failures.append(f"音频流: {e}")

    if (dir_path / "video.m4s").exists() or (dir_path / "audio.m4s").exists():
        if has_ffmpeg():
            c.log("等待文件落盘稳定后合并…")
            time.sleep(2)
            merge_dir(dir_path)
            files = [f for f in files if f not in ("video.m4s", "audio.m4s")]
            files.append("video.mp4")
        else:
            failures.append("未检测到 ffmpeg，分离流已保留；安装后用 --merge 补合并")
            c.log("提示: winget install Gyan.FFmpeg")

    qn = v.get("quality") or "画质未知"
    video_line = (
        f"[video.mp4](video.mp4)（{qn} {v.get('width', 0)}x{v.get('height', 0)}）"
        if "video.mp4" in files
        else (f"[video.m4s](video.m4s) + [audio.m4s](audio.m4s)（分离流，未合并；原始: {v.get('videoUrl', '')}）"
              if "video.m4s" in files else "（未取得视频流：接口返回为空，请确认已登录且视频可播放）")
    )
    pages_lines = [
        f"- P{p['page']} {p['part']}" + ("（当前）" if p["page"] == data.get("page") else "")
        for p in data.get("pages", []) if len(data.get("pages", [])) > 1
    ]
    note = build_note(data, cover_name, video_line, pages_lines, rel_path)
    (dir_path / "note.md").write_text(note, encoding="utf-8")
    files.append("note.md")

    if failures:
        c.log("部分失败:\n  " + "\n  ".join(failures))
    return {
        "status": "ok",
        "dir": str(dir_path),
        "rel_path": rel_path,
        "title": data.get("title", ""),
        "bvid": data.get("bvid", ""),
        "quality": qn,
        "files": files,
        "failures": failures,
    }


def list_pages(context) -> list[dict]:
    return [{"title": p.title(), "url": p.url}
            for p in context.pages if p.url.startswith(("http:", "https:"))]


def main() -> int:
    c.setup_utf8()
    args = parse_args(sys.argv[1:])
    out_root = Path(args.out).expanduser() if args.out else Path.cwd() / DEFAULT_OUT_NAME

    if args.merge:
        if not has_ffmpeg():
            c.emit_json(c.fail("no-ffmpeg", "未检测到 ffmpeg",
                               "winget install Gyan.FFmpeg 后重试"))
            return 2
        r = merge_dir(Path(args.merge).expanduser())
        c.emit_json({"status": "ok", "merge": r})
        return 0

    if not args.url and not args.list:
        c.emit_json(c.fail("bad-args", "缺少 --url（或 --merge / --list）",
                           "uv run bili_clip.py --url <视频链接>"))
        return 2
    if args.url and not BILI_URL_RE.search(args.url):
        c.emit_json(c.fail("bad-url", f"链接不是 B 站页面: {args.url}",
                           "需要 https://www.bilibili.com/video/BV... 形式的链接"))
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
        page = context.new_page()
        try:
            result = clip_flow(page, args.url, out_root, args)
        except Exception as e:
            c.emit_json(c.fail("clip-error", str(e),
                               "查看 stderr 日志定位；确认浏览器会话与登录态后重试"))
            return 2
    c.emit_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
