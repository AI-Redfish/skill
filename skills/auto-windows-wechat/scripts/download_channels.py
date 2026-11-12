#!/usr/bin/env python3
"""Download a user-authorized video-channel share through a logged-in Tabbit tab.

Usage: uv run --no-project download_channels.py SHARE_URL --tab OBSERVED_ID -o VIDEO.mp4
Dependencies: Python 3.10+ standard library, installed Tabbit CLI, Yuanbao login.
Only URLs in the documented share format are accepted. No cookies, tokens, or
media URLs are exported. Existing output files are never overwritten. Downloads
are bounded to 64 MiB by default (configurable up to 256 MiB). stdout: one JSON
result; exit 0 success, 1 operational error, 2 invalid arguments. This script does
not control the desktop, send WeChat messages, bypass login, or transcribe.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
import uuid


class DownloadError(Exception):
    """Safe-to-display operational error."""


def validate_share_url(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != 'https' or url.netloc != 'weixin.qq.com'
            or not re.fullmatch(r'/sph/[A-Za-z0-9_-]+/?', url.path)
            or url.fragment or url.query):
        raise ValueError('仅接受 https://weixin.qq.com/sph/<视频标识>；请提供原分享链接')
    return value


def find_cli(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser()
    elif os.name == 'nt':
        path = Path(os.environ.get('LOCALAPPDATA', '')) / 'Tabbit/LocalAgent/bin/tabbit-cli.exe'
    else:
        path = Path.home() / '.local/bin/tabbit-cli'
    if not path.is_file():
        raise DownloadError('找不到 Tabbit 稳定入口；请安装 Tabbit 或用 --cli 指定入口')
    return path


def parse_cli_json(text: str) -> dict:
    try:
        value = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        value = None
        for line in reversed(text.splitlines()):
            try:
                candidate = json.loads(line)
                if isinstance(candidate, dict):
                    value = candidate
                    break
            except ValueError:
                continue
    if not isinstance(value, dict):
        raise DownloadError('Tabbit 返回无有效 JSON；请检查 diagnose，不要盲目重跑下载')
    return value


def cli_call(cli: Path, arguments: list[str], code: str | None = None) -> dict:
    try:
        proc = subprocess.run([str(cli), *arguments], input=code, encoding='utf-8',
                              errors='replace', capture_output=True, timeout=195)
    except (OSError, subprocess.TimeoutExpired):
        raise DownloadError('Tabbit 调用中断；请检查任务 receipt 后再重试') from None
    if not proc.stdout.strip():
        return {}
    # Never include raw CLI errors in exceptions: they could contain signed URLs.
    return parse_cli_json(proc.stdout)


def materialize(result: dict, cli: Path, task: str) -> dict:
    resource = result.get('resourceId')
    if not resource:
        value = result.get('value')
        if not isinstance(value, dict):
            raise DownloadError('Tabbit 缺少结果；请按 request-id 检查 receipt')
        return value
    offset, chunks = 0, []
    total = 0
    while True:
        part = cli_call(cli, ['resource', '--task', task, '--resource', resource,
                             '--offset', str(offset), '--max-bytes', '65536'])
        # Some CLI versions wrap resource reads in result.
        if 'data' not in part and isinstance(part.get('result'), dict):
            part = part['result']
        data = part.get('data')
        if not isinstance(data, str):
            raise DownloadError('Tabbit resource 缺少 data；结果未完整读取')
        total += len(data)
        if total > 360 * 1024 * 1024:
            raise DownloadError('资源超过下载上限；请改用分段下载流程')
        chunks.append(data)
        if part.get('eof') is True:
            break
        nxt = part.get('nextOffset')
        if not isinstance(nxt, int) or nxt <= offset:
            raise DownloadError('资源分页未推进；停止读取，避免重复下载')
        offset = nxt
    try:
        value = json.loads(''.join(chunks))
    except ValueError:
        raise DownloadError('资源 JSON 不完整；请检查分页结果') from None
    if not isinstance(value, dict):
        raise DownloadError('资源不是预期对象')
    return value


def read_request(initial: dict, cli: Path, task: str, request: str) -> dict:
    result = initial
    for _ in range(4):
        status = result.get('status')
        if status == 'succeeded':
            return materialize(result.get('result', {}), cli, task)
        if status in ('failed', 'interrupted') or result.get('ok') is False:
            raise DownloadError('后台请求失败；请检查登录态与站点状态，不要导出 Cookie')
        if status not in (None, 'queued', 'running'):
            raise DownloadError('Tabbit 状态不可识别；请检查 receipt')
        result = cli_call(cli, ['receipt', '--task', task, '--request-id', request,
                                '--wait-ms', '60000'])
    raise DownloadError('任务仍未完成；保留任务供检查，勿换 request-id 盲目重跑')


def make_program(url: str, max_bytes: int) -> str:
    # JSON encoding prevents URL content from becoming executable source.
    return 'const shareUrl = ' + json.dumps(url) + ';\nconst maxBytes = ' + str(max_bytes) + ';\n' + r'''
try {
  if (new URL(page.url()).origin !== 'https://yuanbao.tencent.com')
    return {ok:false, error:'选中的不是元宝标签页；请重新发现 tabId'};
  const parsed = await page.fetch('/api/weixin/get_parse_result', {
    method:'POST', headers:{'Content-Type':'application/json'}, as:'json',
    body:JSON.stringify({type:'video_channel_url', url:shareUrl, scene:1}),
    maxBytes:262144, timeoutMs:30000
  });
  if (parsed.status === 429) return {ok:false, error:'站点限流；停止自动重试，等待站点允许后再试'};
  if (parsed.status === 401 || parsed.status === 403) {
    reportIssue('AUTHENTICATION_REQUIRED');
    return {ok:false, error:'元宝未登录或登录失效；请用户在元宝页面完成登录后重试'};
  }
  if (!parsed.ok || parsed.json?.code !== 0)
    return {ok:false, error:'元宝授权解析失败；可能为失效链接、访问限制或接口变化'};
  const playback = new URL(parsed.json.data?.playable_url);
  if (playback.origin !== 'https://channels.weixin.qq.com')
    return {ok:false, error:'授权播放页域名异常；停止请求'};
  const token = playback.searchParams.get('token');
  const eid = playback.searchParams.get('eid');
  if (!token || !eid)
    return {ok:false, error:'授权参数缺失；播放页不是 MP4，请重新授权解析'};
  const feed = await page.request.post(
    'https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info', {
      headers:{'Content-Type':'application/json', Origin:playback.origin, Referer:playback.href},
      data:{baseReq:{generalToken:token}, exportId:eid}, timeout:30000
    });
  let body;
  try {
    if (feed.status() === 429) return {ok:false, error:'站点限流；停止重试，遵守 Retry-After'};
    if (!feed.ok()) return {ok:false, error:'视频详情请求失败；请重新授权或确认访问权限'};
    body = await feed.json();
  } finally { await feed.dispose(); }
  if (body.errCode !== 0 || !body.data?.feedInfo?.videoUrl)
    return {ok:false, error:'视频详情缺少媒体地址；不绕过访问控制'};
  const media = new URL(body.data.feedInfo.videoUrl);
  if (media.protocol !== 'https:' || media.username || media.password
      || !['qq.com','qpic.cn'].some(d => media.hostname === d || media.hostname.endsWith('.'+d)))
    return {ok:false, error:'媒体域名或协议超出允许范围；停止下载，请人工核对'};
  // Probe with a small Range first; do not pull an unbounded response.
  const probe = await page.request.get(media.href, {headers:{Range:'bytes=0-31'}, timeout:30000});
  let total;
  try {
    const headers = probe.headers();
    const match = /^bytes 0-\d+\/(\d+)$/.exec(headers['content-range'] || '');
    total = match ? Number(match[1]) : Number(headers['content-length']);
    if (![200,206].includes(probe.status()) || !Number.isSafeInteger(total) || total < 16 || total > maxBytes)
      return {ok:false, error:'无法确认媒体大小或超出上限；停止自动下载'};
  } finally { await probe.dispose(); }
  // Range support was verified before this bounded full request.
  const response = await page.request.get(media.href, {
    headers:{Range:`bytes=0-${total-1}`}, timeout:90000
  });
  try {
    if (![200,206].includes(response.status()))
      return {ok:false, error:'媒体下载失败；签名可能过期，请重新授权'};
    const bytes = await response.body();
    if (bytes.length !== total || bytes.subarray(4,8).toString('ascii') !== 'ftyp')
      return {ok:false, error:'媒体不完整或不是 MP4；不将网页或加密内容交付为视频'};
    return {ok:true, bytes:bytes.length, base64:bytes.toString('base64')};
  } finally { await response.dispose(); }
} catch (_) {
  return {ok:false, error:'后台请求异常；请检查登录态、网络或接口变化，再决定是否录屏'};
}
'''


def save_media(value: dict, output: Path) -> dict:
    if value.get('ok') is not True:
        raise DownloadError(value.get('error', '后台未成功；不生成空视频'))
    # Authentication and media URLs remain only in the runtime, never in files.
    try:
        data = base64.b64decode(value['base64'], validate=True)
    except (ValueError, KeyError, TypeError):
        raise DownloadError('媒体编码损坏；不写入交付文件') from None
    if len(data) < 16 or data[4:8] != b'ftyp' or len(data) != value.get('bytes'):
        raise DownloadError('媒体字节数或 MP4 头不匹配；不写入交付文件')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open('xb') as stream:
            stream.write(data)
    except FileExistsError:
        raise DownloadError('输出已存在，未覆盖；请指定新名称或先确认覆盖方式') from None
    return {'ok': True, 'video': str(output), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), 'source': 'authorized-background',
            'validation': 'length-and-mp4-header; full-decode-required'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', type=validate_share_url)
    parser.add_argument('--tab', type=int, required=True, help='从 Tabbit create 清单观察到的元宝 tabId')
    parser.add_argument('-o', '--output', type=Path, required=True)
    parser.add_argument('--cli', help='已安装 Tabbit 的稳定 CLI 路径')
    parser.add_argument('--max-mib', type=int, default=64, choices=range(1,257), metavar='1..256')
    args = parser.parse_args()
    task = 'channels-' + uuid.uuid4().hex[:12]
    cleanup = False
    try:
        if args.output.exists():
            raise DownloadError('输出已存在，未覆盖；请使用新文件名')
        cli = find_cli(args.cli)
        created = cli_call(cli, ['create', '--task', task])
        if created.get('ok') is False or not created:
            raise DownloadError('无法建立 Tabbit 任务；请检查稳定入口与浏览器状态')
        cleanup = True
        request = 'download-' + uuid.uuid4().hex[:12]
        cleanup = False  # Preserve uncertain pending requests for receipt inspection.
        try:
            initial = cli_call(cli, ['nodejs', '--task', task, '--tab', str(args.tab),
                                    '--request-id', request, '--timeout-ms', '180000'],
                               make_program(args.url, args.max_mib * 1024 * 1024))
            value = read_request(initial, cli, task, request)
        except DownloadError as exc:
            raise DownloadError(f'{exc}；request-id={request}') from None
        cleanup = True
        result = save_media(value, args.output)
        print(json.dumps({'output':result}, ensure_ascii=False))
        return 0
    except (DownloadError, OSError) as exc:
        message = str(exc) if isinstance(exc, DownloadError) else '本地文件读写失败；请检查输出目录权限和磁盘空间'
        print(json.dumps({'output':{'ok':False, 'error':message, 'task':task}}, ensure_ascii=False))
        return 1
    finally:
        if cleanup:
            try:
                cli_call(cli, ['finish', '--task', task])  # Retains the acquired login tab.
            except DownloadError:
                print('[channels] finish 未确认；请检查任务状态，保留登录标签页', file=sys.stderr)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
