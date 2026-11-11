// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取搜索结果商品 — read.
// 分页读取当前闲鱼搜索结果，返回商品名称、描述、价格、图片、标签、想要数、卖家和规范链接。
async function goofish_get_search_results(rawInput = {}) {
  const route = (url) => {
    if (url.protocol !== 'https:' || url.hostname !== 'www.goofish.com')
      return null;
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/search') {
      const query = url.searchParams.get('q') || '';
      return query ? {type: 'search', identity: `search:${query}`} : null;
    }
    if (path === '/item') {
      const itemId = url.searchParams.get('id');
      return /^\d{5,32}$/.test(itemId || '') ?
          {type: 'item', identity: `item:${itemId}`} :
          null;
    }
    if (path === '/publish')
      return {type: 'publish', identity: 'publish'};
    if (path === '/im') {
      const peerUserId = url.searchParams.get('peerUserId') || 'current';
      const itemId = url.searchParams.get('itemId') || 'current';
      return {type: 'messages', identity: `messages:${peerUserId}:${itemId}`};
    }
    return null;
  };
  const toolsByRoute = {
    search: ['goofish_get_search_results'],
    item: ['goofish_get_item_details'],
    publish: ['goofish_publish_item'],
    messages: ['goofish_reply_message']
  };
  const goofishAdapter = {
    matches: (url) => route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type ? [...toolsByRoute[type]] : [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!goofishAdapter.matches(routeUrl) ||
      !goofishAdapter.toolNames(routeUrl).includes(
          'goofish_get_search_results'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 闲鱼 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['maxItems', 'maxPages'].includes(key)) &&
        (!('maxItems' in rawInput) ||
         (Number.isInteger(rawInput['maxItems']) && rawInput['maxItems'] >= 1 &&
          rawInput['maxItems'] <= 1000)) &&
        (!('maxPages' in rawInput) ||
         (Number.isInteger(rawInput['maxPages']) && rawInput['maxPages'] >= 1 &&
          rawInput['maxPages'] <= 50))))
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
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const numberFrom = (value) => {
      const match = clean(value).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
      const parsed = match ? Number(match[0]) : NaN;
      return Number.isFinite(parsed) ? parsed : null;
    };
    const itemUrl = (value) => {
      try {
        const parsed = new URL(String(value || ''), location.href);
        const itemId = parsed.hostname === 'www.goofish.com' &&
                parsed.pathname === '/item' ?
            parsed.searchParams.get('id') :
            '';
        return /^\d{5,32}$/.test(itemId || '') ?
            `https://www.goofish.com/item?id=${itemId}` :
            '';
      } catch {
        return '';
      }
    };
    const itemIdFrom = (value) => {
      try {
        return new URL(value).searchParams.get('id') || '';
      } catch {
        return '';
      }
    };
    const searchItem = (anchor) => {
      const canonicalUrl = itemUrl(anchor.href);
      const id = itemIdFrom(canonicalUrl);
      const titleNode = anchor.querySelector('[class*="row1-wrap-title"]');
      const description =
          clean(titleNode?.getAttribute('title') || titleNode?.textContent);
      const row2 = anchor.querySelector('[class*="row2-wrap"]');
      const row3 = anchor.querySelector('[class*="row3-wrap-price"]');
      const priceText =
          clean(anchor.querySelector('[class*="price-wrap"]')?.textContent);
      const priceValues = clean(row3?.textContent)
                              .match(/¥\s*\d+(?:\.\d+)?/g)
                              ?.map(numberFrom)
                              .filter((entry) => entry !== null) ||
          [];
      const row2Texts =
          Array.from(row2?.querySelectorAll('[title], span, div') || [])
              .map(
                  (node) =>
                      clean(node.getAttribute('title') || node.textContent))
              .filter(Boolean);
      const priceDescription =
          clean(anchor.querySelector('[class*="price-desc"]')?.textContent);
      const sellerLabel = clean(
          anchor.querySelector('[class*="seller-text-wrap"]')
              ?.getAttribute('title') ||
          anchor.querySelector('[class*="seller-text"]')?.textContent);
      const credit = clean(
          anchor.querySelector('[class*="credit-container"] [title]')
              ?.getAttribute('title') ||
          anchor.querySelector('[class*="credit-container"]')?.textContent);
      const image = anchor.querySelector('[class*="feeds-image"], img');
      const publishedText =
          row2Texts.find(
              (entry) =>
                  /(?:前发布|内发布|刚刚发布|刚刚擦亮|天前)/
                      .test(entry)) ||
          null;
      const discountText =
          [...row2Texts, priceDescription].find(
              (entry) => /降价|购入价|折|优惠/.test(entry)) ||
          null;
      const wantMatch = priceDescription.match(/([\d,.]+)人想要/);
      const tags = [...new Set(row2Texts.filter(
          (entry) => entry !== publishedText && entry !== discountText &&
              entry.length <= 80))];
      return id && description ? {
        id,
        canonicalUrl,
        title: description,
        description,
        price: numberFrom(priceText),
        priceText: priceText || null,
        originalPrice:
            priceValues.length > 1 ? priceValues[priceValues.length - 1] : null,
        publishedText,
        discountText,
        wantCount: wantMatch ? numberFrom(wantMatch[1]) : null,
        tags,
        image: image ? {
          url: absolute(image.currentSrc || image.src) || null,
          alt: clean(image.alt) || null
        } :
                       null,
        seller: {
          label: sellerLabel || null,
          avatarUrl:
              absolute(
                  anchor.querySelector('[class*="avatar"]')?.currentSrc ||
                  anchor.querySelector('[class*="avatar"]')?.src) ||
              null,
          credit: credit || null
        }
      } :
                                 null;
    };
    {
      if (location.pathname !== '/search' ||
          !new URL(location.href).searchParams.get('q'))
        throw new Error(
            'UNSUPPORTED_ROUTE: 该操作只在带关键词的闲鱼搜索结果页可用。');
      const maxItems =
          Math.min(1000, Math.max(1, Number(input.maxItems ?? 1000)));
      const maxPages = Math.min(50, Math.max(1, Number(input.maxPages ?? 50)));
      const items = new Map();
      let pagesRead = 0;
      let stopReason = 'last_page';
      let totalPages = 1;
      let firstPage = 1;
      let lastPage = 1;
      const activePage = () =>
          Number(clean(
              document
                  .querySelector('[class*="search-pagination-page-box-active"]')
                  ?.textContent)) ||
          1;
      const collect = () => {
        for (const anchor of Array.from(
                 document.querySelectorAll('a[href*="/item?"]'))) {
          const parsed = searchItem(anchor);
          if (parsed && !items.has(parsed.id))
            items.set(parsed.id, parsed);
          if (items.size >= maxItems)
            break;
        }
      };
      for (let pageIndex = 0; pageIndex < maxPages && items.size < maxItems;
           pageIndex += 1) {
        for (let attempt = 0; attempt < 30 &&
             document.querySelectorAll('a[href*="/item?"]').length === 0;
             attempt += 1)
          await pause(200);
        const current = activePage();
        if (pagesRead === 0)
          firstPage = current;
        lastPage = current;
        const pageNumbers = Array
                                .from(document.querySelectorAll(
                                    '[class*="search-pagination-page-box"]'))
                                .map((node) => Number(clean(node.textContent)))
                                .filter(Number.isFinite);
        totalPages = Math.max(totalPages, ...pageNumbers);
        collect();
        pagesRead += 1;
        if (items.size >= maxItems) {
          stopReason = 'max_items';
          break;
        }
        const next =
            document.querySelector('[class*="search-pagination-arrow-right"]')
                ?.closest('button');
        if (!next || next.disabled || current >= totalPages) {
          stopReason = 'last_page';
          break;
        }
        if (pagesRead >= maxPages) {
          stopReason = 'max_pages';
          break;
        }
        const previousFirstId =
            itemIdFrom(document.querySelector('a[href*="/item?"]')?.href || '');
        next.click();
        let changed = false;
        for (let attempt = 0; attempt < 60; attempt += 1) {
          await pause(200);
          const nextFirstId = itemIdFrom(
              document.querySelector('a[href*="/item?"]')?.href || '');
          if (activePage() !== current && nextFirstId &&
              nextFirstId !== previousFirstId) {
            changed = true;
            break;
          }
        }
        if (!changed) {
          stopReason = 'stalled';
          break;
        }
      }
      const complete = stopReason === 'last_page';
      return {
        data: {
          query: new URL(location.href).searchParams.get('q'),
          firstPage,
          lastPage,
          totalPages,
          pagesRead,
          items: Array.from(items.values()).slice(0, maxItems),
          count: Math.min(items.size, maxItems),
          complete,
          truncated: !complete,
          stopReason
        },
        warnings: complete ?
            [] :
            [`搜索结果因 ${stopReason} 停止，未覆盖全部 ${totalPages} 页。`]
      };
    }
  }
}


// 读取商品完整信息 — read.
// 读取当前商品的价格、描述、规格、优惠/服务、图片、卖家、想要数、浏览数和指定数量的可见评论。
async function goofish_get_item_details(rawInput = {}) {
  const route = (url) => {
    if (url.protocol !== 'https:' || url.hostname !== 'www.goofish.com')
      return null;
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/search') {
      const query = url.searchParams.get('q') || '';
      return query ? {type: 'search', identity: `search:${query}`} : null;
    }
    if (path === '/item') {
      const itemId = url.searchParams.get('id');
      return /^\d{5,32}$/.test(itemId || '') ?
          {type: 'item', identity: `item:${itemId}`} :
          null;
    }
    if (path === '/publish')
      return {type: 'publish', identity: 'publish'};
    if (path === '/im') {
      const peerUserId = url.searchParams.get('peerUserId') || 'current';
      const itemId = url.searchParams.get('itemId') || 'current';
      return {type: 'messages', identity: `messages:${peerUserId}:${itemId}`};
    }
    return null;
  };
  const toolsByRoute = {
    search: ['goofish_get_search_results'],
    item: ['goofish_get_item_details'],
    publish: ['goofish_publish_item'],
    messages: ['goofish_reply_message']
  };
  const goofishAdapter = {
    matches: (url) => route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type ? [...toolsByRoute[type]] : [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!goofishAdapter.matches(routeUrl) ||
      !goofishAdapter.toolNames(routeUrl).includes('goofish_get_item_details'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 闲鱼 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => ['commentLimit'].includes(key)) &&
        (!('commentLimit' in rawInput) ||
         (Number.isInteger(rawInput['commentLimit']) &&
          rawInput['commentLimit'] >= 1 && rawInput['commentLimit'] <= 100))))
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
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const numberFrom = (value) => {
      const match = clean(value).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
      const parsed = match ? Number(match[0]) : NaN;
      return Number.isFinite(parsed) ? parsed : null;
    };
    {
      if (location.pathname !== '/item')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在闲鱼商品详情页可用。');
      const id = new URL(location.href).searchParams.get('id') || '';
      if (!/^\d{5,32}$/.test(id))
        throw new Error('VALIDATION_ERROR: 当前商品缺少有效 itemId。');
      const root = document.querySelector('[class*="item-main-container"]');
      const info = root?.querySelector('[class*="item-main-info"]') || root;
      if (!root || !info)
        throw new Error('SITE_CHANGED: 未找到闲鱼商品详情容器。');
      const description =
          clean(info.querySelector('[class*="desc"]')?.textContent);
      const priceText =
          clean(info.querySelector('[class*="price"]')?.textContent);
      const statsText =
          clean(Array.from(info.querySelectorAll('[class*="want"]'))
                    .map((node) => node.textContent)
                    .find((value) => /想要|浏览/.test(clean(value))));
      const wantMatch = statsText.match(/([\d,.]+)人想要/);
      const viewMatch = statsText.match(/([\d,.]+)浏览/);
      const attributes =
          Array.from(info.querySelectorAll('[class*="item--"]'))
              .map((node) => clean(node.textContent))
              .filter((value) => /[:：]/.test(value))
              .map((value) => {
                const separator = value.search(/[:：]/);
                return {
                  name: value.slice(0, separator).replace(/\s+/g, ''),
                  value: value.slice(separator + 1).trim()
                };
              })
              .filter(({name, value}) => name && value);
      const images =
          Array.from(root.querySelectorAll('[class*="item-main-window"] img'))
              .map((image) => ({
                     url: absolute(image.currentSrc || image.src),
                     alt: clean(image.alt) || null
                   }))
              .filter(({url}) => url && /alicdn\.com/i.test(url));
      const uniqueImages = images.filter(
          (entry, index) =>
              images.findIndex((candidate) => candidate.url === entry.url) ===
              index);
      const sellerRoot =
          document.querySelector('[class*="item-user-container"]');
      const sellerLabels = Array
                               .from(
                                   sellerRoot?.querySelectorAll(
                                       '[class*="item-user-info-label"]') ||
                                   [])
                               .map((node) => clean(node.textContent))
                               .filter(Boolean);
      const offers =
          Array.from(info.querySelectorAll('span, div'))
              .map(
                  (node) =>
                      clean(node.getAttribute('title') || node.textContent))
              .filter(
                  (value) => value && value.length <= 80 &&
                      /包邮|担保交易|验货宝|优惠|降价|购入价|自提|无需邮寄/
                          .test(value));
      const uniqueOffers = [...new Set(offers)].filter(
          (value) => !offers.some(
              (other) => other !== value && other.length < value.length &&
                  value.includes(other)));
      const commentLimit =
          Math.min(100, Math.max(1, Number(input.commentLimit ?? 20)));
      const commentContainer = document.querySelector(
          '[class*="comment-list"], [class*="commentList"], [data-testid="comment-list"]');
      const commentNodes =
          Array
              .from(
                  (commentContainer || document)
                      .querySelectorAll(
                          '[class*="comment-item"], [class*="commentItem"], [data-testid="comment"]'))
              .slice(0, commentLimit);
      const comments =
          commentNodes
              .map((node, index) => ({
                     index: index + 1,
                     author: clean(node.querySelector(
                                           '[class*="name"], [class*="user"]')
                                       ?.textContent) ||
                         null,
                     content: clean(
                         node.querySelector(
                                 '[class*="content"], [class*="text"]')
                             ?.textContent ||
                         node.textContent),
                     publishedText:
                         clean(node.querySelector('time, [class*="time"]')
                                   ?.textContent) ||
                         null
                   }))
              .filter(({content}) => content);
      const commentsAvailable = Boolean(commentContainer || comments.length);
      return {
        data: {
          id,
          canonicalUrl: `https://www.goofish.com/item?id=${id}`,
          name: description || clean(document.title).replace(/_闲鱼$/, ''),
          description,
          price: numberFrom(priceText),
          priceText: priceText ? `¥${priceText.replace(/^¥/, '')}` : null,
          stats: {
            wantCount: wantMatch ? numberFrom(wantMatch[1]) : null,
            viewCount: viewMatch ? numberFrom(viewMatch[1]) : null
          },
          offers: uniqueOffers,
          attributes,
          images: uniqueImages,
          seller: {
            name: clean(sellerRoot
                            ?.querySelector('[class*="item-user-info-nick"]')
                            ?.textContent) ||
                null,
            avatarUrl: absolute(
                           sellerRoot?.querySelector('img')?.currentSrc ||
                           sellerRoot?.querySelector('img')?.src) ||
                null,
            labels: sellerLabels,
            location: sellerLabels.find(
                          (value) => !/擦亮|来闲鱼|卖出|好评率/.test(
                              value)) ||
                null,
            credit:
                sellerLabels.find((value) => /好评率|信用/.test(value)) ||
                null
          },
          comments: {
            requestedLimit: commentLimit,
            available: commentsAvailable,
            items: comments,
            count: comments.length,
            complete: commentsAvailable ? comments.length < commentLimit : true
          }
        },
        warnings: commentsAvailable ?
            [] :
            [
              '当前闲鱼网页版商品详情页没有公开评论区，comments.available=false。'
            ]
      };
    }
  }
}


// 发布新商品 — write. 填写图片、描述、价格、发货和所在地并发布；必须传
// confirm=true。
async function goofish_publish_item(rawInput = {}) {
  const route = (url) => {
    if (url.protocol !== 'https:' || url.hostname !== 'www.goofish.com')
      return null;
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/search') {
      const query = url.searchParams.get('q') || '';
      return query ? {type: 'search', identity: `search:${query}`} : null;
    }
    if (path === '/item') {
      const itemId = url.searchParams.get('id');
      return /^\d{5,32}$/.test(itemId || '') ?
          {type: 'item', identity: `item:${itemId}`} :
          null;
    }
    if (path === '/publish')
      return {type: 'publish', identity: 'publish'};
    if (path === '/im') {
      const peerUserId = url.searchParams.get('peerUserId') || 'current';
      const itemId = url.searchParams.get('itemId') || 'current';
      return {type: 'messages', identity: `messages:${peerUserId}:${itemId}`};
    }
    return null;
  };
  const toolsByRoute = {
    search: ['goofish_get_search_results'],
    item: ['goofish_get_item_details'],
    publish: ['goofish_publish_item'],
    messages: ['goofish_reply_message']
  };
  const goofishAdapter = {
    matches: (url) => route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type ? [...toolsByRoute[type]] : [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!goofishAdapter.matches(routeUrl) ||
      !goofishAdapter.toolNames(routeUrl).includes('goofish_publish_item'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 闲鱼 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'images' in rawInput &&
        'description' in rawInput && 'price' in rawInput &&
        'location' in rawInput && 'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['images', 'description', 'price', 'originalPrice',
                    'shipping', 'shippingFee', 'pickup', 'location', 'confirm']
                       .includes(key)) &&
        (!('images' in rawInput) ||
         (Array.isArray(rawInput['images']) && rawInput['images'].length >= 1 &&
          rawInput['images'].length <= 9 &&
          rawInput['images'].every(
              item => typeof item === 'object' && item !== null &&
                  !Array.isArray(item) && 'filename' in item &&
                  'mimeType' in item && 'base64' in item &&
                  Object.keys(item).every(
                      key => ['filename', 'mimeType', 'base64'].includes(
                          key)) &&
                  (!('filename' in item) ||
                   (typeof item['filename'] === 'string' &&
                    [...item['filename']].length >= 1 &&
                    [...item['filename']].length <= 255)) &&
                  (!('mimeType' in item) ||
                   (typeof item['mimeType'] === 'string' &&
                    new RegExp('^image\\/(?:jpeg|png|webp|gif)$')
                        .test(item['mimeType']))) &&
                  (!('base64' in item) ||
                   (typeof item['base64'] === 'string' &&
                    [...item['base64']].length >= 1 &&
                    [...item['base64']].length <= 14000000))))) &&
        (!('description' in rawInput) ||
         (typeof rawInput['description'] === 'string' &&
          [...rawInput['description']].length >= 1 &&
          [...rawInput['description']].length <= 1500)) &&
        (!('price' in rawInput) ||
         (typeof rawInput['price'] === 'string' &&
          new RegExp('^(?:0|[1-9]\\d{0,7})(?:\\.\\d{1,2})?$')
              .test(rawInput['price']))) &&
        (!('originalPrice' in rawInput) ||
         (typeof rawInput['originalPrice'] === 'string' &&
          new RegExp('^(?:0|[1-9]\\d{0,7})(?:\\.\\d{1,2})?$')
              .test(rawInput['originalPrice']))) &&
        (!('shipping' in rawInput) ||
         (typeof rawInput['shipping'] === 'string' &&
          ['free', 'distance', 'fixed', 'none'].includes(
              rawInput['shipping']))) &&
        (!('shippingFee' in rawInput) ||
         (typeof rawInput['shippingFee'] === 'string' &&
          new RegExp('^(?:0|[1-9]\\d{0,5})(?:\\.\\d{1,2})?$')
              .test(rawInput['shippingFee']))) &&
        (!('pickup' in rawInput) ||
         (typeof rawInput['pickup'] === 'boolean')) &&
        (!('location' in rawInput) ||
         (typeof rawInput['location'] === 'string' &&
          [...rawInput['location']].length >= 1 &&
          [...rawInput['location']].length <= 100)) &&
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
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const visible = (element) =>
        Boolean(element && element.getClientRects().length > 0);
    const setInput = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 闲鱼输入框不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const setEditable = (element, value) => {
      element.focus();
      element.textContent = value;
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    {
      if (location.pathname !== '/publish')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在闲鱼发闲置页可用。');
      if (input.confirm !== true)
        throw new Error('VALIDATION_ERROR: 发布商品必须显式传 confirm=true。');
      const images = Array.isArray(input.images) ? input.images : [];
      const fileInput = document.querySelector('input[type="file"]');
      const editor = document.querySelector(
          '[contenteditable="true"][class*="editor"], [class*="editor"][contenteditable="true"]');
      const moneyInputs =
          Array.from(document.querySelectorAll('input[placeholder="0.00"]'));
      if (!fileInput || !editor || moneyInputs.length < 2)
        throw new Error('SITE_CHANGED: 闲鱼发布表单结构已变化。');
      const files = images.map((entry) => {
        const filename = clean(entry.filename);
        const mimeType = clean(entry.mimeType);
        const encoded = clean(entry.base64).replace(/^data:[^;]+;base64,/, '');
        const binary = atob(encoded);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1)
          bytes[index] = binary.charCodeAt(index);
        if (bytes.byteLength > 10 * 1024 * 1024)
          throw new Error(`RESULT_TOO_LARGE: 图片 ${filename} 超过 10 MiB。`);
        return new File([bytes], filename, {type: mimeType});
      });
      const transfer = new DataTransfer();
      files.forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
      fileInput.dispatchEvent(new Event('change', {bubbles: true}));
      setEditable(editor, clean(input.description));
      setInput(moneyInputs[0], clean(input.price));
      if (input.originalPrice)
        setInput(moneyInputs[1], clean(input.originalPrice));
      const shipping = clean(input.shipping || 'free');
      const shippingLabels = {
        free: '包邮',
        distance: '按距离计费',
        fixed: '一口价',
        none: '无需邮寄'
      };
      const shippingText = shippingLabels[shipping];
      const shippingControl =
          Array.from(document.querySelectorAll('label, [class*="radio"]'))
              .find((node) => clean(node.textContent) === shippingText);
      if (!shippingControl)
        throw new Error(`SITE_CHANGED: 未找到发货方式“${shippingText}”。`);
      shippingControl.click();
      await pause(100);
      if (shipping === 'fixed') {
        if (!input.shippingFee)
          throw new Error(
              'VALIDATION_ERROR: shipping=fixed 时必须传 shippingFee。');
        const freight = Array.from(
            document.querySelectorAll('input[placeholder="0.00"]'))[2];
        if (!freight)
          throw new Error('SITE_CHANGED: 未找到固定运费输入框。');
        setInput(freight, clean(input.shippingFee));
      }
      const pickupSwitch = document.querySelector(
          'button[role="switch"], button[class*="ant-switch"]');
      const pickupEnabled =
          pickupSwitch?.getAttribute('aria-checked') === 'true' ||
          pickupSwitch?.classList.contains('ant-switch-checked');
      if (pickupSwitch && pickupEnabled !== Boolean(input.pickup))
        pickupSwitch.click();
      const locationValue = clean(input.location);
      const locationTrigger =
          Array.from(document.querySelectorAll('div, span, button'))
              .find(
                  (node) => visible(node) &&
                      clean(node.textContent) === '请选择地址');
      if (locationTrigger) {
        locationTrigger.click();
        await pause(200);
        const locationInput =
            document.querySelector('input[placeholder="搜索地点"]');
        if (!locationInput)
          throw new Error('SITE_CHANGED: 未找到所在地搜索框。');
        setInput(locationInput, locationValue);
        await pause(500);
        const option =
            Array
                .from(document.querySelectorAll(
                    'li, [role="option"], [class*="location"], [class*="address"]'))
                .find(
                    (node) => visible(node) &&
                        clean(node.textContent) === locationValue);
        if (!option)
          throw new Error(
              `CONTENT_UNAVAILABLE: 所在地没有精确匹配“${locationValue}”。`);
        option.click();
        await pause(100);
      } else if (!clean(document.body.innerText).includes(locationValue)) {
        throw new Error(
            `SITE_CHANGED: 无法确认商品所在地为“${locationValue}”。`);
      }
      await pause(600);
      const publish = Array.from(document.querySelectorAll('button'))
                          .find(
                              (button) => visible(button) &&
                                  clean(button.textContent) === '发布');
      if (!publish || publish.disabled)
        throw new Error(
            'CONTENT_UNAVAILABLE: 发布按钮不可用，请检查图片、描述、价格和所在地。');
      publish.click();
      return {
        data: {
          submitted: true,
          imageCount: files.length,
          descriptionLength: clean(input.description).length,
          price: clean(input.price),
          shipping,
          pickup: Boolean(input.pickup),
          location: locationValue
        }
      };
    }
  }
}


// 回复当前会话 — write. 核对当前会话收件人后发送回复；必须传 recipient 和
// confirm=true。
async function goofish_reply_message(rawInput = {}) {
  const route = (url) => {
    if (url.protocol !== 'https:' || url.hostname !== 'www.goofish.com')
      return null;
    const path = url.pathname.replace(/\/+$/, '') || '/';
    if (path === '/search') {
      const query = url.searchParams.get('q') || '';
      return query ? {type: 'search', identity: `search:${query}`} : null;
    }
    if (path === '/item') {
      const itemId = url.searchParams.get('id');
      return /^\d{5,32}$/.test(itemId || '') ?
          {type: 'item', identity: `item:${itemId}`} :
          null;
    }
    if (path === '/publish')
      return {type: 'publish', identity: 'publish'};
    if (path === '/im') {
      const peerUserId = url.searchParams.get('peerUserId') || 'current';
      const itemId = url.searchParams.get('itemId') || 'current';
      return {type: 'messages', identity: `messages:${peerUserId}:${itemId}`};
    }
    return null;
  };
  const toolsByRoute = {
    search: ['goofish_get_search_results'],
    item: ['goofish_get_item_details'],
    publish: ['goofish_publish_item'],
    messages: ['goofish_reply_message']
  };
  const goofishAdapter = {
    matches: (url) => route(url) !== null,
    toolNames: (url) => {
      const type = route(url)?.type;
      return type ? [...toolsByRoute[type]] : [];
    }
  };
  const routeUrl = new URL(location.href);
  if (!goofishAdapter.matches(routeUrl) ||
      !goofishAdapter.toolNames(routeUrl).includes('goofish_reply_message'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 闲鱼 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) && 'recipient' in rawInput &&
        'text' in rawInput && 'confirm' in rawInput &&
        Object.keys(rawInput).every(
            key => ['recipient', 'text', 'confirm'].includes(key)) &&
        (!('recipient' in rawInput) ||
         (typeof rawInput['recipient'] === 'string' &&
          [...rawInput['recipient']].length >= 1 &&
          [...rawInput['recipient']].length <= 100)) &&
        (!('text' in rawInput) ||
         (typeof rawInput['text'] === 'string' &&
          [...rawInput['text']].length >= 1 &&
          [...rawInput['text']].length <= 2000)) &&
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
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const setInput = (element, value) => {
      const prototype = element instanceof HTMLTextAreaElement ?
          HTMLTextAreaElement.prototype :
          HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
      if (!setter)
        throw new Error('SITE_CHANGED: 闲鱼输入框不支持标准 value setter。');
      setter.call(element, value);
      element.dispatchEvent(new InputEvent(
          'input', {bubbles: true, inputType: 'insertText', data: value}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    };
    {
      if (location.pathname !== '/im')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在闲鱼消息页可用。');
      if (input.confirm !== true)
        throw new Error('VALIDATION_ERROR: 回复消息必须显式传 confirm=true。');
      const recipient = clean(input.recipient);
      const topbar = document.querySelector('[class*="message-topbar"]');
      const currentRecipient = clean(topbar?.textContent);
      if (!topbar || !currentRecipient)
        throw new Error('CONTENT_UNAVAILABLE: 当前没有打开可回复的闲鱼会话。');
      if (currentRecipient !== recipient &&
          !currentRecipient.includes(recipient))
        throw new Error(`PERMISSION_DENIED: 当前会话“${
            currentRecipient}”与 recipient“${recipient}”不一致。`);
      const textarea = document.querySelector(
          'textarea[placeholder*="请输入消息"], [class*="sendbox"] textarea');
      const sendbox = document.querySelector('[class*="sendbox"]');
      if (!textarea || !sendbox)
        throw new Error('SITE_CHANGED: 未找到闲鱼消息输入框。');
      const before =
          document
              .querySelectorAll(
                  '[class*="message-list"] > *, [class*="message-item"]')
              .length;
      setInput(textarea, clean(input.text));
      await pause(50);
      const send =
          Array.from(sendbox.querySelectorAll('button'))
              .find((button) => clean(button.textContent) === '发送') ||
          sendbox.querySelector('button:last-of-type');
      if (!send || send.disabled)
        throw new Error('CONTENT_UNAVAILABLE: 发送按钮不可用。');
      send.click();
      for (let attempt = 0; attempt < 20 && clean(textarea.value); attempt += 1)
        await pause(100);
      const after =
          document
              .querySelectorAll(
                  '[class*="message-list"] > *, [class*="message-item"]')
              .length;
      if (clean(textarea.value))
        throw new Error(
            'SITE_CHANGED: 发送后输入框未清空，无法确认消息已发送。');
      return {
        data: {
          sent: true,
          recipient: currentRecipient,
          characters: clean(input.text).length,
          messageCountChanged: after > before
        }
      };
    }
  }
}
