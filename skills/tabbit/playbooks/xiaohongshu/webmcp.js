// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取笔记信息 — read. 读取当前笔记标题、作者、正文摘要和图片数量。
async function xiaohongshu_get_note_context(rawInput = {}) {
  const xiaohongshuAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.xiaohongshu.com' &&
        /^\/(explore|discovery\/item)\/[\w-]+\/?$/.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!xiaohongshuAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 小红书 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => [].includes(key))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
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
  const imageSources = () => {
    const nodes = Array.from(document.querySelectorAll(
        '.swiper-slide:not(.swiper-slide-duplicate) img, [class*="carousel"] img, [class*="gallery"] img, [class*="note"] img'));
    const values = nodes.map((node) => absolute(node.currentSrc || node.src))
                       .filter((value) => /^https:\/\//.test(value));
    return [...new Set(values)].filter(
        (value) => !/avatar|logo|icon/i.test(value));
  };
  const publicUrl = () => 'xiaohongshu' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  {
    const images = imageSources();
    context = {
      id: location.pathname.split('/').pop(),
      title: meta('og:title') ||
          text(['#detail-title', '.title', '[class*="title"]']) ||
          document.title,
      author: text([
        '.author-wrapper .name', '.user-name',
        '[class*="author"] [class*="name"]'
      ]),
      summary: (meta('description') || text([
                  '#detail-desc', '.desc', '[class*="note-content"]'
                ])).slice(0, 3000),
      imageCount: images.length,
      canonicalUrl: publicUrl()
    };
    formats = images.map(
        (url, index) =>
            ({url, mimeType: 'image/jpeg', quality: index + 1, muxed: true}));
  }
  return {data: context};
}


// 读取或下载图片 — download. 按原顺序返回图片；可选下载，下载时会写入本地文件。
async function xiaohongshu_get_post_images(rawInput = {}) {
  const xiaohongshuAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.xiaohongshu.com' &&
        /^\/(explore|discovery\/item)\/[\w-]+\/?$/.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!xiaohongshuAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 小红书 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['download', 'limit'].includes(key)) &&
        (!('download' in rawInput) ||
         (typeof rawInput['download'] === 'boolean')) &&
        (!('limit' in rawInput) ||
         (Number.isInteger(rawInput['limit']) && rawInput['limit'] >= 1 &&
          rawInput['limit'] <= 20))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
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
  const imageSources = () => {
    const nodes = Array.from(document.querySelectorAll(
        '.swiper-slide:not(.swiper-slide-duplicate) img, [class*="carousel"] img, [class*="gallery"] img, [class*="note"] img'));
    const values = nodes.map((node) => absolute(node.currentSrc || node.src))
                       .filter((value) => /^https:\/\//.test(value));
    return [...new Set(values)].filter(
        (value) => !/avatar|logo|icon/i.test(value));
  };
  const makeUrlAsset = (url, filename, mimeType) =>
      ({url, filename, mimeType, sourceOrigin: location.origin});
  const publicUrl = () => 'xiaohongshu' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  {
    const images = imageSources();
    context = {
      id: location.pathname.split('/').pop(),
      title: meta('og:title') ||
          text(['#detail-title', '.title', '[class*="title"]']) ||
          document.title,
      author: text([
        '.author-wrapper .name', '.user-name',
        '[class*="author"] [class*="name"]'
      ]),
      summary: (meta('description') || text([
                  '#detail-desc', '.desc', '[class*="note-content"]'
                ])).slice(0, 3000),
      imageCount: images.length,
      canonicalUrl: publicUrl()
    };
    formats = images.map(
        (url, index) =>
            ({url, mimeType: 'image/jpeg', quality: index + 1, muxed: true}));
  }
  {
    const limit = Math.min(20, Math.max(1, Number(input.limit ?? 20)));
    const images = formats.slice(0, limit).map(
        (entry, index) =>
            ({index: index + 1, url: entry.url, mimeType: entry.mimeType}));
    const assets = input.download === true ?
        images.map(
            (entry) => makeUrlAsset(
                entry.url,
                `${safeTitle(context.title, 'xiaohongshu')}-${entry.index}.jpg`,
                entry.mimeType)) :
        undefined;
    return {
      data: {
        items: images,
        count: images.length,
        truncated: formats.length > limit
      },
      ...(assets ? {assets} : {})
    };
  }
}


// 读取评论 — read. 分页读取当前笔记可见评论，单次最多 200 条。
async function xiaohongshu_extract_comments(rawInput = {}) {
  const xiaohongshuAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        url.hostname === 'www.xiaohongshu.com' &&
        /^\/(explore|discovery\/item)\/[\w-]+\/?$/.test(url.pathname)
  };
  const routeUrl = new URL(location.href);
  if (!xiaohongshuAdapter.matches(routeUrl))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 小红书 page for this recipe.');
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
  const collectComments = () => {
    const limit = Math.min(200, Math.max(1, Number(input.limit ?? 20)));
    const selectors = {
      bilibili:
          '.reply-item, .root-reply-container, bili-comment-thread-renderer',
      youtube: 'ytd-comment-thread-renderer, ytd-comment-view-model',
      xiaoyuzhou: '[class*="comment-item"], [data-testid*="comment"]',
      xiaohongshu: '.comment-item, [class*="comment-item"]'
    };
    const allNodes = Array.from(document.querySelectorAll(
        selectors['xiaohongshu'] || '[data-comment-id]'));
    const cursor =
        typeof input.cursor === 'string' && /^\d+$/.test(input.cursor) ?
        Number(input.cursor) :
        0;
    const nodes = allNodes.slice(cursor, cursor + limit);
    const items =
        nodes
            .map((node, index) => {
              const authorNode = node.querySelector(
                  '#author-text, .user-name, .name, [class*="author"] a, a[href*="/user/"]');
              const contentNode = node.querySelector(
                  '#content-text, .reply-content, .content, [class*="comment-content"]');
              const timeNode =
                  node.querySelector('time, .reply-time, [class*="time"]');
              const likeText =
                  node.querySelector(
                          '#vote-count-middle, .like, [class*="like-count"]')
                      ?.textContent ||
                  '0';
              const id = node.dataset.commentId || node.id ||
                  `${'xiaohongshu'}-${index + 1}`;
              return {
                id,
                author: {
                  name: authorNode?.textContent?.trim() || '未知用户',
                  profileUrl: absolute(authorNode?.href || '') || null
                },
                content: (contentNode?.textContent || node.textContent || '')
                             .trim()
                             .slice(0, 5000),
                publishedAt:
                    timeNode?.dateTime || timeNode?.textContent?.trim() || null,
                likeCount: Number((likeText.match(/[\d,.]+/)?.[0] || '0')
                                      .replace(/,/g, '')) ||
                    0,
                replyCount: 0,
                sourceUrl:
                    `${location.origin}${location.pathname}${location.search}`
              };
            })
            .filter((item) => item.content);
    const nextOffset = cursor + nodes.length;
    const hasMore = nextOffset < allNodes.length;
    return {
      items,
      nextCursor: hasMore ? String(nextOffset) : null,
      hasMore,
      truncated: hasMore
    };
  };
  const imageSources = () => {
    const nodes = Array.from(document.querySelectorAll(
        '.swiper-slide:not(.swiper-slide-duplicate) img, [class*="carousel"] img, [class*="gallery"] img, [class*="note"] img'));
    const values = nodes.map((node) => absolute(node.currentSrc || node.src))
                       .filter((value) => /^https:\/\//.test(value));
    return [...new Set(values)].filter(
        (value) => !/avatar|logo|icon/i.test(value));
  };
  const publicUrl = () => 'xiaohongshu' === 'youtube' ?
      `${location.origin}/watch?v=${
          encodeURIComponent(
              new URL(location.href).searchParams.get('v') || '')}` :
      `${location.origin}${location.pathname}`;
  let context = {};
  let formats = [];
  {
    const images = imageSources();
    context = {
      id: location.pathname.split('/').pop(),
      title: meta('og:title') ||
          text(['#detail-title', '.title', '[class*="title"]']) ||
          document.title,
      author: text([
        '.author-wrapper .name', '.user-name',
        '[class*="author"] [class*="name"]'
      ]),
      summary: (meta('description') || text([
                  '#detail-desc', '.desc', '[class*="note-content"]'
                ])).slice(0, 3000),
      imageCount: images.length,
      canonicalUrl: publicUrl()
    };
    formats = images.map(
        (url, index) =>
            ({url, mimeType: 'image/jpeg', quality: index + 1, muxed: true}));
  }
  return {
    data: collectComments(),
    warnings: ['仅返回当前页面已加载且可见的评论。']
  };
}
