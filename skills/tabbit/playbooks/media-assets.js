// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. Nodejs support recipe for the four
// media sites. See WEBMCP-SOURCE.md. Paste this file alongside the selected
// page callback. Explicitly call: const sourceOrigin = new
// URL(page.url()).origin; const result = await
// page.evaluate(bilibili_download_video, {}); if (result.error) throw new
// Error(result.error.message); console.log(await saveMediaAssets(page,
// result.assets, {site: 'bilibili', sourceOrigin})); Requires the existing
// nodejs artifactPath helper. Files are never overwritten.
async function saveMediaAssets(page, assets, {site, sourceOrigin}) {
  const hosts = {
    bilibili: ['bilivideo.com', 'hdslb.com', 'bilibili.com'],
    youtube: ['googlevideo.com', 'youtube.com', 'ytimg.com'],
    xiaoyuzhou: ['xiaoyuzhoufm.com', 'xyzcdn.net', 'ximalaya.com'],
    xiaohongshu: ['xhscdn.com', 'xiaohongshu.com'],
  }[site];
  if (!hosts || !Array.isArray(assets) || assets.length > 20) {
    throw new Error(
        'VALIDATION_ERROR: Expected at most 20 assets from a supported media site.');
  }
  const {writeFile} = await import('node:fs/promises');
  const files = [];
  for (const asset of assets) {
    if (new URL(page.url()).origin !== sourceOrigin ||
        asset.sourceOrigin !== sourceOrigin) {
      throw new Error(
          'STALE_PAGE_CONTEXT: Asset and page origins must match the inspected source.');
    }
    // artifactPath accepts at most 128 characters. Keep extension when
    // truncating.
    const cleaned = sanitizeFilename(asset.filename);
    const extension = cleaned.match(/\.[^.]+$/)?.[0] || '';
    const filename = cleaned.length <= 128 ?
        cleaned :
        cleaned.slice(0, 128 - extension.length) + extension;
    const path = artifactPath(filename);
    let text = asset.text;
    let url;
    if (text === undefined || asset.transform) {
      url = new URL(asset.url);
      if (url.protocol !== 'https:' || url.username || url.password ||
          !hosts.some(
              host =>
                  url.hostname === host || url.hostname.endsWith(`.${host}`))) {
        throw new Error(
            'PERMISSION_DENIED: Asset URL is outside the source CDN allowlist.');
      }
    }
    if (asset.transform) {
      if (asset.transform.type !== 'subtitle' ||
          !['srt', 'vtt', 'json'].includes(asset.transform.format)) {
        throw new Error('VALIDATION_ERROR: Unsupported subtitle transform.');
      }
      const response = await page.fetch(url.href, {
        as: 'text',
        credentials: 'include',
        maxBytes: 5 * 1024 * 1024,
        timeoutMs: 20000,
      });
      if (!response.ok)
        throw new Error(
            `CONTENT_UNAVAILABLE: Subtitle HTTP ${response.status}`);
      if (!response.text?.trim())
        throw new Error(
            'CONTENT_UNAVAILABLE: Empty subtitle response; a platform token may be required.');
      text = convertSubtitle(response.text, asset.transform.format);
    }
    if (text !== undefined) {
      if (typeof text !== 'string' ||
          Buffer.byteLength(text) > 5 * 1024 * 1024) {
        throw new Error('RESULT_TOO_LARGE: Export exceeds 5 MiB.');
      }
      await writeFile(path, text, {encoding: 'utf8', flag: 'wx'});
      files.push(
          {path, bytes: Buffer.byteLength(text), mimeType: asset.mimeType});
    } else {
      // page.fetch's existing transport has an 8 MiB ceiling. Larger media must
      // use the site's native download UI; do not report a URL as a saved file.
      const response = await page.fetch(url.href, {
        as: 'file',
        savePath: path,
        credentials: 'include',
        timeoutMs: 20000,
      });
      if (!response.ok)
        throw new Error(`CONTENT_UNAVAILABLE: Media HTTP ${response.status}`);
      files.push({
        path: response.path,
        bytes: response.bytes,
        mimeType: asset.mimeType
      });
    }
  }
  return files;
}
function sanitizeFilename(value) {
  const clean = value.normalize('NFKC')
                    .replace(/[\p{Cc}/\\:*?"<>|]/gu, '-')
                    .replace(/\.{2,}/g, '.')
                    .replace(/^[.\s-]+|[.\s]+$/g, '')
                    .trim();
  const safe = clean.slice(0, 180) || 'download';
  return /\.(exe|dmg|pkg|app|js|html?)$/i.test(safe) ? `${safe}.txt` : safe;
}
const decodeEntities = (value) =>
    value.replace(/<br\s*\/?>/gi, '\n')
        .replace(/<[^>]+>/g, '')
        .replace(
            /&#(\d+);/g, (_match, code) => String.fromCodePoint(Number(code)))
        .replace(
            /&#x([\da-f]+);/gi,
            (_match, code) => String.fromCodePoint(Number.parseInt(code, 16)))
        .replace(/&quot;/g, '"')
        .replace(/&apos;/g, '\'')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
        .trim();
const stamp = (seconds, vtt = false) => {
  const ms = Math.max(0, Math.round(seconds * 1000));
  const h = Math.floor(ms / 3600000).toString().padStart(2, '0');
  const m = Math.floor((ms % 3600000) / 60000).toString().padStart(2, '0');
  const s = Math.floor((ms % 60000) / 1000).toString().padStart(2, '0');
  const milli = (ms % 1000).toString().padStart(3, '0');
  return `${h}:${m}:${s}${vtt ? '.' : ','}${milli}`;
};
function jsonCues(parsed) {
  const rows = parsed?.body || parsed?.events || parsed;
  if (!Array.isArray(rows))
    return [];
  return rows.flatMap((row) => {
    const start = Number(
        row.from !== undefined         ? row.from :
            row.tStartMs !== undefined ? row.tStartMs / 1000 :
                                         row.start ?? 0);
    const end = Number(
        row.to !== undefined ? row.to :
            row.tStartMs !== undefined && row.dDurationMs !== undefined ?
                               (row.tStartMs + row.dDurationMs) / 1000 :
                               row.end ?? start + 2);
    const text =
        String(
            row.content ?? row.segs?.map((segment) => segment.utf8).join('') ??
            row.text ?? '')
            .trim();
    return text && Number.isFinite(start) && Number.isFinite(end) ?
        [{start, end: Math.max(start, end), text}] :
        [];
  });
}
function xmlCues(raw) {
  const cues = [];
  for (const match of raw.matchAll(/<(text|p)\b([^>]*)>([\s\S]*?)<\/\1>/gi)) {
    const attrs = match[2] || '';
    const read = (name) =>
        attrs.match(new RegExp(`\\b${name}=["']([^"']+)["']`, 'i'))?.[1];
    const usesMilliseconds = read('t') !== undefined;
    const start =
        Number(read('start') ?? read('t') ?? 0) / (usesMilliseconds ? 1000 : 1);
    const length =
        Number(read('dur') ?? read('d') ?? (usesMilliseconds ? 2000 : 2)) /
        (read('d') !== undefined ? 1000 : 1);
    const text = decodeEntities(match[3] || '');
    if (text && Number.isFinite(start) && Number.isFinite(length))
      cues.push({start, end: start + length, text});
  }
  return cues;
}
function convertSubtitle(raw, format) {
  if (!raw.trim())
    throw new Error('字幕响应为空。');
  if (format === 'json') {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return JSON.stringify({raw}, null, 2);
    }
  }
  if (format === 'vtt' && /^WEBVTT(?:\r?\n|$)/.test(raw))
    return raw;
  let cues = [];
  try {
    cues = jsonCues(JSON.parse(raw));
  } catch {
    cues = xmlCues(raw);
  }
  if (!cues.length)
    throw new Error('字幕格式无法解析。');
  if (format === 'vtt')
    return `WEBVTT\n\n${
        cues.map(
                (cue) => `${stamp(cue.start, true)} --> ${
                    stamp(cue.end, true)}\n${cue.text}`)
            .join('\n\n')}\n`;
  return `${
      cues.map(
              (cue, index) => `${index + 1}\n${stamp(cue.start)} --> ${
                  stamp(cue.end)}\n${cue.text}`)
          .join('\n\n')}\n`;
}
