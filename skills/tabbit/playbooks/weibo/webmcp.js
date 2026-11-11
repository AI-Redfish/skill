// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取首页信息流 — read.
// 滚动并读取当前首页所选信息流中观察到的全部微博，保留正文、媒体、链接和互动数。
async function weibo_get_home_feed(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes('weibo_get_home_feed'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const metric = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*(万|亿)?/);
      if (!match)
        return 0;
      const multiplier = match[2] === '亿' ? 100000000 :
          match[2] === '万'                ? 10000 :
                                             1;
      return Math.round(Number(match[1]) * multiplier) || 0;
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = postInfo(article);
      const header = article.querySelector('header');
      const authorLink =
          header?.querySelector(
              'a[usercard], a[href*="/u/"][aria-label], a[href*="/u/"]') ||
          null;
      const authorId = clean(authorLink?.getAttribute('usercard')) ||
          authorLink?.href.match(/\/u\/(\d+)/)?.[1] || info.uid || null;
      const authorName = clean(
                             authorLink?.getAttribute('aria-label') ||
                             authorLink?.textContent) ||
          null;
      const contentRoot = article.querySelector('.wbpro-feed-content');
      const content = clean(contentRoot?.innerText || contentRoot?.textContent)
                          .replace(/\s*\.{3}展开\s*$/, '');
      const media = contentRoot ?
          [
            ...Array
                .from(contentRoot.querySelectorAll(
                    '.woo-picture-main img, img[class*="focusImg"]'))
                .map((node) => ({
                       type: 'image',
                       url: absolute(node.currentSrc || node.src),
                       alt: clean(node.alt) || null
                     })),
            ...Array.from(contentRoot.querySelectorAll('video'))
                .map((node) => ({
                       type: 'video',
                       url: absolute(node.currentSrc || node.src) || null,
                       poster: absolute(node.poster) || null
                     }))
          ]
              .filter(
                  (entry) => entry.url || ('poster' in entry && entry.poster)) :
          [];
      const links = contentRoot ?
          Array.from(contentRoot.querySelectorAll('a[href]'))
              .map((node) => ({
                     text: clean(node.textContent),
                     url: absolute(node.href)
                   }))
              .filter((entry) => entry.url) :
          [];
      const footer = article.querySelector('footer');
      const ariaMetrics = clean(footer?.getAttribute('aria-label')).split(',');
      const source =
          clean(article.querySelector('[title^="来自"]')?.getAttribute('title'))
              .replace(/^来自\s*/, '') ||
          null;
      const locationLabel =
          clean(
              article.querySelector('[title^="发布于"]')?.getAttribute('title'))
              .replace(/^发布于\s*/, '') ||
          null;
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          id: authorId,
          name: authorName,
          profileUrl: authorId ? `https://weibo.com/u/${authorId}` : null
        },
        publishedAt: info.publishedAt,
        source,
        location: locationLabel,
        content,
        media,
        links,
        metrics: {
          reposts: metric(
              ariaMetrics[0] ||
              footer?.querySelector('[title="转发"]')
                  ?.parentElement?.textContent),
          comments: metric(
              ariaMetrics[1] ||
              footer?.querySelector('[title="评论"]')
                  ?.parentElement?.textContent),
          likes: metric(
              ariaMetrics[2] ||
              footer?.querySelector('button.woo-like-main')?.textContent)
        },
        pinned: /(^|\n)置顶(\n|$)/.test(
            clean(article.innerText || article.textContent))
      };
    };
    const expandArticle = async (article) => {
      const controls =
          Array.from(article.querySelectorAll('.wbpro-feed-content .expand'))
              .filter((node) => clean(node.textContent) === '展开');
      const control = visible(controls);
      if (control) {
        control.click();
        await pause(80);
      }
    };
    const collectPosts = async (limit, maxScrolls, predicate = () => true) => {
      const originalY = window.scrollY;
      const collected = new Map();
      let idle = 0;
      let scrolls = 0;
      let endReached = false;
      const collect = async () => {
        const before = collected.size;
        for (const article of articleNodes()) {
          await expandArticle(article);
          const post = postFromArticle(article);
          if (post.id && predicate(post) && !collected.has(post.id))
            collected.set(post.id, post);
          if (collected.size >= limit)
            break;
        }
        return collected.size - before;
      };
      if (window.scrollY > 8) {
        window.scrollTo({top: 0, behavior: 'auto'});
        await pause(180);
      }
      await collect();
      while (collected.size < limit && scrolls < maxScrolls && idle < 3 &&
             !endReached) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(640, window.innerHeight * 0.82), behavior: 'auto'});
        await pause(450);
        const added = await collect();
        scrolls += 1;
        const pageText = clean(document.querySelector('main')?.textContent);
        endReached =
            /已加载全部|没有更多|到底了/.test(pageText.slice(-500));
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, limit);
      const hitLimit = collected.size >= limit;
      const stoppedByCap =
          scrolls >= maxScrolls && !endReached && idle < 3 && !hitLimit;
      const truncated = hitLimit || stoppedByCap;
      if (window.scrollY !== originalY) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      return {
        items,
        count: items.length,
        scrolls,
        complete: !truncated && (endReached || idle >= 3),
        truncated,
        stopReason: hitLimit ? 'max_posts' :
            stoppedByCap     ? 'max_scrolls' :
            endReached       ? 'end_marker' :
                               'stable'
      };
    };
    {
      if (!isHome)
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在微博首页可用。');
      const maxPosts =
          Math.min(200, Math.max(1, Number(input.maxPosts ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const data = await collectPosts(maxPosts, maxScrolls);
      const activeFeed =
          clean(document.querySelector('a[active], [aria-selected="true"]')
                    ?.textContent) ||
          document.title;
      return {
        data: {feed: activeFeed, ...data},
        warnings: data.truncated ?
            ['微博信息流按需加载；结果达到调用上限，truncated=true。'] :
            []
      };
    }
  }
}


// 读取微博及评论 — read.
// 在首页或微博详情页读取目标微博的完整可见正文、媒体、评论和回复。
async function weibo_get_post_with_comments(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes(
          'weibo_get_post_with_comments'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'maxComments', 'maxScrolls',
                    'includeReplies']
                       .includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^[A-Za-z0-9]{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$')
              .test(rawInput['postUrl']))) &&
        (!('maxComments' in rawInput) ||
         (Number.isInteger(rawInput['maxComments']) &&
          rawInput['maxComments'] >= 1 && rawInput['maxComments'] <= 500)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 50)) &&
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
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/[ \t]+\n/g, '\n')
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const currentPost =
        currentPath.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const requestedPostId = () => clean(input.postId) ||
        postPath(input.postUrl)?.id || currentPost?.[2] || '';
    const metric = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*(万|亿)?/);
      if (!match)
        return 0;
      const multiplier = match[2] === '亿' ? 100000000 :
          match[2] === '万'                ? 10000 :
                                             1;
      return Math.round(Number(match[1]) * multiplier) || 0;
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = postInfo(article);
      const header = article.querySelector('header');
      const authorLink =
          header?.querySelector(
              'a[usercard], a[href*="/u/"][aria-label], a[href*="/u/"]') ||
          null;
      const authorId = clean(authorLink?.getAttribute('usercard')) ||
          authorLink?.href.match(/\/u\/(\d+)/)?.[1] || info.uid || null;
      const authorName = clean(
                             authorLink?.getAttribute('aria-label') ||
                             authorLink?.textContent) ||
          null;
      const contentRoot = article.querySelector('.wbpro-feed-content');
      const content = clean(contentRoot?.innerText || contentRoot?.textContent)
                          .replace(/\s*\.{3}展开\s*$/, '');
      const media = contentRoot ?
          [
            ...Array
                .from(contentRoot.querySelectorAll(
                    '.woo-picture-main img, img[class*="focusImg"]'))
                .map((node) => ({
                       type: 'image',
                       url: absolute(node.currentSrc || node.src),
                       alt: clean(node.alt) || null
                     })),
            ...Array.from(contentRoot.querySelectorAll('video'))
                .map((node) => ({
                       type: 'video',
                       url: absolute(node.currentSrc || node.src) || null,
                       poster: absolute(node.poster) || null
                     }))
          ]
              .filter(
                  (entry) => entry.url || ('poster' in entry && entry.poster)) :
          [];
      const links = contentRoot ?
          Array.from(contentRoot.querySelectorAll('a[href]'))
              .map((node) => ({
                     text: clean(node.textContent),
                     url: absolute(node.href)
                   }))
              .filter((entry) => entry.url) :
          [];
      const footer = article.querySelector('footer');
      const ariaMetrics = clean(footer?.getAttribute('aria-label')).split(',');
      const source =
          clean(article.querySelector('[title^="来自"]')?.getAttribute('title'))
              .replace(/^来自\s*/, '') ||
          null;
      const locationLabel =
          clean(
              article.querySelector('[title^="发布于"]')?.getAttribute('title'))
              .replace(/^发布于\s*/, '') ||
          null;
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          id: authorId,
          name: authorName,
          profileUrl: authorId ? `https://weibo.com/u/${authorId}` : null
        },
        publishedAt: info.publishedAt,
        source,
        location: locationLabel,
        content,
        media,
        links,
        metrics: {
          reposts: metric(
              ariaMetrics[0] ||
              footer?.querySelector('[title="转发"]')
                  ?.parentElement?.textContent),
          comments: metric(
              ariaMetrics[1] ||
              footer?.querySelector('[title="评论"]')
                  ?.parentElement?.textContent),
          likes: metric(
              ariaMetrics[2] ||
              footer?.querySelector('button.woo-like-main')?.textContent)
        },
        pinned: /(^|\n)置顶(\n|$)/.test(
            clean(article.innerText || article.textContent))
      };
    };
    const expandArticle = async (article) => {
      const controls =
          Array.from(article.querySelectorAll('.wbpro-feed-content .expand'))
              .filter((node) => clean(node.textContent) === '展开');
      const control = visible(controls);
      if (control) {
        control.click();
        await pause(80);
      }
    };
    const findTarget = async (allowFirst = false) => {
      const id = requestedPostId();
      const find = () =>
          articleNodes().find((article) => postInfo(article).id === id) || null;
      if (id) {
        let target = find();
        if (target)
          return target;
        if (isHome) {
          window.scrollTo({top: 0, behavior: 'auto'});
          await pause(180);
          for (let index = 0; index < 20 && !target; index += 1) {
            target = find();
            if (target)
              break;
            window.scrollBy({
              top: Math.max(640, window.innerHeight * 0.82),
              behavior: 'auto'
            });
            await pause(350);
          }
        }
        return target;
      }
      if (currentPost || allowFirst)
        return articleNodes()[0] || null;
      return null;
    };
    const requireTarget = async () => {
      const target = await findTarget(false);
      if (target)
        return target;
      if (isHome && !requestedPostId())
        throw new Error(
            'VALIDATION_ERROR: 在微博首页操作帖子时必须传 postId 或完整 postUrl。');
      throw new Error(
          'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标微博。');
    };
    const clickAction = (article, title) => {
      const icon = article.querySelector(`[title="${title}"]`);
      const control = icon?.closest('[class*="_item_"]') || icon?.parentElement;
      if (!control)
        throw new Error(`SITE_CHANGED: 目标微博没有“${title}”操作。`);
      control.click();
    };
    const commentFromNode = (node, index) => {
      const textNode = node.querySelector('.text');
      const authorLink =
          textNode?.querySelector('a[usercard], a[href*="/u/"]') || null;
      const author = clean(authorLink?.textContent) || '未知用户';
      const authorId = clean(authorLink?.getAttribute('usercard')) ||
          authorLink?.href.match(/\/u\/(\d+)/)?.[1] || null;
      const fullText = clean(textNode?.innerText || textNode?.textContent);
      const content = clean(fullText.replace(
          new RegExp(
              `^${author.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*[:：]\\s*`),
          ''));
      const infoNode = node.querySelector('.info > div:first-child, .info');
      const publishedAt =
          clean(infoNode?.childNodes[0]?.textContent || infoNode?.textContent)
              .replace(/\s*来自.*$/, '') ||
          null;
      const locationLabel = clean(infoNode?.querySelector('span')?.textContent)
                                .replace(/^来自\s*/, '') ||
          null;
      const likeButton = node.querySelector('button.woo-like-main');
      const depth =
          node.classList.contains('item2') || Boolean(node.closest('.list2')) ?
          1 :
          0;
      const stable =
          clean(node.dataset.id || node.getAttribute('comment_id')) ||
          `${authorId || author}:${publishedAt || index}:${
              content.slice(0, 80)}`;
      return {
        id: stable,
        author: {
          id: authorId,
          name: author,
          profileUrl: authorId ? `https://weibo.com/u/${authorId}` :
                                 absolute(authorLink?.href || '') || null
        },
        content,
        publishedAt,
        location: locationLabel,
        likeCount: metric(likeButton?.textContent),
        depth
      };
    };
    const commentNodes = (scope, includeReplies) => {
      const top = Array.from(scope.querySelectorAll('.wbpro-list .item1'));
      const replies = includeReplies ?
          Array.from(scope.querySelectorAll('.wbpro-list .item2')) :
          [];
      return [...top, ...replies].filter(
          (node) =>
              node.querySelector('.text')?.closest('.item1, .item2') === node &&
              node.querySelector('.info')?.closest('.item1, .item2') === node);
    };
    const replyControls = (scope) =>
        Array
            .from(scope.querySelectorAll(
                '.wbpro-list .list2 a, .wbpro-list .list2 button'))
            .filter(
                (node) =>
                    /^(查看更多评论|查看更多|展开更多回复|共\d+条回复)$/
                        .test(clean(node.textContent)));
    const collectComments =
        async (scope, limit, maxScrolls, includeReplies) => {
      const originalY = window.scrollY;
      const collected = new Map();
      let scrolls = 0;
      let idle = 0;
      let endReached = false;
      const collect = () => {
        const before = collected.size;
        commentNodes(scope(), includeReplies).forEach((node, index) => {
          const comment = commentFromNode(node, index);
          if (comment.content && !collected.has(comment.id))
            collected.set(comment.id, comment);
        });
        return collected.size - before;
      };
      collect();
      const hasCommentEndMarker = () =>
          (!includeReplies || replyControls(scope()).length === 0) &&
          Array.from(scope().querySelectorAll('div, span'))
              .some(
                  (node) => /^(已加载全部评论|还没有人评论)$/.test(
                      clean(node.textContent)));
      endReached = hasCommentEndMarker();
      while (collected.size < limit && scrolls < maxScrolls && idle < 3 &&
             !endReached) {
        const root = scope();
        const more = (includeReplies ? visible(replyControls(root)) : null) ||
            visible(Array.from(root.querySelectorAll('button, a, div, span'))
                        .filter(
                            (node) => !node.closest('.list2') &&
                                /^(查看更多评论|查看更多)$/.test(
                                    clean(node.textContent)) &&
                                node.children.length <= 2));
        if (more)
          more.click();
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(520, window.innerHeight * 0.75), behavior: 'auto'});
        await pause(400);
        const added = collect();
        scrolls += 1;
        endReached = hasCommentEndMarker();
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, limit);
      const hitLimit = collected.size >= limit;
      const stoppedByCap =
          scrolls >= maxScrolls && !endReached && idle < 3 && !hitLimit;
      const truncated = hitLimit || !endReached;
      if (window.scrollY !== originalY) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      return {
        items,
        count: items.length,
        scrolls,
        complete: !truncated,
        truncated,
        stopReason: hitLimit ? 'max_comments' :
            stoppedByCap     ? 'max_scrolls' :
            endReached       ? 'end_marker' :
                               'stable'
      };
    };
    const actionScope = (target) =>
        currentPost ? document : target.parentElement || document;
    {
      const target = await requireTarget();
      await expandArticle(target);
      let openedComments = false;
      let scope = () => actionScope(target);
      if (!scope().querySelector('textarea[placeholder="发布你的评论"]') &&
          !scope().querySelector('.wbpro-list .item1')) {
        clickAction(target, '评论');
        openedComments = true;
        await pause(350);
      }
      const refreshed = await findTarget(false) || target;
      scope = () => actionScope(refreshed);
      const maxComments =
          Math.min(500, Math.max(1, Number(input.maxComments ?? 200)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const comments = await collectComments(
          scope, maxComments, maxScrolls, input.includeReplies !== false);
      const post = postFromArticle(refreshed);
      if (openedComments && isHome) {
        try {
          clickAction(refreshed, '评论');
          await pause(100);
        } catch { /* Keep the extracted result if the panel rerendered. */
        }
      }
      return {
        data: {post, comments},
        warnings: comments.truncated ?
            ['微博评论按需加载；结果不完整，truncated=true。'] :
            post.metrics.comments > 0 && comments.count === 0 ?
            ['页面显示有评论，但评论列表尚未加载或当前不可见。'] :
            []
      };
    }
  }
}


// 读取博主最新 6 条微博 — read. 读取当前博主主页最新发布的 6
// 条非置顶微博；不把旧置顶微博计入最新列表。
async function weibo_get_profile_latest_posts(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes(
          'weibo_get_profile_latest_posts'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const currentProfile = currentPath.match(/^\/u\/(\d{1,20})$/);
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const metric = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*(万|亿)?/);
      if (!match)
        return 0;
      const multiplier = match[2] === '亿' ? 100000000 :
          match[2] === '万'                ? 10000 :
                                             1;
      return Math.round(Number(match[1]) * multiplier) || 0;
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = postInfo(article);
      const header = article.querySelector('header');
      const authorLink =
          header?.querySelector(
              'a[usercard], a[href*="/u/"][aria-label], a[href*="/u/"]') ||
          null;
      const authorId = clean(authorLink?.getAttribute('usercard')) ||
          authorLink?.href.match(/\/u\/(\d+)/)?.[1] || info.uid || null;
      const authorName = clean(
                             authorLink?.getAttribute('aria-label') ||
                             authorLink?.textContent) ||
          null;
      const contentRoot = article.querySelector('.wbpro-feed-content');
      const content = clean(contentRoot?.innerText || contentRoot?.textContent)
                          .replace(/\s*\.{3}展开\s*$/, '');
      const media = contentRoot ?
          [
            ...Array
                .from(contentRoot.querySelectorAll(
                    '.woo-picture-main img, img[class*="focusImg"]'))
                .map((node) => ({
                       type: 'image',
                       url: absolute(node.currentSrc || node.src),
                       alt: clean(node.alt) || null
                     })),
            ...Array.from(contentRoot.querySelectorAll('video'))
                .map((node) => ({
                       type: 'video',
                       url: absolute(node.currentSrc || node.src) || null,
                       poster: absolute(node.poster) || null
                     }))
          ]
              .filter(
                  (entry) => entry.url || ('poster' in entry && entry.poster)) :
          [];
      const links = contentRoot ?
          Array.from(contentRoot.querySelectorAll('a[href]'))
              .map((node) => ({
                     text: clean(node.textContent),
                     url: absolute(node.href)
                   }))
              .filter((entry) => entry.url) :
          [];
      const footer = article.querySelector('footer');
      const ariaMetrics = clean(footer?.getAttribute('aria-label')).split(',');
      const source =
          clean(article.querySelector('[title^="来自"]')?.getAttribute('title'))
              .replace(/^来自\s*/, '') ||
          null;
      const locationLabel =
          clean(
              article.querySelector('[title^="发布于"]')?.getAttribute('title'))
              .replace(/^发布于\s*/, '') ||
          null;
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          id: authorId,
          name: authorName,
          profileUrl: authorId ? `https://weibo.com/u/${authorId}` : null
        },
        publishedAt: info.publishedAt,
        source,
        location: locationLabel,
        content,
        media,
        links,
        metrics: {
          reposts: metric(
              ariaMetrics[0] ||
              footer?.querySelector('[title="转发"]')
                  ?.parentElement?.textContent),
          comments: metric(
              ariaMetrics[1] ||
              footer?.querySelector('[title="评论"]')
                  ?.parentElement?.textContent),
          likes: metric(
              ariaMetrics[2] ||
              footer?.querySelector('button.woo-like-main')?.textContent)
        },
        pinned: /(^|\n)置顶(\n|$)/.test(
            clean(article.innerText || article.textContent))
      };
    };
    const expandArticle = async (article) => {
      const controls =
          Array.from(article.querySelectorAll('.wbpro-feed-content .expand'))
              .filter((node) => clean(node.textContent) === '展开');
      const control = visible(controls);
      if (control) {
        control.click();
        await pause(80);
      }
    };
    const collectPosts = async (limit, maxScrolls, predicate = () => true) => {
      const originalY = window.scrollY;
      const collected = new Map();
      let idle = 0;
      let scrolls = 0;
      let endReached = false;
      const collect = async () => {
        const before = collected.size;
        for (const article of articleNodes()) {
          await expandArticle(article);
          const post = postFromArticle(article);
          if (post.id && predicate(post) && !collected.has(post.id))
            collected.set(post.id, post);
          if (collected.size >= limit)
            break;
        }
        return collected.size - before;
      };
      if (window.scrollY > 8) {
        window.scrollTo({top: 0, behavior: 'auto'});
        await pause(180);
      }
      await collect();
      while (collected.size < limit && scrolls < maxScrolls && idle < 3 &&
             !endReached) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(640, window.innerHeight * 0.82), behavior: 'auto'});
        await pause(450);
        const added = await collect();
        scrolls += 1;
        const pageText = clean(document.querySelector('main')?.textContent);
        endReached =
            /已加载全部|没有更多|到底了/.test(pageText.slice(-500));
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, limit);
      const hitLimit = collected.size >= limit;
      const stoppedByCap =
          scrolls >= maxScrolls && !endReached && idle < 3 && !hitLimit;
      const truncated = hitLimit || stoppedByCap;
      if (window.scrollY !== originalY) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      return {
        items,
        count: items.length,
        scrolls,
        complete: !truncated && (endReached || idle >= 3),
        truncated,
        stopReason: hitLimit ? 'max_posts' :
            stoppedByCap     ? 'max_scrolls' :
            endReached       ? 'end_marker' :
                               'stable'
      };
    };
    {
      if (!currentProfile)
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在微博博主主页可用。');
      const uid = currentProfile[1];
      const data = await collectPosts(
          6, 18, (post) => post.author.id === uid && !post.pinned);
      return {
        data: {
          uid,
          posts: data.items,
          count: data.count,
          complete: data.items.length === 6,
          truncated: data.items.length < 6 && data.truncated
        },
        warnings: data.items.length < 6 ?
            ['当前页面只观察到少于 6 条符合条件的非置顶微博。'] :
            []
      };
    }
  }
}


// 发布单条微博 — write. 在微博首页发布单条微博；必须传 confirm=true。
async function weibo_publish_post(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes('weibo_publish_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'text' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(key => ['text', 'confirm'].includes(key)) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 5000)) &&
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const metric = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*(万|亿)?/);
      if (!match)
        return 0;
      const multiplier = match[2] === '亿' ? 100000000 :
          match[2] === '万'                ? 10000 :
                                             1;
      return Math.round(Number(match[1]) * multiplier) || 0;
    };
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const postFromArticle = (article) => {
      const info = postInfo(article);
      const header = article.querySelector('header');
      const authorLink =
          header?.querySelector(
              'a[usercard], a[href*="/u/"][aria-label], a[href*="/u/"]') ||
          null;
      const authorId = clean(authorLink?.getAttribute('usercard')) ||
          authorLink?.href.match(/\/u\/(\d+)/)?.[1] || info.uid || null;
      const authorName = clean(
                             authorLink?.getAttribute('aria-label') ||
                             authorLink?.textContent) ||
          null;
      const contentRoot = article.querySelector('.wbpro-feed-content');
      const content = clean(contentRoot?.innerText || contentRoot?.textContent)
                          .replace(/\s*\.{3}展开\s*$/, '');
      const media = contentRoot ?
          [
            ...Array
                .from(contentRoot.querySelectorAll(
                    '.woo-picture-main img, img[class*="focusImg"]'))
                .map((node) => ({
                       type: 'image',
                       url: absolute(node.currentSrc || node.src),
                       alt: clean(node.alt) || null
                     })),
            ...Array.from(contentRoot.querySelectorAll('video'))
                .map((node) => ({
                       type: 'video',
                       url: absolute(node.currentSrc || node.src) || null,
                       poster: absolute(node.poster) || null
                     }))
          ]
              .filter(
                  (entry) => entry.url || ('poster' in entry && entry.poster)) :
          [];
      const links = contentRoot ?
          Array.from(contentRoot.querySelectorAll('a[href]'))
              .map((node) => ({
                     text: clean(node.textContent),
                     url: absolute(node.href)
                   }))
              .filter((entry) => entry.url) :
          [];
      const footer = article.querySelector('footer');
      const ariaMetrics = clean(footer?.getAttribute('aria-label')).split(',');
      const source =
          clean(article.querySelector('[title^="来自"]')?.getAttribute('title'))
              .replace(/^来自\s*/, '') ||
          null;
      const locationLabel =
          clean(
              article.querySelector('[title^="发布于"]')?.getAttribute('title'))
              .replace(/^发布于\s*/, '') ||
          null;
      return {
        id: info.id || null,
        url: info.url || null,
        author: {
          id: authorId,
          name: authorName,
          profileUrl: authorId ? `https://weibo.com/u/${authorId}` : null
        },
        publishedAt: info.publishedAt,
        source,
        location: locationLabel,
        content,
        media,
        links,
        metrics: {
          reposts: metric(
              ariaMetrics[0] ||
              footer?.querySelector('[title="转发"]')
                  ?.parentElement?.textContent),
          comments: metric(
              ariaMetrics[1] ||
              footer?.querySelector('[title="评论"]')
                  ?.parentElement?.textContent),
          likes: metric(
              ariaMetrics[2] ||
              footer?.querySelector('button.woo-like-main')?.textContent)
        },
        pinned: /(^|\n)置顶(\n|$)/.test(
            clean(article.innerText || article.textContent))
      };
    };
    const setNativeValue = async (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 微博输入控件不支持标准 value setter。');
      element.focus();
      setter.call(element, value);
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
      await pause(100);
      if (element.value !== value)
        throw new Error('VALIDATION_ERROR: 微博编辑器拒绝了输入内容。');
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
        throw new Error('VALIDATION_ERROR: 该微博写操作必须传 confirm=true。');
    };
    {
      requireConfirmed();
      if (!isHome)
        throw new Error('UNSUPPORTED_ROUTE: 发布微博只在微博首页可用。');
      const editor = await waitFor(
          () => visible(document.querySelectorAll(
              'textarea[placeholder="有什么新鲜事想分享给大家？"]')),
          '微博首页发布编辑器未加载。');
      const content = clean(input.text);
      await setNativeValue(editor, content);
      const button = await waitFor(
          () => visible(Array.from(document.querySelectorAll('button'))
                            .filter(
                                (node) => clean(node.textContent) === '发送' &&
                                    !node.disabled &&
                                    !node.classList.contains('disabled'))),
          '找不到可用的“发送”按钮。');
      button.click();
      await waitFor(
          () =>
              editor.value === '' || !document.contains(editor) ? editor : null,
          '发布后编辑器没有清空。');
      const published = articleNodes()
                            .map(postFromArticle)
                            .find((post) => post.content === content) ||
          null;
      return {data: {published: true, text: content, post: published}};
    }
  }
}


// 点赞微博 — write. 点赞目标微博；如果已经点赞则不重复操作，也不会取消点赞。
async function weibo_like_post(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes('weibo_like_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^[A-Za-z0-9]{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$')
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const currentPost =
        currentPath.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const requestedPostId = () => clean(input.postId) ||
        postPath(input.postUrl)?.id || currentPost?.[2] || '';
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const findTarget = async (allowFirst = false) => {
      const id = requestedPostId();
      const find = () =>
          articleNodes().find((article) => postInfo(article).id === id) || null;
      if (id) {
        let target = find();
        if (target)
          return target;
        if (isHome) {
          window.scrollTo({top: 0, behavior: 'auto'});
          await pause(180);
          for (let index = 0; index < 20 && !target; index += 1) {
            target = find();
            if (target)
              break;
            window.scrollBy({
              top: Math.max(640, window.innerHeight * 0.82),
              behavior: 'auto'
            });
            await pause(350);
          }
        }
        return target;
      }
      if (currentPost || allowFirst)
        return articleNodes()[0] || null;
      return null;
    };
    const requireTarget = async () => {
      const target = await findTarget(false);
      if (target)
        return target;
      if (isHome && !requestedPostId())
        throw new Error(
            'VALIDATION_ERROR: 在微博首页操作帖子时必须传 postId 或完整 postUrl。');
      throw new Error(
          'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标微博。');
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
      const target = await requireTarget();
      const button = target.querySelector('button.woo-like-main');
      if (!button)
        throw new Error('SITE_CHANGED: 目标微博没有点赞按钮。');
      if (/取消赞/.test(clean(button.title)) ||
          /liked|active|select/i.test(button.className))
        return {
          data: {postId: postInfo(target).id, liked: true, changed: false}
        };
      const before = clean(button.textContent);
      button.click();
      await waitFor(() => {
        const freshArticle =
            articleNodes().find(
                (article) => postInfo(article).id === postInfo(target).id) ||
            target;
        const freshButton = freshArticle.querySelector('button.woo-like-main');
        return freshButton &&
                (/取消赞/.test(clean(freshButton.title)) ||
                 clean(freshButton.textContent) !== before) ?
            freshButton :
            null;
      }, '点赞后页面状态未更新。');
      return {data: {postId: postInfo(target).id, liked: true, changed: true}};
    }
  }
}


// 回复微博 — write. 回复目标微博；必须传 confirm=true。
async function weibo_reply_post(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes('weibo_reply_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'text' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'text', 'confirm'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^[A-Za-z0-9]{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$')
              .test(rawInput['postUrl']))) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 5000)) &&
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const currentPost =
        currentPath.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const requestedPostId = () => clean(input.postId) ||
        postPath(input.postUrl)?.id || currentPost?.[2] || '';
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const findTarget = async (allowFirst = false) => {
      const id = requestedPostId();
      const find = () =>
          articleNodes().find((article) => postInfo(article).id === id) || null;
      if (id) {
        let target = find();
        if (target)
          return target;
        if (isHome) {
          window.scrollTo({top: 0, behavior: 'auto'});
          await pause(180);
          for (let index = 0; index < 20 && !target; index += 1) {
            target = find();
            if (target)
              break;
            window.scrollBy({
              top: Math.max(640, window.innerHeight * 0.82),
              behavior: 'auto'
            });
            await pause(350);
          }
        }
        return target;
      }
      if (currentPost || allowFirst)
        return articleNodes()[0] || null;
      return null;
    };
    const requireTarget = async () => {
      const target = await findTarget(false);
      if (target)
        return target;
      if (isHome && !requestedPostId())
        throw new Error(
            'VALIDATION_ERROR: 在微博首页操作帖子时必须传 postId 或完整 postUrl。');
      throw new Error(
          'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标微博。');
    };
    const clickAction = (article, title) => {
      const icon = article.querySelector(`[title="${title}"]`);
      const control = icon?.closest('[class*="_item_"]') || icon?.parentElement;
      if (!control)
        throw new Error(`SITE_CHANGED: 目标微博没有“${title}”操作。`);
      control.click();
    };
    const setNativeValue = async (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 微博输入控件不支持标准 value setter。');
      element.focus();
      setter.call(element, value);
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
      await pause(100);
      if (element.value !== value)
        throw new Error('VALIDATION_ERROR: 微博编辑器拒绝了输入内容。');
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
        throw new Error('VALIDATION_ERROR: 该微博写操作必须传 confirm=true。');
    };
    const actionScope = (target) =>
        currentPost ? document : target.parentElement || document;
    {
      requireConfirmed();
      const target = await requireTarget();
      const scope = () => actionScope(target);
      let editor = visible(
          scope().querySelectorAll('textarea[placeholder="发布你的评论"]'));
      if (!editor) {
        clickAction(target, '评论');
        editor = await waitFor(
            () => visible(
                scope().querySelectorAll(
                    'textarea[placeholder="发布你的评论"]')),
            '微博评论编辑器未加载。');
      }
      const content = clean(input.text);
      await setNativeValue(editor, content);
      const button = await waitFor(
          () => visible(Array.from(scope().querySelectorAll('button'))
                            .filter(
                                (node) => clean(node.textContent) === '评论' &&
                                    !node.disabled &&
                                    !node.classList.contains('disabled'))),
          '找不到可用的“评论”按钮。');
      button.click();
      await waitFor(
          () => editor?.value === '' || !document.contains(editor) ? editor :
                                                                     null,
          '回复后评论编辑器没有清空。');
      return {
        data: {postId: postInfo(target).id, replied: true, text: content}
      };
    }
  }
}


// 引用微博 — write. 带文字转发目标微博；必须传 confirm=true。
async function weibo_quote_post(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes('weibo_quote_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'text' in rawInput &&
        'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'text', 'confirm'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^[A-Za-z0-9]{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$')
              .test(rawInput['postUrl']))) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 5000)) &&
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const currentPost =
        currentPath.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const requestedPostId = () => clean(input.postId) ||
        postPath(input.postUrl)?.id || currentPost?.[2] || '';
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const findTarget = async (allowFirst = false) => {
      const id = requestedPostId();
      const find = () =>
          articleNodes().find((article) => postInfo(article).id === id) || null;
      if (id) {
        let target = find();
        if (target)
          return target;
        if (isHome) {
          window.scrollTo({top: 0, behavior: 'auto'});
          await pause(180);
          for (let index = 0; index < 20 && !target; index += 1) {
            target = find();
            if (target)
              break;
            window.scrollBy({
              top: Math.max(640, window.innerHeight * 0.82),
              behavior: 'auto'
            });
            await pause(350);
          }
        }
        return target;
      }
      if (currentPost || allowFirst)
        return articleNodes()[0] || null;
      return null;
    };
    const requireTarget = async () => {
      const target = await findTarget(false);
      if (target)
        return target;
      if (isHome && !requestedPostId())
        throw new Error(
            'VALIDATION_ERROR: 在微博首页操作帖子时必须传 postId 或完整 postUrl。');
      throw new Error(
          'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标微博。');
    };
    const clickAction = (article, title) => {
      const icon = article.querySelector(`[title="${title}"]`);
      const control = icon?.closest('[class*="_item_"]') || icon?.parentElement;
      if (!control)
        throw new Error(`SITE_CHANGED: 目标微博没有“${title}”操作。`);
      control.click();
    };
    const setNativeValue = async (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 微博输入控件不支持标准 value setter。');
      element.focus();
      setter.call(element, value);
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
      await pause(100);
      if (element.value !== value)
        throw new Error('VALIDATION_ERROR: 微博编辑器拒绝了输入内容。');
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
        throw new Error('VALIDATION_ERROR: 该微博写操作必须传 confirm=true。');
    };
    {
      requireConfirmed();
      const originalUrl = location.href;
      const target = await requireTarget();
      clickAction(target, '转发');
      const editor = await waitFor(
          () => visible(document.querySelectorAll(
              'textarea[placeholder="说说分享心得"]')),
          '微博转发编辑器未加载。');
      const content = 'quote_post' === 'quote_post' ?
          clean(input.text) :
          clean(input.text) || '转发微博';
      await setNativeValue(editor, content);
      const button = await waitFor(
          () => visible(Array.from(document.querySelectorAll('button'))
                            .filter(
                                (node) => clean(node.textContent) === '转发' &&
                                    !node.disabled &&
                                    !node.classList.contains('disabled'))),
          '找不到可用的“转发”按钮。');
      button.click();
      await waitFor(
          () =>
              editor.value === '' || !document.contains(editor) ? editor : null,
          '转发后编辑器没有关闭。');
      if (location.href !== originalUrl)
        history.replaceState(history.state, '', originalUrl);
      return {
        data: {
          postId: postInfo(target).id,
          reposted: true,
          quoted: 'quote_post' === 'quote_post',
          text: content
        }
      };
    }
  }
}


// 转发微博 — write. 转发目标微博；可选自定义转发文字，必须传 confirm=true。
async function weibo_repost_post(rawInput = {}) {
  const route = (url) => {
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/' || path === '/mygroups') {
      return {
        type: 'home',
        identity: path === '/mygroups' ?
            `home:${url.searchParams.get('gid') || 'groups'}` :
            'home:all'
      };
    }
    const post = path.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    if (post)
      return {type: 'post', identity: `post:${post[1]}:${post[2]}`};
    const profile = path.match(/^\/u\/(\d{1,20})$/);
    if (profile)
      return {type: 'profile', identity: `profile:${profile[1]}`};
    return null;
  };
  const homeTools = [
    'weibo_get_home_feed', 'weibo_get_post_with_comments', 'weibo_publish_post',
    'weibo_like_post', 'weibo_reply_post', 'weibo_quote_post',
    'weibo_repost_post'
  ];
  const postTools = [
    'weibo_get_post_with_comments', 'weibo_like_post', 'weibo_reply_post',
    'weibo_quote_post', 'weibo_repost_post'
  ];
  const profileTools = ['weibo_get_profile_latest_posts'];
  const weiboAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        (url.hostname === 'weibo.com' || url.hostname === 'www.weibo.com') &&
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
  if (!weiboAdapter.matches(routeUrl) ||
      !weiboAdapter.toolNames(routeUrl).includes('weibo_repost_post'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 微博 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['postId', 'postUrl', 'text', 'confirm'].includes(key)) &&
        (!('postId' in rawInput) ||
         (typeof rawInput['postId'] === 'string' &&
          new RegExp('^[A-Za-z0-9]{1,32}$').test(rawInput['postId']))) &&
        (!('postUrl' in rawInput) ||
         (typeof rawInput['postUrl'] === 'string' &&
          [...rawInput['postUrl']].length >= 1 &&
          [...rawInput['postUrl']].length <= 2048 &&
          new RegExp(
              '^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$')
              .test(rawInput['postUrl']))) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 5000)) &&
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
                                 .replace(/\n{3,}/g, '\n\n')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (nodes) =>
        Array.from(nodes).find((node) => node.getClientRects().length > 0) ||
        null;
    const currentPath = location.pathname.replace(/\/+$/, '') || '/';
    const isHome = currentPath === '/' || currentPath === '/mygroups';
    const currentPost =
        currentPath.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})$/);
    const postPath = (value) => {
      const raw = clean(value);
      if (!raw)
        return null;
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== 'https:' ||
            !['weibo.com', 'www.weibo.com'].includes(parsed.hostname))
          return null;
        const match =
            parsed.pathname.match(/^\/(\d{1,20})\/([A-Za-z0-9]{1,32})\/?$/);
        return match ? {
          uid: match[1],
          id: match[2],
          url: `https://weibo.com/${match[1]}/${match[2]}`
        } :
                       null;
      } catch {
        return null;
      }
    };
    const requestedPostId = () => clean(input.postId) ||
        postPath(input.postUrl)?.id || currentPost?.[2] || '';
    const articleNodes = () =>
        Array.from(document.querySelectorAll('main article'));
    const postInfo = (article) => {
      for (const link of article.querySelectorAll('header a[href]')) {
        const info = postPath(link.getAttribute('href'));
        if (info)
          return {...info, publishedAt: clean(link.textContent) || null};
      }
      return {uid: '', id: '', url: '', publishedAt: null};
    };
    const findTarget = async (allowFirst = false) => {
      const id = requestedPostId();
      const find = () =>
          articleNodes().find((article) => postInfo(article).id === id) || null;
      if (id) {
        let target = find();
        if (target)
          return target;
        if (isHome) {
          window.scrollTo({top: 0, behavior: 'auto'});
          await pause(180);
          for (let index = 0; index < 20 && !target; index += 1) {
            target = find();
            if (target)
              break;
            window.scrollBy({
              top: Math.max(640, window.innerHeight * 0.82),
              behavior: 'auto'
            });
            await pause(350);
          }
        }
        return target;
      }
      if (currentPost || allowFirst)
        return articleNodes()[0] || null;
      return null;
    };
    const requireTarget = async () => {
      const target = await findTarget(false);
      if (target)
        return target;
      if (isHome && !requestedPostId())
        throw new Error(
            'VALIDATION_ERROR: 在微博首页操作帖子时必须传 postId 或完整 postUrl。');
      throw new Error(
          'CONTENT_UNAVAILABLE: 当前页面已加载内容中找不到目标微博。');
    };
    const clickAction = (article, title) => {
      const icon = article.querySelector(`[title="${title}"]`);
      const control = icon?.closest('[class*="_item_"]') || icon?.parentElement;
      if (!control)
        throw new Error(`SITE_CHANGED: 目标微博没有“${title}”操作。`);
      control.click();
    };
    const setNativeValue = async (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 微博输入控件不支持标准 value setter。');
      element.focus();
      setter.call(element, value);
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
      await pause(100);
      if (element.value !== value)
        throw new Error('VALIDATION_ERROR: 微博编辑器拒绝了输入内容。');
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
        throw new Error('VALIDATION_ERROR: 该微博写操作必须传 confirm=true。');
    };
    {
      requireConfirmed();
      const originalUrl = location.href;
      const target = await requireTarget();
      clickAction(target, '转发');
      const editor = await waitFor(
          () => visible(document.querySelectorAll(
              'textarea[placeholder="说说分享心得"]')),
          '微博转发编辑器未加载。');
      const content = 'repost_post' === 'quote_post' ?
          clean(input.text) :
          clean(input.text) || '转发微博';
      await setNativeValue(editor, content);
      const button = await waitFor(
          () => visible(Array.from(document.querySelectorAll('button'))
                            .filter(
                                (node) => clean(node.textContent) === '转发' &&
                                    !node.disabled &&
                                    !node.classList.contains('disabled'))),
          '找不到可用的“转发”按钮。');
      button.click();
      await waitFor(
          () =>
              editor.value === '' || !document.contains(editor) ? editor : null,
          '转发后编辑器没有关闭。');
      if (location.href !== originalUrl)
        history.replaceState(history.state, '', originalUrl);
      return {
        data: {
          postId: postInfo(target).id,
          reposted: true,
          quoted: 'repost_post' === 'quote_post',
          text: content
        }
      };
    }
  }
}
