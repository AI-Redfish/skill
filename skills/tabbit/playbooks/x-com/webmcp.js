// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取主页信息流 — read.
// 滚动并读取当前主页所选时间线中已观察到的帖子，保留引用内容、媒体、链接和互动数。
async function x_get_home_feed(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_get_home_feed'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['maxPosts', 'maxScrolls'].includes(key)) &&
        (!('maxPosts' in rawInput) ||
         (Number.isInteger(rawInput['maxPosts']) && rawInput['maxPosts'] >= 1 &&
          rawInput['maxPosts'] <= 200)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 50))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        if (time.closest('div[role="link"]'))
          continue;
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = statusInfo(article);
      const postTexts =
          Array.from(article.querySelectorAll('[data-testid="tweetText"]'));
      const rootText =
          postTexts.find((node) => !node.closest('div[role="link"]'));
      const avatar = Array
                         .from(article.querySelectorAll(
                             '[data-testid^="UserAvatar-Container-"]'))
                         .find((node) => !node.closest('div[role="link"]'));
      const userName =
          Array.from(article.querySelectorAll('[data-testid="User-Name"]'))
              .find((node) => !node.closest('div[role="link"]'));
      const displayLines =
          clean(userName?.innerText || userName?.textContent)
              .split('\n')
              .filter((line) => line && !line.startsWith('@') && line !== '·');
      const quotedPosts =
          postTexts.filter((node) => node.closest('div[role="link"]'))
              .map((node) => {
                const quote = node.closest('div[role="link"]');
                const handle =
                    quote
                        .querySelector('[data-testid^="UserAvatar-Container-"]')
                        ?.dataset.testid?.replace(/^UserAvatar-Container-/, '');
                return {
                  author: {handle: handle || null},
                  content: clean(node.innerText || node.textContent)
                };
              });
      const media = [
        ...Array
            .from(article.querySelectorAll(
                'img[src*="pbs.twimg.com/media"], img[src*="video_thumb"]'))
            .map((node) => ({
                   type: 'image',
                   url: node.currentSrc || node.src,
                   alt: clean(node.alt) || null
                 })),
        ...Array.from(article.querySelectorAll('video'))
            .map((node) => ({
                   type: 'video',
                   url: node.currentSrc || node.src || null,
                   poster: node.poster || null
                 }))
      ];
      const links =
          Array.from(article.querySelectorAll('a[href]'))
              .map((node) => absolute(node.href))
              .filter(
                  (url) => url &&
                      !/\/analytics(?:\?|$)|\/photo\/\d+(?:\?|$)/.test(url));
      const action = (name) => {
        const node = article.querySelector(
            `[data-testid="${name}"], [data-testid="un${name}"]`);
        return node ? {
          label: clean(node.getAttribute('aria-label')),
          text: clean(node.innerText || node.textContent),
          active: node.getAttribute('data-testid') === `un${name}`
        } :
                      null;
      };
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          handle: info.handle ||
              avatar?.dataset.testid?.replace(/^UserAvatar-Container-/, '') ||
              null,
          name: displayLines[0] || null
        },
        publishedAt: info.publishedAt,
        content: clean(rootText?.innerText || rootText?.textContent),
        quotedPosts,
        media,
        links: [...new Set(links)],
        metrics: {
          replies: action('reply'),
          reposts: action('retweet'),
          likes: action('like'),
          bookmarks: action('bookmark')
        },
        pinned: clean(article.innerText || article.textContent)
                    .startsWith('已置顶') ||
            clean(article.innerText || article.textContent)
                .toLowerCase()
                .startsWith('pinned'),
        rawText: clean(article.innerText || article.textContent).slice(0, 20000)
      };
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const expandReplyControls = async () => {
      const controls =
          Array.from(document.querySelectorAll('button, [role="button"]'))
              .filter((node) => {
                const label = clean(`${node.getAttribute('aria-label') || ''} ${
                    node.innerText || node.textContent}`);
                return /(显示(更多)?回复|查看更多回复|Show( more)? replies)/i
                           .test(label) &&
                    node.getClientRects().length > 0;
              })
              .slice(0, 20);
      controls.forEach((node) => node.click());
      if (controls.length)
        await pause(350);
      return controls.length;
    };
    const collectTimeline = async (
        limit, maxScrolls, predicate = () => true, expandReplies = false) => {
      const originalY = window.scrollY;
      const collected = new Map();
      let idle = 0;
      let scrolls = 0;
      const collect = () => {
        const before = collected.size;
        for (const article of articleNodes()) {
          const post = postFromArticle(article);
          if (post.id && predicate(post) && !collected.has(post.id))
            collected.set(post.id, post);
          if (collected.size >= limit)
            break;
        }
        return collected.size - before;
      };
      if (expandReplies)
        await expandReplyControls();
      collect();
      while (collected.size < limit && scrolls < maxScrolls && idle < 3) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(640, window.innerHeight * 0.82), behavior: 'auto'});
        await pause(550);
        if (expandReplies)
          await expandReplyControls();
        const added = collect();
        scrolls += 1;
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, limit);
      const truncated =
          collected.size >= limit || (scrolls >= maxScrolls && idle < 3);
      if (scrolls > 0) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      return {items, count: items.length, scrolls, truncated};
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const requireHome = () => {
      if (location.pathname !== '/home')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在 X 主页可用。');
    };
    {
      requireHome();
      await waitFor(
          () => articleNodes()[0] || null, 'X 主页信息流尚未加载。', 15000);
      const maxPosts =
          Math.min(200, Math.max(1, Number(input.maxPosts ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const data = await collectTimeline(maxPosts, maxScrolls);
      return {
        data: {
          timeline:
              clean(
                  document.querySelector('[role="tab"][aria-selected="true"]')
                      ?.textContent) ||
              null,
          ...data
        },
        warnings: data.truncated ?
            ['X 信息流按需加载；结果达到调用上限，truncated=true。'] :
            []
      };
    }
  }
}


// 读取帖子完整对话 — read.
// 在主页或帖子详情页读取目标帖、可见上下文、回复和每条帖子内嵌的引用内容。
async function x_get_post_thread(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_get_post_thread'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'maxPosts', 'maxScrolls'].includes(
                key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^\\d{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+')
              .test(rawInput['postUrl']))) &&
        (!('maxPosts' in rawInput) ||
         (Number.isInteger(rawInput['maxPosts']) && rawInput['maxPosts'] >= 1 &&
          rawInput['maxPosts'] <= 200)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 50))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const requestedStatusId = () => {
      const explicit = clean(input.postId);
      if (explicit)
        return explicit;
      const url = clean(input.postUrl);
      if (url) {
        try {
          const parsed = new URL(url);
          if (parsed.protocol !== 'https:' || parsed.hostname !== 'x.com')
            return '';
          return statusMatch(parsed.pathname)?.[2] || '';
        } catch {
          return '';
        }
      }
      return location.pathname.match(/^\/[A-Za-z0-9_]{1,15}\/status\/(\d+)/)
                 ?.[1] ||
          '';
    };
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        if (time.closest('div[role="link"]'))
          continue;
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = statusInfo(article);
      const postTexts =
          Array.from(article.querySelectorAll('[data-testid="tweetText"]'));
      const rootText =
          postTexts.find((node) => !node.closest('div[role="link"]'));
      const avatar = Array
                         .from(article.querySelectorAll(
                             '[data-testid^="UserAvatar-Container-"]'))
                         .find((node) => !node.closest('div[role="link"]'));
      const userName =
          Array.from(article.querySelectorAll('[data-testid="User-Name"]'))
              .find((node) => !node.closest('div[role="link"]'));
      const displayLines =
          clean(userName?.innerText || userName?.textContent)
              .split('\n')
              .filter((line) => line && !line.startsWith('@') && line !== '·');
      const quotedPosts =
          postTexts.filter((node) => node.closest('div[role="link"]'))
              .map((node) => {
                const quote = node.closest('div[role="link"]');
                const handle =
                    quote
                        .querySelector('[data-testid^="UserAvatar-Container-"]')
                        ?.dataset.testid?.replace(/^UserAvatar-Container-/, '');
                return {
                  author: {handle: handle || null},
                  content: clean(node.innerText || node.textContent)
                };
              });
      const media = [
        ...Array
            .from(article.querySelectorAll(
                'img[src*="pbs.twimg.com/media"], img[src*="video_thumb"]'))
            .map((node) => ({
                   type: 'image',
                   url: node.currentSrc || node.src,
                   alt: clean(node.alt) || null
                 })),
        ...Array.from(article.querySelectorAll('video'))
            .map((node) => ({
                   type: 'video',
                   url: node.currentSrc || node.src || null,
                   poster: node.poster || null
                 }))
      ];
      const links =
          Array.from(article.querySelectorAll('a[href]'))
              .map((node) => absolute(node.href))
              .filter(
                  (url) => url &&
                      !/\/analytics(?:\?|$)|\/photo\/\d+(?:\?|$)/.test(url));
      const action = (name) => {
        const node = article.querySelector(
            `[data-testid="${name}"], [data-testid="un${name}"]`);
        return node ? {
          label: clean(node.getAttribute('aria-label')),
          text: clean(node.innerText || node.textContent),
          active: node.getAttribute('data-testid') === `un${name}`
        } :
                      null;
      };
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          handle: info.handle ||
              avatar?.dataset.testid?.replace(/^UserAvatar-Container-/, '') ||
              null,
          name: displayLines[0] || null
        },
        publishedAt: info.publishedAt,
        content: clean(rootText?.innerText || rootText?.textContent),
        quotedPosts,
        media,
        links: [...new Set(links)],
        metrics: {
          replies: action('reply'),
          reposts: action('retweet'),
          likes: action('like'),
          bookmarks: action('bookmark')
        },
        pinned: clean(article.innerText || article.textContent)
                    .startsWith('已置顶') ||
            clean(article.innerText || article.textContent)
                .toLowerCase()
                .startsWith('pinned'),
        rawText: clean(article.innerText || article.textContent).slice(0, 20000)
      };
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const expandReplyControls = async () => {
      const controls =
          Array.from(document.querySelectorAll('button, [role="button"]'))
              .filter((node) => {
                const label = clean(`${node.getAttribute('aria-label') || ''} ${
                    node.innerText || node.textContent}`);
                return /(显示(更多)?回复|查看更多回复|Show( more)? replies)/i
                           .test(label) &&
                    node.getClientRects().length > 0;
              })
              .slice(0, 20);
      controls.forEach((node) => node.click());
      if (controls.length)
        await pause(350);
      return controls.length;
    };
    const collectTimeline = async (
        limit, maxScrolls, predicate = () => true, expandReplies = false) => {
      const originalY = window.scrollY;
      const collected = new Map();
      let idle = 0;
      let scrolls = 0;
      const collect = () => {
        const before = collected.size;
        for (const article of articleNodes()) {
          const post = postFromArticle(article);
          if (post.id && predicate(post) && !collected.has(post.id))
            collected.set(post.id, post);
          if (collected.size >= limit)
            break;
        }
        return collected.size - before;
      };
      if (expandReplies)
        await expandReplyControls();
      collect();
      while (collected.size < limit && scrolls < maxScrolls && idle < 3) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(640, window.innerHeight * 0.82), behavior: 'auto'});
        await pause(550);
        if (expandReplies)
          await expandReplyControls();
        const added = collect();
        scrolls += 1;
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, limit);
      const truncated =
          collected.size >= limit || (scrolls >= maxScrolls && idle < 3);
      if (scrolls > 0) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      return {items, count: items.length, scrolls, truncated};
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    {
      const rootId = requestedStatusId();
      if (!rootId)
        throw new Error(
            'VALIDATION_ERROR: 无法确定目标帖子；在主页请传 postId 或完整 postUrl。');
      if (!location.pathname.match(/^\/[A-Za-z0-9_]{1,15}\/status\/\d+/))
        throw new Error('UNSUPPORTED_ROUTE: 读取回复需要目标帖详情页。');
      await waitFor(
          () => articleNodes()[0] || null, 'X 帖子详情尚未加载。', 15000);
      const maxPosts =
          Math.min(200, Math.max(1, Number(input.maxPosts ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const data =
          await collectTimeline(maxPosts, maxScrolls, () => true, true);
      const rootIndex = data.items.findIndex((post) => post.id === rootId);
      if (rootIndex < 0)
        throw new Error('CONTENT_UNAVAILABLE: 详情页中找不到目标帖子。');
      const posts = data.items.map((post, index) => ({
                                     ...post,
                                     relation: index < rootIndex ? 'context' :
                                         index === rootIndex     ? 'root' :
                                                                   'reply'
                                   }));
      return {
        data: {
          rootPostId: rootId,
          rootIndex,
          posts,
          count: data.count,
          scrolls: data.scrolls,
          truncated: data.truncated
        },
        warnings: data.truncated ?
            ['X 回复流按需加载；结果达到调用上限，truncated=true。'] :
            []
      };
    }
  }
}


// 读取博主最新 6 帖 — read. 读取当前博主主页最新发布的 6
// 个非置顶帖子；不把旧置顶帖计入最新列表。
async function x_get_profile_latest_posts(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_get_profile_latest_posts'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => [].includes(key))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        if (time.closest('div[role="link"]'))
          continue;
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = statusInfo(article);
      const postTexts =
          Array.from(article.querySelectorAll('[data-testid="tweetText"]'));
      const rootText =
          postTexts.find((node) => !node.closest('div[role="link"]'));
      const avatar = Array
                         .from(article.querySelectorAll(
                             '[data-testid^="UserAvatar-Container-"]'))
                         .find((node) => !node.closest('div[role="link"]'));
      const userName =
          Array.from(article.querySelectorAll('[data-testid="User-Name"]'))
              .find((node) => !node.closest('div[role="link"]'));
      const displayLines =
          clean(userName?.innerText || userName?.textContent)
              .split('\n')
              .filter((line) => line && !line.startsWith('@') && line !== '·');
      const quotedPosts =
          postTexts.filter((node) => node.closest('div[role="link"]'))
              .map((node) => {
                const quote = node.closest('div[role="link"]');
                const handle =
                    quote
                        .querySelector('[data-testid^="UserAvatar-Container-"]')
                        ?.dataset.testid?.replace(/^UserAvatar-Container-/, '');
                return {
                  author: {handle: handle || null},
                  content: clean(node.innerText || node.textContent)
                };
              });
      const media = [
        ...Array
            .from(article.querySelectorAll(
                'img[src*="pbs.twimg.com/media"], img[src*="video_thumb"]'))
            .map((node) => ({
                   type: 'image',
                   url: node.currentSrc || node.src,
                   alt: clean(node.alt) || null
                 })),
        ...Array.from(article.querySelectorAll('video'))
            .map((node) => ({
                   type: 'video',
                   url: node.currentSrc || node.src || null,
                   poster: node.poster || null
                 }))
      ];
      const links =
          Array.from(article.querySelectorAll('a[href]'))
              .map((node) => absolute(node.href))
              .filter(
                  (url) => url &&
                      !/\/analytics(?:\?|$)|\/photo\/\d+(?:\?|$)/.test(url));
      const action = (name) => {
        const node = article.querySelector(
            `[data-testid="${name}"], [data-testid="un${name}"]`);
        return node ? {
          label: clean(node.getAttribute('aria-label')),
          text: clean(node.innerText || node.textContent),
          active: node.getAttribute('data-testid') === `un${name}`
        } :
                      null;
      };
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          handle: info.handle ||
              avatar?.dataset.testid?.replace(/^UserAvatar-Container-/, '') ||
              null,
          name: displayLines[0] || null
        },
        publishedAt: info.publishedAt,
        content: clean(rootText?.innerText || rootText?.textContent),
        quotedPosts,
        media,
        links: [...new Set(links)],
        metrics: {
          replies: action('reply'),
          reposts: action('retweet'),
          likes: action('like'),
          bookmarks: action('bookmark')
        },
        pinned: clean(article.innerText || article.textContent)
                    .startsWith('已置顶') ||
            clean(article.innerText || article.textContent)
                .toLowerCase()
                .startsWith('pinned'),
        rawText: clean(article.innerText || article.textContent).slice(0, 20000)
      };
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const expandReplyControls = async () => {
      const controls =
          Array.from(document.querySelectorAll('button, [role="button"]'))
              .filter((node) => {
                const label = clean(`${node.getAttribute('aria-label') || ''} ${
                    node.innerText || node.textContent}`);
                return /(显示(更多)?回复|查看更多回复|Show( more)? replies)/i
                           .test(label) &&
                    node.getClientRects().length > 0;
              })
              .slice(0, 20);
      controls.forEach((node) => node.click());
      if (controls.length)
        await pause(350);
      return controls.length;
    };
    const collectTimeline = async (
        limit, maxScrolls, predicate = () => true, expandReplies = false) => {
      const originalY = window.scrollY;
      const collected = new Map();
      let idle = 0;
      let scrolls = 0;
      const collect = () => {
        const before = collected.size;
        for (const article of articleNodes()) {
          const post = postFromArticle(article);
          if (post.id && predicate(post) && !collected.has(post.id))
            collected.set(post.id, post);
          if (collected.size >= limit)
            break;
        }
        return collected.size - before;
      };
      if (expandReplies)
        await expandReplyControls();
      collect();
      while (collected.size < limit && scrolls < maxScrolls && idle < 3) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(640, window.innerHeight * 0.82), behavior: 'auto'});
        await pause(550);
        if (expandReplies)
          await expandReplyControls();
        const added = collect();
        scrolls += 1;
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, limit);
      const truncated =
          collected.size >= limit || (scrolls >= maxScrolls && idle < 3);
      if (scrolls > 0) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      return {items, count: items.length, scrolls, truncated};
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    {
      const handle =
          location.pathname.match(/^\/([A-Za-z0-9_]{1,15})\/?$/)?.[1];
      if (!handle)
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在 X 博主主页可用。');
      await waitFor(
          () => articleNodes()[0] || null, 'X 博主主页帖子尚未加载。', 15000);
      const data = await collectTimeline(
          6, 18,
          (post) =>
              post.author.handle?.toLowerCase() === handle.toLowerCase() &&
              !post.pinned);
      return {
        data: {
          handle,
          posts: data.items,
          count: data.count,
          complete: data.items.length === 6,
          truncated: data.items.length < 6 && data.truncated
        },
        warnings: data.items.length < 6 ?
            ['当前页面只观察到少于 6 个符合条件的非置顶帖子。'] :
            []
      };
    }
  }
}


// 发布单个帖子 — write. 在 X 主页发布单个帖子；必须传 confirm=true。
async function x_publish_post(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_publish_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'text' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(key => ['text', 'confirm'].includes(key)) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 25000)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const composer = () => visible(document.querySelectorAll(
        '[data-testid^="tweetTextarea_"][role="textbox"], [data-testid^="tweetTextarea_"][contenteditable="true"]'));
    const setEditable = async (element, value) => {
      element.focus();
      if (element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement) {
        const prototype = element instanceof HTMLTextAreaElement ?
            HTMLTextAreaElement.prototype :
            HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (!setter)
          throw new Error('SITE_CHANGED: X 表单控件不支持标准 value setter。');
        setter.call(element, value);
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
        element.dispatchEvent(new Event('change', {bubbles: true}));
        await pause(80);
        if (element.value !== value)
          throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
        return;
      }
      const selection = getSelection();
      selection?.selectAllChildren(element);
      let inserted = false;
      try {
        inserted = typeof document.execCommand === 'function' &&
            document.execCommand('insertText', false, value);
      } catch {
        inserted = false;
      }
      if (!inserted ||
          clean(element.innerText || element.textContent) !== clean(value)) {
        element.textContent = '';
        element.dispatchEvent(new InputEvent(
            'beforeinput',
            {bubbles: true, inputType: 'insertText', data: value}));
        element.textContent = value;
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
      }
      await pause(80);
      if (clean(element.innerText || element.textContent) !== clean(value))
        throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const clickPublish =
        async (testIds = ['tweetButtonInline', 'tweetButton']) => {
      const button = await waitFor(
          () => visible(testIds
                            .flatMap(
                                (id) => Array.from(document.querySelectorAll(
                                    `button[data-testid="${id}"]`)))
                            .filter((node) => !node.disabled)),
          '找不到可用的发布按钮。');
      button.click();
      await pause(800);
    };
    const requireHome = () => {
      if (location.pathname !== '/home')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在 X 主页可用。');
    };
    const requireConfirmed = () => {
      if (input.confirm !== true)
        throw new Error(
            'VALIDATION_ERROR: 该 X 外部写操作必须传 confirm=true。');
    };
    {
      requireConfirmed();
      requireHome();
      const editor = await waitFor(composer, 'X 主页发帖编辑器未加载。');
      await setEditable(editor, clean(input.text));
      await clickPublish();
      return {data: {published: true, kind: 'post', text: clean(input.text)}};
    }
  }
}


// 发布 Thread — write. 在 X 主页按顺序发布 2–25 条组成的 Thread；必须传
// confirm=true。
async function x_publish_thread(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_publish_thread'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'posts' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['posts', 'confirm'].includes(key)) &&
        (!('posts' in rawInput) ||
         (Array.isArray(rawInput['posts']) && rawInput['posts'].length >= 2 &&
          rawInput['posts'].length <= 25 &&
          rawInput['posts'].every(
              item => typeof item === 'string' && [...item].length >= 1 &&
                  [...item].length <= 25000))) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const composer = () => visible(document.querySelectorAll(
        '[data-testid^="tweetTextarea_"][role="textbox"], [data-testid^="tweetTextarea_"][contenteditable="true"]'));
    const setEditable = async (element, value) => {
      element.focus();
      if (element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement) {
        const prototype = element instanceof HTMLTextAreaElement ?
            HTMLTextAreaElement.prototype :
            HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (!setter)
          throw new Error('SITE_CHANGED: X 表单控件不支持标准 value setter。');
        setter.call(element, value);
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
        element.dispatchEvent(new Event('change', {bubbles: true}));
        await pause(80);
        if (element.value !== value)
          throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
        return;
      }
      const selection = getSelection();
      selection?.selectAllChildren(element);
      let inserted = false;
      try {
        inserted = typeof document.execCommand === 'function' &&
            document.execCommand('insertText', false, value);
      } catch {
        inserted = false;
      }
      if (!inserted ||
          clean(element.innerText || element.textContent) !== clean(value)) {
        element.textContent = '';
        element.dispatchEvent(new InputEvent(
            'beforeinput',
            {bubbles: true, inputType: 'insertText', data: value}));
        element.textContent = value;
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
      }
      await pause(80);
      if (clean(element.innerText || element.textContent) !== clean(value))
        throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const clickPublish =
        async (testIds = ['tweetButtonInline', 'tweetButton']) => {
      const button = await waitFor(
          () => visible(testIds
                            .flatMap(
                                (id) => Array.from(document.querySelectorAll(
                                    `button[data-testid="${id}"]`)))
                            .filter((node) => !node.disabled)),
          '找不到可用的发布按钮。');
      button.click();
      await pause(800);
    };
    const requireHome = () => {
      if (location.pathname !== '/home')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在 X 主页可用。');
    };
    const requireConfirmed = () => {
      if (input.confirm !== true)
        throw new Error(
            'VALIDATION_ERROR: 该 X 外部写操作必须传 confirm=true。');
    };
    {
      requireConfirmed();
      requireHome();
      const posts = input.posts.map(clean);
      for (let index = 0; index < posts.length; index += 1) {
        const editors =
            Array
                .from(document.querySelectorAll(
                    '[data-testid^="tweetTextarea_"][role="textbox"], [data-testid^="tweetTextarea_"][contenteditable="true"]'))
                .filter((node) => node.getClientRects().length > 0);
        const editor = editors[index] || editors.at(-1) ||
            await waitFor(composer, 'Thread 编辑器未加载。');
        await setEditable(editor, posts[index]);
        if (index < posts.length - 1) {
          const add = await waitFor(
              () => visible(document.querySelectorAll(
                  '[data-testid="addButton"], button[aria-label="添加帖子"], button[aria-label="Add post"]')),
              '找不到 Thread 的“添加帖子”按钮。');
          add.click();
          await pause(180);
        }
      }
      await clickPublish();
      return {
        data: {published: true, kind: 'thread', count: posts.length, posts}
      };
    }
  }
}


// 发布长文 — write. 在 X 主页打开文章编辑器并发布标题和正文；必须传
// confirm=true，且账号需有文章权限。
async function x_publish_article(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_publish_article'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'title' in rawInput &&
        'content' in rawInput && 'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['title', 'content', 'confirm'].includes(key)) &&
        (!('title' in rawInput) ||
         (typeof rawInput['title'] === 'string' &&
          [...rawInput['title']].length >= 1 &&
          [...rawInput['title']].length <= 200)) &&
        (!('content' in rawInput) ||
         (typeof rawInput['content'] === 'string' &&
          [...rawInput['content']].length >= 1 &&
          [...rawInput['content']].length <= 100000)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const setEditable = async (element, value) => {
      element.focus();
      if (element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement) {
        const prototype = element instanceof HTMLTextAreaElement ?
            HTMLTextAreaElement.prototype :
            HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (!setter)
          throw new Error('SITE_CHANGED: X 表单控件不支持标准 value setter。');
        setter.call(element, value);
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
        element.dispatchEvent(new Event('change', {bubbles: true}));
        await pause(80);
        if (element.value !== value)
          throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
        return;
      }
      const selection = getSelection();
      selection?.selectAllChildren(element);
      let inserted = false;
      try {
        inserted = typeof document.execCommand === 'function' &&
            document.execCommand('insertText', false, value);
      } catch {
        inserted = false;
      }
      if (!inserted ||
          clean(element.innerText || element.textContent) !== clean(value)) {
        element.textContent = '';
        element.dispatchEvent(new InputEvent(
            'beforeinput',
            {bubbles: true, inputType: 'insertText', data: value}));
        element.textContent = value;
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
      }
      await pause(80);
      if (clean(element.innerText || element.textContent) !== clean(value))
        throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const requireConfirmed = () => {
      if (input.confirm !== true)
        throw new Error(
            'VALIDATION_ERROR: 该 X 外部写操作必须传 confirm=true。');
    };
    {
      requireConfirmed();
      if (location.pathname !== '/compose/articles')
        throw new Error('UNSUPPORTED_ROUTE: 长文发布需要 X 文章编辑页。');
      if (!document.querySelector('[contenteditable="true"], textarea')) {
        const create = await waitFor(
            () => visible(
                document.querySelectorAll('button[aria-label="create"]')),
            '找不到新建文章按钮。');
        create.click();
        await pause(700);
      }
      const title = await waitFor(
          () => visible(document.querySelectorAll(
              '[data-testid="twitter-article-title"][contenteditable="true"], textarea[placeholder*="title" i], textarea[placeholder*="标题"], [contenteditable="true"][aria-label*="title" i], [contenteditable="true"][aria-label*="标题"]')),
          '文章标题编辑器未加载。');
      const body = await waitFor(
          () => visible(Array
                            .from(document.querySelectorAll(
                                '[contenteditable="true"], textarea'))
                            .filter(
                                (node) => node !== title &&
                                    !title.contains(node) &&
                                    !node.contains(title))),
          '文章正文编辑器未加载。');
      await setEditable(title, clean(input.title));
      await setEditable(body, clean(input.content));
      const publish = await waitFor(
          () => visible(
              Array.from(document.querySelectorAll('button'))
                  .filter(
                      (node) => !node.disabled &&
                          /^(发布|Publish)(文章| article)?$/i.test(
                              clean(node.innerText || node.textContent)))),
          '找不到文章发布按钮。');
      publish.click();
      await pause(350);
      const confirm = visible(
          Array.from(document.querySelectorAll('[role="dialog"] button'))
              .filter(
                  (node) => !node.disabled &&
                      /发布|Publish/i.test(
                          clean(node.innerText || node.textContent))));
      if (confirm) {
        confirm.click();
        await pause(900);
      }
      return {
        data: {published: true, kind: 'article', title: clean(input.title)}
      };
    }
  }
}


// 点赞帖子 — write. 点赞目标帖子；如果已经点赞则不重复操作，也不会取消点赞。
async function x_like_post(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_like_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^\\d{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+')
              .test(rawInput['postUrl'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const requestedStatusId = () => {
      const explicit = clean(input.postId);
      if (explicit)
        return explicit;
      const url = clean(input.postUrl);
      if (url) {
        try {
          const parsed = new URL(url);
          if (parsed.protocol !== 'https:' || parsed.hostname !== 'x.com')
            return '';
          return statusMatch(parsed.pathname)?.[2] || '';
        } catch {
          return '';
        }
      }
      return location.pathname.match(/^\/[A-Za-z0-9_]{1,15}\/status\/(\d+)/)
                 ?.[1] ||
          '';
    };
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const findArticle = () => {
      const id = requestedStatusId();
      if (!id && location.pathname === '/home')
        return null;
      if (!id)
        return articleNodes()[0] || null;
      return articleNodes().find((article) => statusInfo(article).id === id) ||
          null;
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const requireTarget = () => {
      const target = findArticle();
      if (!target)
        throw new Error(
            location.pathname === '/home' && !requestedStatusId() ?
                'VALIDATION_ERROR: 在主页操作帖子时必须传 postId 或完整 postUrl。' :
                'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标帖子。');
      return target;
    };
    {
      const target = requireTarget();
      const already = target.querySelector('[data-testid="unlike"]');
      if (already)
        return {
          data: {postId: statusInfo(target).id, liked: true, changed: false}
        };
      const like = target.querySelector('[data-testid="like"]');
      if (!like)
        throw new Error('SITE_CHANGED: 目标帖子没有可用的点赞按钮。');
      like.click();
      await waitFor(
          () => target.querySelector('[data-testid="unlike"]'),
          '点赞后页面状态未更新。');
      return {
        data: {postId: statusInfo(target).id, liked: true, changed: true}
      };
    }
  }
}


// 回复帖子 — write. 回复目标帖子；必须传 confirm=true。
async function x_reply_post(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_reply_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'text' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'text', 'confirm'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^\\d{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+')
              .test(rawInput['postUrl']))) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 25000)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const requestedStatusId = () => {
      const explicit = clean(input.postId);
      if (explicit)
        return explicit;
      const url = clean(input.postUrl);
      if (url) {
        try {
          const parsed = new URL(url);
          if (parsed.protocol !== 'https:' || parsed.hostname !== 'x.com')
            return '';
          return statusMatch(parsed.pathname)?.[2] || '';
        } catch {
          return '';
        }
      }
      return location.pathname.match(/^\/[A-Za-z0-9_]{1,15}\/status\/(\d+)/)
                 ?.[1] ||
          '';
    };
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const findArticle = () => {
      const id = requestedStatusId();
      if (!id && location.pathname === '/home')
        return null;
      if (!id)
        return articleNodes()[0] || null;
      return articleNodes().find((article) => statusInfo(article).id === id) ||
          null;
    };
    const composer = () => visible(document.querySelectorAll(
        '[data-testid^="tweetTextarea_"][role="textbox"], [data-testid^="tweetTextarea_"][contenteditable="true"]'));
    const setEditable = async (element, value) => {
      element.focus();
      if (element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement) {
        const prototype = element instanceof HTMLTextAreaElement ?
            HTMLTextAreaElement.prototype :
            HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (!setter)
          throw new Error('SITE_CHANGED: X 表单控件不支持标准 value setter。');
        setter.call(element, value);
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
        element.dispatchEvent(new Event('change', {bubbles: true}));
        await pause(80);
        if (element.value !== value)
          throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
        return;
      }
      const selection = getSelection();
      selection?.selectAllChildren(element);
      let inserted = false;
      try {
        inserted = typeof document.execCommand === 'function' &&
            document.execCommand('insertText', false, value);
      } catch {
        inserted = false;
      }
      if (!inserted ||
          clean(element.innerText || element.textContent) !== clean(value)) {
        element.textContent = '';
        element.dispatchEvent(new InputEvent(
            'beforeinput',
            {bubbles: true, inputType: 'insertText', data: value}));
        element.textContent = value;
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
      }
      await pause(80);
      if (clean(element.innerText || element.textContent) !== clean(value))
        throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const clickPublish =
        async (testIds = ['tweetButtonInline', 'tweetButton']) => {
      const button = await waitFor(
          () => visible(testIds
                            .flatMap(
                                (id) => Array.from(document.querySelectorAll(
                                    `button[data-testid="${id}"]`)))
                            .filter((node) => !node.disabled)),
          '找不到可用的发布按钮。');
      button.click();
      await pause(800);
    };
    const requireConfirmed = () => {
      if (input.confirm !== true)
        throw new Error(
            'VALIDATION_ERROR: 该 X 外部写操作必须传 confirm=true。');
    };
    const requireTarget = () => {
      const target = findArticle();
      if (!target)
        throw new Error(
            location.pathname === '/home' && !requestedStatusId() ?
                'VALIDATION_ERROR: 在主页操作帖子时必须传 postId 或完整 postUrl。' :
                'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标帖子。');
      return target;
    };
    {
      requireConfirmed();
      const target = requireTarget();
      const button = target.querySelector('[data-testid="reply"]');
      if (!button)
        throw new Error('SITE_CHANGED: 目标帖子没有回复按钮。');
      button.click();
      const editor = await waitFor(composer, '回复编辑器未加载。');
      await setEditable(editor, clean(input.text));
      await clickPublish(['tweetButton']);
      return {
        data: {
          postId: statusInfo(target).id,
          replied: true,
          text: clean(input.text)
        }
      };
    }
  }
}


// 引用帖子 — write. 带文字引用目标帖子并发布；必须传 confirm=true。
async function x_quote_post(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_quote_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'text' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'text', 'confirm'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^\\d{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+')
              .test(rawInput['postUrl']))) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 25000)) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const requestedStatusId = () => {
      const explicit = clean(input.postId);
      if (explicit)
        return explicit;
      const url = clean(input.postUrl);
      if (url) {
        try {
          const parsed = new URL(url);
          if (parsed.protocol !== 'https:' || parsed.hostname !== 'x.com')
            return '';
          return statusMatch(parsed.pathname)?.[2] || '';
        } catch {
          return '';
        }
      }
      return location.pathname.match(/^\/[A-Za-z0-9_]{1,15}\/status\/(\d+)/)
                 ?.[1] ||
          '';
    };
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const findArticle = () => {
      const id = requestedStatusId();
      if (!id && location.pathname === '/home')
        return null;
      if (!id)
        return articleNodes()[0] || null;
      return articleNodes().find((article) => statusInfo(article).id === id) ||
          null;
    };
    const composer = () => visible(document.querySelectorAll(
        '[data-testid^="tweetTextarea_"][role="textbox"], [data-testid^="tweetTextarea_"][contenteditable="true"]'));
    const setEditable = async (element, value) => {
      element.focus();
      if (element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement) {
        const prototype = element instanceof HTMLTextAreaElement ?
            HTMLTextAreaElement.prototype :
            HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (!setter)
          throw new Error('SITE_CHANGED: X 表单控件不支持标准 value setter。');
        setter.call(element, value);
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
        element.dispatchEvent(new Event('change', {bubbles: true}));
        await pause(80);
        if (element.value !== value)
          throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
        return;
      }
      const selection = getSelection();
      selection?.selectAllChildren(element);
      let inserted = false;
      try {
        inserted = typeof document.execCommand === 'function' &&
            document.execCommand('insertText', false, value);
      } catch {
        inserted = false;
      }
      if (!inserted ||
          clean(element.innerText || element.textContent) !== clean(value)) {
        element.textContent = '';
        element.dispatchEvent(new InputEvent(
            'beforeinput',
            {bubbles: true, inputType: 'insertText', data: value}));
        element.textContent = value;
        element.dispatchEvent(new InputEvent(
            'input', {bubbles: true, inputType: 'insertText', data: value}));
      }
      await pause(80);
      if (clean(element.innerText || element.textContent) !== clean(value))
        throw new Error('VALIDATION_ERROR: X 编辑器拒绝了输入内容。');
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const clickPublish =
        async (testIds = ['tweetButtonInline', 'tweetButton']) => {
      const button = await waitFor(
          () => visible(testIds
                            .flatMap(
                                (id) => Array.from(document.querySelectorAll(
                                    `button[data-testid="${id}"]`)))
                            .filter((node) => !node.disabled)),
          '找不到可用的发布按钮。');
      button.click();
      await pause(800);
    };
    const requireConfirmed = () => {
      if (input.confirm !== true)
        throw new Error(
            'VALIDATION_ERROR: 该 X 外部写操作必须传 confirm=true。');
    };
    const requireTarget = () => {
      const target = findArticle();
      if (!target)
        throw new Error(
            location.pathname === '/home' && !requestedStatusId() ?
                'VALIDATION_ERROR: 在主页操作帖子时必须传 postId 或完整 postUrl。' :
                'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标帖子。');
      return target;
    };
    {
      requireConfirmed();
      const target = requireTarget();
      if ('quote_post' === 'repost_post' &&
          target.querySelector('[data-testid="unretweet"]'))
        return {
          data: {postId: statusInfo(target).id, reposted: true, changed: false}
        };
      const button = target.querySelector(
          '[data-testid="retweet"], [data-testid="unretweet"]');
      if (!button)
        throw new Error('SITE_CHANGED: 目标帖子没有转帖按钮。');
      button.click();
      const quote = await waitFor(
          () =>
              visible(Array.from(document.querySelectorAll('[role="menuitem"]'))
                          .filter(
                              (node) => /^(引用|Quote)$/i.test(
                                  clean(node.innerText || node.textContent)))),
          '转帖菜单中找不到引用入口。');
      quote.click();
      const editor = await waitFor(composer, '引用编辑器未加载。');
      await setEditable(editor, clean(input.text));
      await clickPublish(['tweetButton']);
      return {
        data: {
          postId: statusInfo(target).id,
          quoted: true,
          text: clean(input.text)
        }
      };
    }
  }
}


// 转帖 — write. 转帖目标帖子；如果已经转帖则不重复操作，必须传 confirm=true。
async function x_repost_post(rawInput = {}) {
  const reservedPaths = new Set([
    'home', 'explore', 'notifications', 'messages', 'i', 'compose', 'search',
    'settings', 'login', 'logout', 'signup', 'tos', 'privacy', 'about', 'jobs'
  ]);
  const route = (url) => {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length === 1 && parts[0] === 'home')
      return {type: 'home', identity: 'home'};
    if (parts.length === 3 && parts[1] === 'status' &&
        /^\d+$/.test(parts[2] || '') &&
        /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '')) {
      return {type: 'post', identity: `post:${parts[2]}`};
    }
    if (parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0] || '') &&
        !reservedPaths.has(parts[0].toLowerCase())) {
      return {type: 'profile', identity: `profile:${parts[0].toLowerCase()}`};
    }
    return null;
  };
  const homeTools = [
    'x_get_home_feed', 'x_get_post_thread', 'x_publish_post',
    'x_publish_thread', 'x_publish_article', 'x_like_post', 'x_reply_post',
    'x_quote_post', 'x_repost_post'
  ];
  const postTools = [
    'x_get_post_thread', 'x_like_post', 'x_reply_post', 'x_quote_post',
    'x_repost_post'
  ];
  const profileTools = ['x_get_profile_latest_posts'];
  const xAdapter = {
    matches: (url) => url.protocol === 'https:' && url.hostname === 'x.com' &&
        route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type === 'home' ? homeTools :
          type === 'post'    ? postTools :
          type === 'profile' ? profileTools :
                               [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!xAdapter.matches(routeUrl) ||
      !xAdapter.toolNames(routeUrl).includes('x_repost_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported X page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'confirm'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^\\d{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+')
              .test(rawInput['postUrl']))) &&
        (!('confirm' in rawInput) ||
         (typeof rawInput['confirm'] === 'boolean' &&
          [true].includes(rawInput['confirm'])))))
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const statusMatch = (value) =>
        String(value || '')
            .match(/^\/(?:#!\/)?([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
    const requestedStatusId = () => {
      const explicit = clean(input.postId);
      if (explicit)
        return explicit;
      const url = clean(input.postUrl);
      if (url) {
        try {
          const parsed = new URL(url);
          if (parsed.protocol !== 'https:' || parsed.hostname !== 'x.com')
            return '';
          return statusMatch(parsed.pathname)?.[2] || '';
        } catch {
          return '';
        }
      }
      return location.pathname.match(/^\/[A-Za-z0-9_]{1,15}\/status\/(\d+)/)
                 ?.[1] ||
          '';
    };
    const statusInfo = (article) => {
      for (const time of Array.from(article.querySelectorAll('time'))) {
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = statusMatch(href);
        if (match)
          return {
            handle: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/status/${match[2]}`,
            publishedAt: time.getAttribute('datetime') || null
          };
      }
      return {handle: '', id: '', url: '', publishedAt: null};
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
    const findArticle = () => {
      const id = requestedStatusId();
      if (!id && location.pathname === '/home')
        return null;
      if (!id)
        return articleNodes()[0] || null;
      return articleNodes().find((article) => statusInfo(article).id === id) ||
          null;
    };
    const waitFor = async (read, message, timeout = 8000) => {
      const started = Date.now();
      for (;;) {
        const value = read();
        if (value)
          return value;
        if (Date.now() - started >= timeout)
          throw new Error(`SITE_CHANGED: ${message}`);
        await pause(100);
      }
    };
    const requireConfirmed = () => {
      if (input.confirm !== true)
        throw new Error(
            'VALIDATION_ERROR: 该 X 外部写操作必须传 confirm=true。');
    };
    const requireTarget = () => {
      const target = findArticle();
      if (!target)
        throw new Error(
            location.pathname === '/home' && !requestedStatusId() ?
                'VALIDATION_ERROR: 在主页操作帖子时必须传 postId 或完整 postUrl。' :
                'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标帖子。');
      return target;
    };
    {
      requireConfirmed();
      const target = requireTarget();
      if ('repost_post' === 'repost_post' &&
          target.querySelector('[data-testid="unretweet"]'))
        return {
          data: {postId: statusInfo(target).id, reposted: true, changed: false}
        };
      const button = target.querySelector(
          '[data-testid="retweet"], [data-testid="unretweet"]');
      if (!button)
        throw new Error('SITE_CHANGED: 目标帖子没有转帖按钮。');
      button.click();
      {
        const confirm = await waitFor(
            () => visible(
                document.querySelectorAll('[data-testid="retweetConfirm"]')),
            '转帖确认项未出现。');
        confirm.click();
        await waitFor(
            () => target.querySelector('[data-testid="unretweet"]'),
            '转帖后页面状态未更新。');
        return {
          data: {postId: statusInfo(target).id, reposted: true, changed: true}
        };
      }
    }
  }
}
