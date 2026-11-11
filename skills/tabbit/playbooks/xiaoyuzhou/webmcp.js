// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取单集信息 — read. 读取当前播客节目、单集、主播、时长和音频信息。
async function xiaoyuzhou_get_episode_context(rawInput = {}) {
  const xiaoyuzhouAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.xiaoyuzhoufm.com' &&
        /^\/episode\/[\w-]+\/?$/.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!xiaoyuzhouAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 小宇宙 page for this recipe.');
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
  const mediaElements = () =>
      Array.from(document.querySelectorAll('video,audio'));
  const mediaSources = () => {
    const values = mediaElements().flatMap(
        (element) =>
            [element.currentSrc, element.src,
             ...Array.from(element.querySelectorAll('source'))
                 .map((source) => source.src)]);
    return [...new Set(
        values.map(absolute).filter((value) => value.startsWith('https://')))];
  };
  const publicUrl = () => 'xiaoyuzhou' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  {
    const next = win.__NEXT_DATA__?.props?.pageProps || {};
    const episode = next.episode || next.data?.episode || jsonLd || {};
    const audioUrl = absolute(
        episode.enclosure?.url || episode.audioUrl || episode.audio?.url ||
        mediaSources()[0]);
    formats = audioUrl ? [{
      url: audioUrl,
      mimeType: episode.enclosure?.type || 'audio/mpeg',
      quality: null,
      muxed: true
    }] :
                         [];
    context = {
      id: episode.eid || episode.id || location.pathname.split('/').pop(),
      title: episode.title || meta('og:title') || document.title,
      podcast: episode.podcast?.title || episode.partOfSeries?.name ||
          text(['[class*="podcast-title"]']),
      hosts: (episode.podcast?.podcasters ||
              []).map?.((host) => host.nickname || host.name) ||
          [],
      duration: duration(episode.duration || mediaElements()[0]?.duration),
      canonicalUrl: publicUrl(),
      audio: formats.map(({url: _url, ...entry}) => entry)
    };
  }
  return {data: context};
}


// 下载音频 — download. 下载当前页面可播放的音频；会写入本地文件。
async function xiaoyuzhou_download_audio(rawInput = {}) {
  const xiaoyuzhouAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.xiaoyuzhoufm.com' &&
        /^\/episode\/[\w-]+\/?$/.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!xiaoyuzhouAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 小宇宙 page for this recipe.');
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
  const mediaSources = () => {
    const values = mediaElements().flatMap(
        (element) =>
            [element.currentSrc, element.src,
             ...Array.from(element.querySelectorAll('source'))
                 .map((source) => source.src)]);
    return [...new Set(
        values.map(absolute).filter((value) => value.startsWith('https://')))];
  };
  const makeUrlAsset = (url, filename, mimeType) =>
      ({url, filename, mimeType, sourceOrigin: location.origin});
  const publicUrl = () => 'xiaoyuzhou' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  {
    const next = win.__NEXT_DATA__?.props?.pageProps || {};
    const episode = next.episode || next.data?.episode || jsonLd || {};
    const audioUrl = absolute(
        episode.enclosure?.url || episode.audioUrl || episode.audio?.url ||
        mediaSources()[0]);
    formats = audioUrl ? [{
      url: audioUrl,
      mimeType: episode.enclosure?.type || 'audio/mpeg',
      quality: null,
      muxed: true
    }] :
                         [];
    context = {
      id: episode.eid || episode.id || location.pathname.split('/').pop(),
      title: episode.title || meta('og:title') || document.title,
      podcast: episode.podcast?.title || episode.partOfSeries?.name ||
          text(['[class*="podcast-title"]']),
      hosts: (episode.podcast?.podcasters ||
              []).map?.((host) => host.nickname || host.name) ||
          [],
      duration: duration(episode.duration || mediaElements()[0]?.duration),
      canonicalUrl: publicUrl(),
      audio: formats.map(({url: _url, ...entry}) => entry)
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
          muxed.url, `${safeTitle(context.title, 'xiaoyuzhou')}.${extension}`,
          muxed.mimeType)]
    };
  }
}


// 读取评论 — read. 分页读取当前单集评论，单次最多 200 条。
async function xiaoyuzhou_extract_comments(rawInput = {}) {
  const xiaoyuzhouAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.xiaoyuzhoufm.com' &&
        /^\/episode\/[\w-]+\/?$/.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!xiaoyuzhouAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 小宇宙 page for this recipe.');
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
  for (const node of document.querySelectorAll('.comment')) {
    if (node.parentElement?.closest('.comment'))
      continue;
    rows.push({node, parent: null});
    if (input.includeReplies) {
      for (const reply of node.querySelectorAll('.replies > .reply'))
        rows.push({node: reply, parent: node});
    }
  }
  const commentId = (node) => {
    const link = node.querySelector('.info .like[href]');
    return node.dataset.commentId ||
        (link ? new URL(link.href, location.href)
                    .searchParams.get('locateCommentId') :
                null);
  };
  const items =
      rows.map(({node, parent}, index) => {
            const authorNode =
                node.querySelector(parent ? '.reply-author' : '.info .name');
            const authorName = authorNode?.textContent?.trim() || '未知用户';
            const contentNode =
                parent ? node : node.querySelector('.text-wrap > .text');
            const content = contentNode?.cloneNode(true);
            content?.querySelector('.reply-author')?.remove();
            for (const br of content?.querySelectorAll('br') || [])
              br.replaceWith('\n');
            const parentId = parent &&
                (commentId(parent) ||
                 `xiaoyuzhou-${
                     rows.findIndex(row => row.node === parent) + 1}`);
            const timeNode = !parent && node.querySelector('.info .pub-time');
            const likeText = !parent &&
                node.querySelector('.info .like .count')?.textContent?.trim();
            return {
              id: String(
                  commentId(node) ||
                  (parent ?
                       `${parentId}-reply-${
                               [...parent.querySelectorAll('.replies > .reply')]
                                   .indexOf(node) +
                           1}` :
                       `xiaoyuzhou-${index + 1}`)),
              ...(parent ? {parentId: String(parentId)} : {}),
              author: {
                name: parent ? authorName.replace(/[:：]$/, '') : authorName,
                profileUrl: absolute(authorNode?.href) || null
              },
              content: content?.textContent?.trim().slice(0, 5000) || '',
              publishedAt: timeNode?.textContent?.trim() || null,
              likeCount: typeof likeText !== 'string' ?
                  null :
                  Number((likeText.match(/[\d,.]+/)?.[0] || '0')
                             .replace(/,/g, '')),
              replyCount: null,
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
