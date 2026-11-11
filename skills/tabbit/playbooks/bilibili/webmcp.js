// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取视频信息 — read. 读取当前 Bilibili
// 视频的标题、作者、时长、字幕和可用格式。
async function bilibili_get_video_context(rawInput = {}) {
  const bilibiliAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.bilibili.com' &&
        /^\/video\/(BV[\w]+|av\d+)\/?$/i.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bilibiliAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported Bilibili page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => [].includes(key))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const win = globalThis;
  const meta = (name) =>
      document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)
          ?.content?.trim() ||
      '';
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const duration = (value) => {
    const seconds = Number(value);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  const jsonLd =
      Array
          .from(document.querySelectorAll('script[type="application/ld+json"]'))
          .flatMap((node) => {
            try {
              const parsed = JSON.parse(node.textContent || 'null');
              return Array.isArray(parsed) ? parsed : [parsed];
            } catch {
              return [];
            }
          })
          .find((entry) => entry && typeof entry === 'object');
  const publicUrl = () => 'bilibili' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  let subtitles = [];
  {
    const state = win.__INITIAL_STATE__ || {};
    const play = win.__playinfo__?.data || {};
    const video = state.videoData || {};
    const owner = video.owner || {};
    formats = [
      ...(play.durl || []).map((entry) => ({
                                 url: absolute(entry.url),
                                 mimeType: 'video/mp4',
                                 quality: entry.quality || null,
                                 muxed: true
                               })),
      ...(play.dash?.video || []).map((entry) => ({
                                        url: absolute(
                                            entry.baseUrl || entry.base_url),
                                        mimeType: entry.mimeType || 'video/mp4',
                                        quality: entry.height || null,
                                        muxed: false
                                      }))
    ];
    subtitles = (video.subtitle?.list || state.subtitle?.subtitles ||
                 []).map((entry) => ({
                           language: entry.lan || entry.lan_doc || 'unknown',
                           label: entry.lan_doc || entry.lan || '',
                           url: absolute(entry.subtitle_url || entry.url)
                         }));
    if (video.cid && (video.bvid || video.aid)) {
      try {
        const params = new URLSearchParams({cid: String(video.cid)});
        if (video.bvid)
          params.set('bvid', String(video.bvid));
        if (video.aid)
          params.set('aid', String(video.aid));
        const response = await fetch(
            `https://api.bilibili.com/x/player/wbi/v2?${params}`,
            {credentials: 'include', signal: AbortSignal.timeout(15000)});
        const payload = response.ok ? await response.json() : null;
        const tracks = payload?.data?.subtitle?.subtitles;
        if (Array.isArray(tracks) && tracks.length)
          subtitles =
              tracks.map((entry) => ({
                           language: entry.lan || entry.lan_doc || 'unknown',
                           label: entry.lan_doc || entry.lan || '',
                           url: absolute(entry.subtitle_url || entry.url)
                         }));
      } catch { /* Keep any usable first-screen subtitle tracks. */
      }
    }
    subtitles = subtitles.filter((entry) => entry.url);
    context = {
      id: video.bvid || video.aid || location.pathname.split('/')[2],
      bvid: video.bvid || null,
      aid: video.aid || null,
      title: video.title || meta('og:title') || document.title,
      author: owner.name || meta('author') || '',
      duration: duration(video.duration || jsonLd?.duration),
      canonicalUrl: publicUrl(),
      subtitles: subtitles.map(({url: _url, ...entry}) => entry),
      formats: formats.map(({url: _url, ...entry}) => entry)
    };
  }
  return {data: context};
}


// 下载视频 — download. 下载当前页面可直接取得的音视频合一格式；会写入本地文件。
async function bilibili_download_video(rawInput = {}) {
  const bilibiliAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.bilibili.com' &&
        /^\/video\/(BV[\w]+|av\d+)\/?$/i.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bilibiliAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported Bilibili page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => ['quality'].includes(key)) &&
        (!('quality' in rawInput) ||
         (typeof rawInput['quality'] === 'string' &&
          [...rawInput['quality']].length <= 32))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const win = globalThis;
  const meta = (name) =>
      document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)
          ?.content?.trim() ||
      '';
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const duration = (value) => {
    const seconds = Number(value);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  };
  const safeTitle = (value, fallback) =>
      String(value || fallback).trim().slice(0, 120);
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  const jsonLd =
      Array
          .from(document.querySelectorAll('script[type="application/ld+json"]'))
          .flatMap((node) => {
            try {
              const parsed = JSON.parse(node.textContent || 'null');
              return Array.isArray(parsed) ? parsed : [parsed];
            } catch {
              return [];
            }
          })
          .find((entry) => entry && typeof entry === 'object');
  const mediaElements = () =>
      Array.from(document.querySelectorAll('video,audio'));
  const makeUrlAsset = (url, filename, mimeType) =>
      ({url, filename, mimeType, sourceOrigin: location.origin});
  const publicUrl = () => 'bilibili' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  let subtitles = [];
  {
    const state = win.__INITIAL_STATE__ || {};
    const play = win.__playinfo__?.data || {};
    const video = state.videoData || {};
    const owner = video.owner || {};
    formats = [
      ...(play.durl || []).map((entry) => ({
                                 url: absolute(entry.url),
                                 mimeType: 'video/mp4',
                                 quality: entry.quality || null,
                                 muxed: true
                               })),
      ...(play.dash?.video || []).map((entry) => ({
                                        url: absolute(
                                            entry.baseUrl || entry.base_url),
                                        mimeType: entry.mimeType || 'video/mp4',
                                        quality: entry.height || null,
                                        muxed: false
                                      }))
    ];
    subtitles = (video.subtitle?.list || state.subtitle?.subtitles ||
                 []).map((entry) => ({
                           language: entry.lan || entry.lan_doc || 'unknown',
                           label: entry.lan_doc || entry.lan || '',
                           url: absolute(entry.subtitle_url || entry.url)
                         }));
    if (video.cid && (video.bvid || video.aid)) {
      try {
        const params = new URLSearchParams({cid: String(video.cid)});
        if (video.bvid)
          params.set('bvid', String(video.bvid));
        if (video.aid)
          params.set('aid', String(video.aid));
        const response = await fetch(
            `https://api.bilibili.com/x/player/wbi/v2?${params}`,
            {credentials: 'include', signal: AbortSignal.timeout(15000)});
        const payload = response.ok ? await response.json() : null;
        const tracks = payload?.data?.subtitle?.subtitles;
        if (Array.isArray(tracks) && tracks.length)
          subtitles =
              tracks.map((entry) => ({
                           language: entry.lan || entry.lan_doc || 'unknown',
                           label: entry.lan_doc || entry.lan || '',
                           url: absolute(entry.subtitle_url || entry.url)
                         }));
      } catch { /* Keep any usable first-screen subtitle tracks. */
      }
    }
    subtitles = subtitles.filter((entry) => entry.url);
    context = {
      id: video.bvid || video.aid || location.pathname.split('/')[2],
      bvid: video.bvid || null,
      aid: video.aid || null,
      title: video.title || meta('og:title') || document.title,
      author: owner.name || meta('author') || '',
      duration: duration(video.duration || jsonLd?.duration),
      canonicalUrl: publicUrl(),
      subtitles: subtitles.map(({url: _url, ...entry}) => entry),
      formats: formats.map(({url: _url, ...entry}) => entry)
    };
  }
  {
    if (mediaElements().some((element) => element.mediaKeys))
      return {
        data: null,
        error: {
          code: 'DRM_PROTECTED',
          message: '当前媒体受 DRM 保护，不执行下载。',
          recoverable: false
        }
      };
    const muxed = formats.find((entry) => entry.muxed && entry.url);
    if (!muxed)
      return {
        data: {tracks: formats.map(({url: _url, ...entry}) => entry)},
        error: {
          code: formats.length ? 'MUX_REQUIRED' : 'DOWNLOAD_UNAVAILABLE',
          message: formats.length ?
              '当前页面只有独立音视频轨，一期不自动合并。' :
              '当前页面没有可直接下载的媒体。',
          recoverable: false
        }
      };
    const extension = String(muxed.mimeType).includes('audio') ? 'mp3' :
        String(muxed.mimeType).includes('webm')                ? 'webm' :
                                                                 'mp4';
    return {
      data: {selected: {mimeType: muxed.mimeType, quality: muxed.quality}},
      assets: [makeUrlAsset(
          muxed.url, `${safeTitle(context.title, 'bilibili')}.${extension}`,
          muxed.mimeType)]
    };
  }
}


// 导出字幕 — export. 按语言导出当前视频已有字幕；会写入本地文件。
async function bilibili_export_subtitles(rawInput = {}) {
  const bilibiliAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.bilibili.com' &&
        /^\/video\/(BV[\w]+|av\d+)\/?$/i.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bilibiliAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported Bilibili page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'language' in rawInput &&
        Object.keys(rawInput).every(
            key => ['language', 'format'].includes(key)) &&
        (!('language' in rawInput) ||
         (typeof rawInput['language'] === 'string' &&
          [...rawInput['language']].length >= 1 &&
          [...rawInput['language']].length <= 32)) &&
        (!('format' in rawInput) ||
         (typeof rawInput['format'] === 'string' &&
          ['srt', 'vtt', 'json'].includes(rawInput['format'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const meta = (name) =>
      document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)
          ?.content?.trim() ||
      '';
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const duration = (value) => {
    const seconds = Number(value);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  };
  const safeTitle = (value, fallback) =>
      String(value || fallback).trim().slice(0, 120);
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  const jsonLd =
      Array
          .from(document.querySelectorAll('script[type="application/ld+json"]'))
          .flatMap((node) => {
            try {
              const parsed = JSON.parse(node.textContent || 'null');
              return Array.isArray(parsed) ? parsed : [parsed];
            } catch {
              return [];
            }
          })
          .find((entry) => entry && typeof entry === 'object');
  const publicUrl = () => 'bilibili' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  let subtitles = [];
  {
    const state = win.__INITIAL_STATE__ || {};
    const play = win.__playinfo__?.data || {};
    const video = state.videoData || {};
    const owner = video.owner || {};
    formats = [
      ...(play.durl || []).map((entry) => ({
                                 url: absolute(entry.url),
                                 mimeType: 'video/mp4',
                                 quality: entry.quality || null,
                                 muxed: true
                               })),
      ...(play.dash?.video || []).map((entry) => ({
                                        url: absolute(
                                            entry.baseUrl || entry.base_url),
                                        mimeType: entry.mimeType || 'video/mp4',
                                        quality: entry.height || null,
                                        muxed: false
                                      }))
    ];
    subtitles = (video.subtitle?.list || state.subtitle?.subtitles ||
                 []).map((entry) => ({
                           language: entry.lan || entry.lan_doc || 'unknown',
                           label: entry.lan_doc || entry.lan || '',
                           url: absolute(entry.subtitle_url || entry.url)
                         }));
    if (video.cid && (video.bvid || video.aid)) {
      try {
        const params = new URLSearchParams({cid: String(video.cid)});
        if (video.bvid)
          params.set('bvid', String(video.bvid));
        if (video.aid)
          params.set('aid', String(video.aid));
        const response = await fetch(
            `https://api.bilibili.com/x/player/wbi/v2?${params}`,
            {credentials: 'include', signal: AbortSignal.timeout(15000)});
        const payload = response.ok ? await response.json() : null;
        const tracks = payload?.data?.subtitle?.subtitles;
        if (Array.isArray(tracks) && tracks.length)
          subtitles =
              tracks.map((entry) => ({
                           language: entry.lan || entry.lan_doc || 'unknown',
                           label: entry.lan_doc || entry.lan || '',
                           url: absolute(entry.subtitle_url || entry.url)
                         }));
      } catch { /* Keep any usable first-screen subtitle tracks. */
      }
    }
    subtitles = subtitles.filter((entry) => entry.url);
    context = {
      id: video.bvid || video.aid || location.pathname.split('/')[2],
      bvid: video.bvid || null,
      aid: video.aid || null,
      title: video.title || meta('og:title') || document.title,
      author: owner.name || meta('author') || '',
      duration: duration(video.duration || jsonLd?.duration),
      canonicalUrl: publicUrl(),
      subtitles: subtitles.map(({url: _url, ...entry}) => entry),
      formats: formats.map(({url: _url, ...entry}) => entry)
    };
  }
  {
    const requested = String(input.language || '');
    const track = subtitles.find(
        (entry) => entry.language === requested || entry.label === requested);
    if (!track?.url)
      return {
        data: {available: subtitles.map(({url: _url, ...entry}) => entry)},
        error: {
          code: 'CONTENT_UNAVAILABLE',
          message: '当前视频没有请求的字幕轨。',
          recoverable: false
        }
      };
    const format = String(input.format || 'srt');
    const mimeType = format === 'json' ? 'application/json' :
        format === 'vtt'               ? 'text/vtt' :
                                         'application/x-subrip';
    return {
      data: {language: requested, format},
      assets: [{
        url: track.url,
        filename:
            `${safeTitle(context.title, 'bilibili')}-${requested}.${format}`,
        mimeType,
        sourceOrigin: location.origin,
        transform: {type: 'subtitle', format}
      }]
    };
  }
}


// 读取评论 — read. 分页读取当前视频评论，单次最多 200 条。
async function bilibili_extract_comments(rawInput = {}) {
  const bilibiliAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.bilibili.com' &&
        /^\/video\/(BV[\w]+|av\d+)\/?$/i.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!bilibiliAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported Bilibili page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['limit', 'cursor', 'includeReplies'].includes(key)) &&
        (!('limit' in rawInput) ||
         (Number.isInteger(rawInput['limit']) && rawInput['limit'] >= 1 &&
          rawInput['limit'] <= 200)) &&
        (!('cursor' in rawInput) ||
         (((typeof rawInput['cursor'] === 'string' &&
            [...rawInput['cursor']].length <= 512) ||
           (rawInput['cursor'] === null)))) &&
        (!('includeReplies' in rawInput) ||
         (typeof rawInput['includeReplies'] === 'boolean'))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  const rows = [];
  for (const panel of document.querySelectorAll('bili-comments')) {
    for (const thread of panel.shadowRoot?.querySelectorAll(
             'bili-comment-thread-renderer') ||
         []) {
      const root = thread.shadowRoot;
      const comment = root?.querySelector('bili-comment-renderer');
      if (comment)
        rows.push({node: comment, parent: null});
      if (input.includeReplies) {
        const replies =
            root?.querySelector('bili-comment-replies-renderer')?.shadowRoot;
        for (const node of replies?.querySelectorAll(
                 'bili-comment-reply-renderer') ||
             [])
          rows.push({node, parent: comment});
      }
    }
  }
  // Older desktop layouts keep the parent body inside a reply-item wrapper.
  for (const node of document.querySelectorAll(
           '.root-reply-container, .reply-item')) {
    if (node.matches('.reply-item') &&
        node.querySelector('.root-reply-container'))
      continue;
    if (node.parentElement?.closest('.root-reply-container') ||
        (node.matches('.reply-item') &&
         node.parentElement?.closest('.reply-item')))
      continue;
    rows.push({node, parent: null});
    if (input.includeReplies) {
      for (const reply of (node.closest('.reply-item') || node)
               .querySelectorAll('.sub-reply-item'))
        rows.push({node: reply, parent: node});
    }
  }
  const plainText = (node) => {
    const copy = node?.cloneNode(true);
    for (const image of copy?.querySelectorAll('img') || [])
      image.replaceWith(image.alt || '');
    for (const br of copy?.querySelectorAll('br') || [])
      br.replaceWith('\n');
    return copy?.textContent?.trim() || '';
  };
  const idOf = (node) => node?.data?.rpid_str || node?.dataset.rpid ||
      node?.dataset.commentId || null;
  const items =
      rows.map(({node, parent}, index) => {
            const root = node.shadowRoot || node.cloneNode(true);
            if (!node.shadowRoot) {
              for (const reply of root.querySelectorAll('.sub-reply-item'))
                reply.remove();
            }
            const user =
                root.querySelector('bili-comment-user-info')?.shadowRoot;
            const actions =
                root.querySelector('bili-comment-action-buttons-renderer')
                    ?.shadowRoot ||
                root;
            const authorNode = user?.querySelector('#user-name a') ||
                root.querySelector('.user-name, .sub-user-name');
            const contentNode = root.querySelector('bili-rich-text')
                                    ?.shadowRoot?.querySelector('#contents') ||
                root.querySelector('.reply-content');
            const timeNode =
                actions.querySelector('#pubdate, .reply-time, .sub-reply-time');
            const likeText =
                actions
                    .querySelector('#like #count, .reply-like, .sub-reply-like')
                    ?.textContent?.trim();
            return {
              id: String(idOf(node) || `bilibili-${index + 1}`),
              ...(parent ? {
                parentId: String(
                    idOf(parent) ||
                    `bilibili-${
                        rows.findIndex(row => row.node === parent) + 1}`)
              } :
                           {}),
              author: {
                name: authorNode?.textContent?.trim() || '未知用户',
                profileUrl: absolute(authorNode?.href) || null
              },
              content: plainText(contentNode).slice(0, 5000),
              publishedAt:
                  timeNode?.dateTime || timeNode?.textContent?.trim() || null,
              likeCount: likeText === undefined ?
                  null :
                  Number((likeText.match(/[\d,.]+/)?.[0] || '0')
                             .replace(/,/g, '')),
              replyCount:
                  Number.isInteger(node.data?.rcount) ? node.data.rcount : null,
              sourceUrl:
                  `${location.origin}${location.pathname}${location.search}`
            };
          })
          .filter(item => item.content);
  const unique = [...new Map(items.map(item => [item.id, item])).values()];
  const cursor =
      typeof input.cursor === 'string' && /^\d+$/.test(input.cursor) ?
      Number(input.cursor) :
      0;
  const selected = unique.slice(cursor, cursor + (input.limit ?? 20));
  const nextOffset = cursor + selected.length;
  const hasMore = nextOffset < unique.length;
  return {
    data: {
      items: selected,
      nextCursor: hasMore ? String(nextOffset) : null,
      hasMore,
      truncated: hasMore
    },
    warnings: [
      '仅返回当前页面已加载的评论；hasMore 仅表示当前已加载列表中还有条目，不代表站点全部评论已加载。'
    ]
  };
}
