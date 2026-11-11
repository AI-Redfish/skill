// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取搜索结果商品 — read.
// 滚动并读取当前淘宝搜索结果页的全部商品卡片，返回标题、价格、销量、店铺、地区、标签、图片和规范商品链接。
async function taobao_get_search_results(rawInput = {}) {
  const route = (url) => {
    if (url.hostname === 's.taobao.com' &&
        url.pathname.replace(/\/+$/, '') === '/search') {
      const query = url.searchParams.get('q') || '';
      const page = url.searchParams.get('page') || '1';
      const tab = url.searchParams.get('tab') || 'all';
      return {type: 'search', identity: `search:${query}:${page}:${tab}`};
    }
    if ((url.hostname === 'item.taobao.com' ||
         url.hostname === 'detail.tmall.com') &&
        url.pathname === '/item.htm') {
      const itemId = url.searchParams.get('id');
      if (/^\d{5,32}$/.test(itemId || ''))
        return {type: 'item', identity: `item:${itemId}`};
    }
    return null;
  };
  const taobaoAdapter = {
    matches: (url) => url.protocol === 'https:' && route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['taobao_get_search_results'] :
        ['taobao_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!taobaoAdapter.matches(routeUrl) ||
      !taobaoAdapter.toolNames(routeUrl).includes('taobao_get_search_results'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 淘宝 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['maxItems', 'maxScrolls'].includes(key)) &&
        (!('maxItems' in rawInput) ||
         (Number.isInteger(rawInput['maxItems']) && rawInput['maxItems'] >= 1 &&
          rawInput['maxItems'] <= 200)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 50))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
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
    const unique = (values) => [...new Set(values.map(clean).filter(Boolean))];
    const publicAssetUrl = (value) => {
      const resolved = absolute(value);
      return /^https:\/\//.test(resolved) ? resolved : '';
    };
    const countValue = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([万萬亿億kmb])?/i);
      if (!match)
        return null;
      const base = Number(match[1]);
      if (!Number.isFinite(base))
        return null;
      const multipliers =
          {k: 1e3, m: 1e6, b: 1e9, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8};
      return Math.round(
          base * (multipliers[(match[2] || '').toLowerCase()] || 1));
    };
    const priceValue = (value) => {
      const match = clean(value).replace(/,/g, '').match(/[\d]+(?:\.[\d]+)?/);
      const parsed = Number(match?.[0]);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const itemIdFrom = (node) => {
      const html = node;
      const candidates =
          [html.dataset.spmActId, html.dataset.nid, html.dataset.itemId];
      const links = node.matches('a[href]') ?
          [node] :
          Array.from(node.querySelectorAll('a[href]'));
      for (const link of links) {
        try {
          candidates.push(
              new URL(link.href, location.href).searchParams.get('id') ||
              undefined);
        } catch { /* Try another link. */
        }
      }
      return candidates.map(clean).find((value) => /^\d{5,32}$/.test(value)) ||
          '';
    };
    const searchCards = () => {
      const selectors = [
        'a[class*="doubleCardWrapper"][href]', '#mainsrp-itemlist .item',
        '[data-spm-act-id][class*="Card"]', '[data-nid].item'
      ];
      const nodes = selectors.flatMap(
          (selector) => Array.from(document.querySelectorAll(selector)));
      return [...new Set(nodes)].filter((node) => itemIdFrom(node));
    };
    const cardText = (card, selectors) => {
      for (const selector of selectors) {
        const value = clean(card.querySelector(selector)?.textContent);
        if (value)
          return value;
      }
      return '';
    };
    const cardList = (card, selectors) => unique(selectors.flatMap(
        (selector) => Array.from(card.querySelectorAll(selector))
                          .map((node) => node.textContent)));
    const searchItem = (card, observedIndex) => {
      const itemId = itemIdFrom(card);
      const rawHref = card.matches('a[href]') ?
          card.href :
          card.querySelector('a[href]')?.href || '';
      let source = 'taobao';
      try {
        source =
            new URL(rawHref, location.href).hostname === 'detail.tmall.com' ?
            'tmall' :
            'taobao';
      } catch { /* Keep Taobao fallback. */
      }
      const url = `${
          source === 'tmall' ? 'https://detail.tmall.com' :
                               'https://item.taobao.com'}/item.htm?id=${
          encodeURIComponent(itemId)}`;
      const priceText = cardText(card, [
        '[class*="innerPriceWrapper--"]', '[class*="priceInt--"]',
        '.price strong', '.price'
      ]);
      const image = card.querySelector('[class*="mainImg--"], img');
      const position =
          Number(card.dataset.spm || card.getAttribute('data-index'));
      const locationParts =
          cardList(card, ['[class*="procity--"]', '.location']);
      return {
        itemId,
        position: Number.isFinite(position) && position > 0 ? position :
                                                              observedIndex + 1,
        source,
        url,
        title:
            cardText(card, ['[class*="title--"]', '.row-2.title', '.title']) ||
            clean(card.textContent).slice(0, 300),
        imageUrl: publicAssetUrl(image?.currentSrc || image?.src) || null,
        price: {
          currency: 'CNY',
          value: priceValue(priceText),
          text: priceText || null,
          qualifier: cardText(card, ['[class*="priceDesc--"]']) || null
        },
        salesText:
            cardText(
                card, ['[class*="realSales--"]', '.deal-cnt', '.sale-num']) ||
            null,
        salesCount: countValue(cardText(
            card, ['[class*="realSales--"]', '.deal-cnt', '.sale-num'])),
        location: locationParts.join(' ') || null,
        shop: {
          name: cardText(
                    card,
                    ['[class*="shopNameText--"]', '.shopname', '.shop a']) ||
              null,
          badges: cardList(card, ['[class*="shopTagWrapper--"]'])
        },
        attributes: cardList(
            card,
            ['[class*="abstractInnerWrapper--"]', '[class*="descBox--"]']),
        promotions: cardList(
            card,
            [
              '[class*="secondKillInfoWrapper--"]', '[class*="coupon"]',
              '[class*="subIconWrapper--"]'
            ]),
        ranking: cardText(card, ['[class*="rankTitleWrapper--"]']) || null,
        sponsored: /(?:m?click\.simba\.taobao\.com)/.test(rawHref),
        rawText: clean(card.textContent).slice(0, 2000)
      };
    };
    {
      const maxItems =
          Math.min(200, Math.max(1, Number(input.maxItems ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const originalY = window.scrollY;
      const collected = new Map();
      let scrolls = 0;
      let idle = 0;
      const collect = () => {
        const before = collected.size;
        for (const card of searchCards()) {
          const item = searchItem(card, collected.size);
          if (item.itemId && !collected.has(item.itemId))
            collected.set(item.itemId, item);
        }
        return collected.size - before;
      };
      collect();
      while (collected.size < maxItems && scrolls < maxScrolls && idle < 3) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(700, window.innerHeight * 0.8), behavior: 'auto'});
        await pause(400);
        const added = collect();
        scrolls += 1;
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 12;
        idle = added === 0 &&
                (atEnd ||
                 beforeHeight === document.documentElement.scrollHeight) ?
            idle + 1 :
            0;
      }
      if (scrolls) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      const all = [...collected.values()].sort(
          (left, right) => left.position - right.position);
      const items = all.slice(0, maxItems);
      const pageState = win.__last_search_params || {};
      const page = Number(
          pageState.page ?? new URL(location.href).searchParams.get('page') ??
          1);
      const stopReason = all.length >= maxItems ? 'max_items' :
          maxScrolls === 0 || (scrolls >= maxScrolls && idle < 3) ?
                                                  'max_scrolls' :
                                                  'page_end';
      const truncated = stopReason !== 'page_end';
      return {
        data: {
          query: clean(decodeURIComponent(
              String(
                  pageState.q || new URL(location.href).searchParams.get('q') ||
                  '')
                  .replace(/\+/g, ' '))),
          page: Number.isFinite(page) ? page : 1,
          tab: clean(
              pageState.tab || new URL(location.href).searchParams.get('tab') ||
              'all'),
          sort: clean(pageState.sort) || null,
          pageSize: Number(pageState.pageSize || pageState.n) || null,
          totalResults: Number(pageState.totalResults) || null,
          totalPages: Number(pageState.totalPage) || null,
          count: items.length,
          observedCount: all.length,
          scrolls,
          complete: !truncated,
          truncated,
          stopReason,
          items
        },
        warnings: [
          '结果只覆盖当前搜索结果页；不会自动翻到下一页。',
          ...(pageState.pageSize && all.length < Number(pageState.pageSize) &&
                      !truncated ?
                  [`页面声明每页 ${pageState.pageSize} 个结果，实际找到 ${
                      all.length} 个可识别商品卡片。`] :
                  [])
        ]
      };
    }
  }
}


// 读取商品完整信息 — read.
// 读取当前淘宝或天猫商品的名称、价格、销量、店铺、参数、规格、库存、优惠、保障、配送、媒体、图文详情和指定数量的评价。
async function taobao_get_product_details(rawInput = {}) {
  const route = (url) => {
    if (url.hostname === 's.taobao.com' &&
        url.pathname.replace(/\/+$/, '') === '/search') {
      const query = url.searchParams.get('q') || '';
      const page = url.searchParams.get('page') || '1';
      const tab = url.searchParams.get('tab') || 'all';
      return {type: 'search', identity: `search:${query}:${page}:${tab}`};
    }
    if ((url.hostname === 'item.taobao.com' ||
         url.hostname === 'detail.tmall.com') &&
        url.pathname === '/item.htm') {
      const itemId = url.searchParams.get('id');
      if (/^\d{5,32}$/.test(itemId || ''))
        return {type: 'item', identity: `item:${itemId}`};
    }
    return null;
  };
  const taobaoAdapter = {
    matches: (url) => url.protocol === 'https:' && route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['taobao_get_search_results'] :
        ['taobao_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!taobaoAdapter.matches(routeUrl) ||
      !taobaoAdapter.toolNames(routeUrl).includes('taobao_get_product_details'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 淘宝 page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['reviewLimit', 'maxReviewScrolls', 'includeDetailImages',
                    'maxDetailImages']
                       .includes(key)) &&
        (!('reviewLimit' in rawInput) ||
         (Number.isInteger(rawInput['reviewLimit']) &&
          rawInput['reviewLimit'] >= 1 && rawInput['reviewLimit'] <= 100)) &&
        (!('maxReviewScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxReviewScrolls']) &&
          rawInput['maxReviewScrolls'] >= 0 &&
          rawInput['maxReviewScrolls'] <= 30)) &&
        (!('includeDetailImages' in rawInput) ||
         (typeof rawInput['includeDetailImages'] === 'boolean')) &&
        (!('maxDetailImages' in rawInput) ||
         (Number.isInteger(rawInput['maxDetailImages']) &&
          rawInput['maxDetailImages'] >= 1 &&
          rawInput['maxDetailImages'] <= 200))))
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
    const unique = (values) => [...new Set(values.map(clean).filter(Boolean))];
    const publicAssetUrl = (value) => {
      const resolved = absolute(value);
      return /^https:\/\//.test(resolved) ? resolved : '';
    };
    const countValue = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([万萬亿億kmb])?/i);
      if (!match)
        return null;
      const base = Number(match[1]);
      if (!Number.isFinite(base))
        return null;
      const multipliers =
          {k: 1e3, m: 1e6, b: 1e9, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8};
      return Math.round(
          base * (multipliers[(match[2] || '').toLowerCase()] || 1));
    };
    const priceValue = (value) => {
      const match = clean(value).replace(/,/g, '').match(/[\d]+(?:\.[\d]+)?/);
      const parsed = Number(match?.[0]);
      return Number.isFinite(parsed) ? parsed : null;
    };
    const cardText = (card, selectors) => {
      for (const selector of selectors) {
        const value = clean(card.querySelector(selector)?.textContent);
        if (value)
          return value;
      }
      return '';
    };
    {
      const originalY = window.scrollY;
      const detailModuleReady = () => Boolean(
          document.querySelector('[class*="tabDetailWrap--"], .desc-root') ||
          Array
              .from(document.querySelectorAll(
                  'button,a,[role="button"],div,span'))
              .some((node) => clean(node.textContent) === '查看全部评价'));
      let detailModuleWaits = 0;
      while (!detailModuleReady() && detailModuleWaits < 8 &&
             !/jsdom/i.test(navigator.userAgent)) {
        await pause(500);
        detailModuleWaits += 1;
      }
      if (input.includeDetailImages !== false) {
        const detailLandmark =
            Array.from(document.querySelectorAll('p,div,span'))
                .find((node) => clean(node.textContent) === '图文详情');
        detailLandmark?.scrollIntoView?.({block: 'center', behavior: 'auto'});
        if (detailLandmark)
          await pause(500);
        for (let index = 0; index < 8; index += 1) {
          const before = window.scrollY;
          window.scrollBy(
              {top: Math.max(700, window.innerHeight * 0.8), behavior: 'auto'});
          await pause(180);
          if (window.scrollY === before ||
              window.scrollY + window.innerHeight >=
                  document.documentElement.scrollHeight - 12)
            break;
        }
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(80);
      }
      const itemId = clean(new URL(location.href).searchParams.get('id'));
      const home = win.__ICE_APP_CONTEXT__?.loaderData?.home?.data;
      const res = home?.res || {};
      const item = res.item || {};
      const seller = res.seller || {};
      const components = res.componentsVO || {};
      const priceVO = components.priceVO || {};
      const skuBase = res.skuBase || {};
      const skuInfo = res.skuCore?.sku2info || {};
      const extensions = Array.isArray(components.extensionInfoVO?.infos) ?
          components.extensionInfoVO.infos :
          [];
      const reviewLimit =
          Math.min(100, Math.max(1, Number(input.reviewLimit ?? 20)));
      const maxReviewScrolls =
          Math.min(30, Math.max(0, Number(input.maxReviewScrolls ?? 10)));
      const maxDetailImages =
          Math.min(200, Math.max(1, Number(input.maxDetailImages ?? 100)));
      const structuredReview = (entry) => ({
        id: clean(entry?.feedId || entry?.id) || null,
        author:
            clean(
                entry?.userName || entry?.reduceUserNick || entry?.userNick) ||
            null,
        publishedAt: clean(
                         entry?.dateTime || entry?.feedbackDate ||
                         entry?.createTime || entry?.createTimeInterval) ||
            null,
        sku: clean(entry?.skuInfo).replace(/^已购\s*/, '') ||
            clean(entry?.skuValueStr) ||
            Object.entries(entry?.skuMap || {})
                .map(([name, value]) => `${clean(name)}：${clean(value)}`)
                .join('；') ||
            null,
        content: clean(entry?.content || entry?.feedback).slice(0, 10000),
        sellerReply:
            clean(
                entry?.reply?.content || entry?.sellerReply || entry?.reply) ||
            null,
        media: [
          ...(Array.isArray(entry?.media) ? entry.media : []),
          ...(Array.isArray(entry?.feedPicList) ? entry.feedPicList : []),
          ...(Array.isArray(entry?.rateResourceList) ? entry.rateResourceList :
                                                       [])
        ]
                   .flatMap((media) => {
                     const imageUrl = publicAssetUrl(
                         media?.imageUrl || media?.thumbnail || media?.url ||
                         media?.picUrl);
                     const videoUrl = publicAssetUrl(
                         media?.videoUrl || media?.videoURL || media?.playUrl);
                     return [{
                       type:
                           clean(media?.type) || (videoUrl ? 'video' : 'image'),
                       imageUrl: imageUrl || null,
                       videoUrl: videoUrl || null
                     }];
                   })
                   .filter((media) => media.imageUrl || media.videoUrl)
      });
      const reviews = new Map();
      const addReview = (review) => {
        const key = review.id ||
            `${review.author}|${review.publishedAt}|${review.content}`;
        if (review.content && !reviews.has(key))
          reviews.set(key, review);
      };
      const previewReviews = Array.isArray(components.rateVO?.group?.items) ?
          components.rateVO.group.items :
          [];
      previewReviews.map(structuredReview).forEach(addReview);
      let reviewApiPages = 0;
      let reviewApiFailed = false;
      let reviewApiHasNext = null;
      const mtopRequest = win.lib?.mtop?.request;
      let detailApiFailed = false;
      let detailApiComponents = [];
      if (typeof mtopRequest === 'function' && itemId) {
        try {
          const response = await mtopRequest.call(win.lib.mtop, {
            api: 'mtop.taobao.detail.getdesc',
            v: '7.0',
            isSec: '0',
            ecode: '0',
            AntiFlood: true,
            AntiCreep: true,
            timeout: 10000,
            dataType: 'jsonp',
            jsonpIncPrefix: 'pcdetaildesc',
            ttid: `2022@${
                location.hostname === 'detail.tmall.com' ?
                    'tmall' :
                    'taobao'}_litepc_9.17.0`,
            data: {
              id: itemId,
              sku_properties: clean(
                  new URL(location.href).searchParams.get('sku_properties')),
              detail_v: '3.3.0',
              preferWireless: 'true'
            }
          });
          const componentData = response?.data?.components?.componentData ||
              response?.components?.componentData || {};
          detailApiComponents = Object.values(componentData);
        } catch {
          detailApiFailed = true;
        }
      }
      if (reviews.size < reviewLimit && typeof mtopRequest === 'function' &&
          itemId) {
        const pageSize = 20;
        const maxPages = Math.ceil(reviewLimit / pageSize);
        for (let pageNo = 1; pageNo <= maxPages && reviews.size < reviewLimit;
             pageNo += 1) {
          try {
            const response = await mtopRequest.call(win.lib.mtop, {
              api: 'mtop.taobao.rate.detaillist.get',
              v: '6.0',
              isSec: '0',
              ecode: '1',
              type: 'get',
              dataType: 'jsonp',
              timeout: 20000,
              jsonpIncPrefix: 'pcdetail',
              data: {
                showTrueCount: false,
                auctionNumId: itemId,
                pageNo,
                pageSize,
                orderType: '',
                searchImpr: '-8',
                expression: '',
                skuVids: '',
                rateSrc: 'pc_rate_list',
                rateType: ''
              }
            });
            const responseData = response?.data || response || {};
            const pageReviews = Array.isArray(responseData.rateList) ?
                responseData.rateList :
                [];
            pageReviews.map(structuredReview).forEach(addReview);
            reviewApiPages += 1;
            reviewApiHasNext = responseData.hasNext === true ||
                responseData.hasNext === 'true';
            if (!pageReviews.length || !reviewApiHasNext)
              break;
          } catch {
            reviewApiFailed = true;
            break;
          }
        }
      }
      let reviewDrawerOpened = false;
      let reviewScrolls = 0;
      const reviewDrawer = () =>
          Array
              .from(document.querySelectorAll(
                  '[class*="Drawer--"], [class*="drawer--"], [role="dialog"]'))
              .find(
                  (node) => /用户评价|全部评价/.test(
                                clean(node.textContent)) ||
                      Boolean(node.querySelector('[class*="Comment--"]'))) ||
          null;
      const domReviews = () => {
        const drawer = reviewDrawer();
        const candidates =
            Array
                .from((drawer || document)
                          .querySelectorAll('[class*="Comment--"]'))
                .filter(
                    (node) => Boolean(drawer) ||
                        !String(node.className).includes('changeCommentStyle'));
        return candidates
            .map((node) => {
              const header = clean(
                  node.querySelector('[class*="userInfo--"]')?.textContent);
              const date =
                  header
                      .match(/\d{4}(?:年|-|\/)\d{1,2}(?:月|-|\/)\d{1,2}日?/)
                      ?.[0] ||
                  null;
              const author = date ?
                  clean(header.slice(0, header.indexOf(date))) :
                  header || null;
              const sku =
                  clean(header.match(/已购[:：]?\s*(.*)$/)?.[1]) || null;
              const contentNode =
                  Array.from(node.querySelectorAll('[class*="content--"]'))
                      .find(
                          (entry) =>
                              String(entry.className)
                                  .split(/\s+/)
                                  .some(
                                      (name) => name.startsWith('content--')));
              const content = clean(contentNode?.textContent).slice(0, 10000);
              const sellerReply =
                  clean(node.querySelector('[class*="reply--"]')?.textContent)
                      .replace(/^商家回复[:：]?\s*/, '') ||
                  null;
              const media = Array.from(node.querySelectorAll('img[src]'))
                                .map((image) => ({
                                       type: 'image',
                                       imageUrl: publicAssetUrl(
                                           image.currentSrc || image.src),
                                       videoUrl: null
                                     }))
                                .filter((entry) => entry.imageUrl);
              return {
                id: null,
                author,
                publishedAt: date,
                sku,
                content,
                sellerReply,
                media
              };
            })
            .filter((review) => review.content);
      };
      if (reviews.size < reviewLimit) {
        const openCandidates =
            Array
                .from(document.querySelectorAll(
                    'button,a,[role="button"],div,span'))
                .filter((node) => clean(node.textContent) === '查看全部评价')
                .sort((left, right) => {
                  const visibility = Number(right.getClientRects().length > 0) -
                      Number(left.getClientRects().length > 0);
                  return visibility ||
                      left.children.length - right.children.length;
                });
        for (const openAll of openCandidates.slice(0, 4)) {
          try {
            openAll.scrollIntoView?.({block: 'center', behavior: 'auto'});
            await pause(80);
            openAll.click();
            for (let attempt = 0; attempt < 20 && !reviewDrawer(); attempt += 1)
              await pause(100);
            reviewDrawerOpened = Boolean(reviewDrawer());
            if (reviewDrawerOpened)
              break;
          } catch { /* Try another matching control, then keep preview reviews.
                     */
          }
        }
        domReviews().forEach(addReview);
        const drawer = reviewDrawer();
        const scrollCandidates =
            drawer ? [drawer, ...Array.from(drawer.querySelectorAll('*'))] : [];
        const scroller =
            scrollCandidates
                .filter((node) => node.scrollHeight > node.clientHeight + 20)
                .sort(
                    (left, right) => right.scrollHeight - left.scrollHeight)[0];
        let idle = 0;
        while (reviews.size < reviewLimit && scroller &&
               reviewScrolls < maxReviewScrolls && idle < 3) {
          const before = reviews.size;
          scroller.scrollTop = Math.min(
              scroller.scrollHeight,
              scroller.scrollTop + Math.max(500, scroller.clientHeight * 0.8));
          scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
          await pause(400);
          domReviews().forEach(addReview);
          reviewScrolls += 1;
          idle = reviews.size === before ? idle + 1 : 0;
        }
      }
      const reviewItems = [...reviews.values()].slice(0, reviewLimit);
      if (reviewDrawerOpened) {
        const drawer = reviewDrawer();
        const close = drawer &&
            Array
                .from(
                    drawer.querySelectorAll('button,[role="button"],div,span'))
                .find((node) => {
                  const label = clean(
                      node.getAttribute('aria-label') ||
                      node.getAttribute('title') || node.textContent);
                  return /^(关闭|close)$/i.test(label) &&
                      node.getClientRects().length > 0;
                });
        close?.click();
        await pause(80);
      }
      const parameterEntries =
          [
            ...(Array.isArray(
                    res.plusViewVO?.industryParamVO?.enhanceParamList) ?
                    res.plusViewVO.industryParamVO.enhanceParamList :
                    []),
            ...(Array.isArray(res.plusViewVO?.industryParamVO?.basicParamList) ?
                    res.plusViewVO.industryParamVO.basicParamList :
                    [])
          ]
              .map((entry) => ({
                     name: clean(entry?.propertyName),
                     value: clean(entry?.valueName)
                   }))
              .filter((entry) => entry.name || entry.value);
      if (!parameterEntries.length) {
        for (const group of extensions.filter(
                 (entry) => entry?.type === 'BASE_PROPS')) {
          for (const entry of Array.isArray(group.items) ? group.items : [])
            parameterEntries.push({
              name: clean(entry?.title),
              value: unique(entry?.text || []).join(' ')
            });
        }
      }
      if (!parameterEntries.length) {
        const domEntries = Array.from(document.querySelectorAll(
            '.paramsInfoArea [class*="ParamsInfo"], .paramsInfoArea [class*="paramItem"], .paramsInfoArea li'));
        for (const entry of domEntries) {
          const children = Array.from(entry.children)
                               .map((node) => clean(node.textContent))
                               .filter(Boolean);
          if (children.length >= 2)
            parameterEntries.push({
              name: children.at(-1) || '',
              value: children.slice(0, -1).join(' ')
            });
        }
      }
      const parameters =
          [...new Map(parameterEntries.map((entry) => [entry.name, entry]))
               .values()];
      let promotionGroups =
          extensions
              .filter(
                  (entry) => ['DAILY_COUPON', 'CAN_BE_ENJOYED_AGAIN'].includes(
                      clean(entry?.type)))
              .map((group) => ({
                     title: clean(group.title),
                     type: clean(group.type),
                     items:
                         unique((Array.isArray(group.items) ? group.items : [])
                                    .flatMap((entry) => entry?.text || []))
                   }));
      if (!promotionGroups.length) {
        const domPromotions = unique(
            Array
                .from(document.querySelectorAll(
                    '[class*="couponListWrap--"], [class*="CouponItem--"], [class*="promotion"]'))
                .map((node) => node.textContent));
        if (domPromotions.length)
          promotionGroups =
              [{title: '优惠', type: 'DOM', items: domPromotions}];
      }
      const guaranteeGroups =
          extensions.filter((entry) => /^GUARANTEE/.test(clean(entry?.type)))
              .flatMap(
                  (group) => (Array.isArray(group.items) ? group.items : [])
                                 .map((entry) => ({
                                        name: clean(entry?.title) ||
                                            clean(entry?.text?.[0]),
                                        description: unique(entry?.text || [])
                                                         .join(' ')
                                                         .slice(0, 3000) ||
                                            null
                                      })))
              .filter((entry) => entry.name);
      const skuProperties =
          (Array.isArray(skuBase.props) ? skuBase.props : [
          ]).map((property) => ({
                   id: clean(property?.pid) || null,
                   name: clean(property?.name) || null,
                   values:
                       (Array.isArray(property?.values) ? property.values : [])
                           .map(
                               (value) => ({
                                 id: clean(value?.vid) || null,
                                 name: clean(value?.name),
                                 imageUrl: publicAssetUrl(value?.image) || null,
                                 selected: value?.selected === true ||
                                     value?.selected === 'true',
                                 available:
                                     !(value?.empty === true ||
                                       value?.empty === 'true'),
                                 badge: clean(value?.corner?.cornerText) || null
                               }))
                           .filter((value) => value.name)
                 }));
      const variants =
          (Array.isArray(skuBase.skus) ? skuBase.skus : [])
              .map((variant) => {
                const info = skuInfo[String(variant?.skuId)] || {};
                const price = info.subPrice || info.price || {};
                return {
                  skuId: clean(variant?.skuId),
                  propertyPath: clean(variant?.propPath),
                  price: {
                    currency: 'CNY',
                    value: priceValue(price.priceText),
                    text: clean(price.priceText) || null,
                    label: clean(price.priceTitle) || null
                  },
                  quantity: Number.isFinite(Number(info.quantity)) ?
                      Number(info.quantity) :
                      null,
                  quantityText: clean(info.quantityText) || null
                };
              })
              .filter((variant) => variant.skuId);
      const mainPrice = priceVO.extraPrice || priceVO.price ||
          skuInfo['0']?.subPrice || skuInfo['0']?.price || {};
      const originalPrice = priceVO.extraPrice ? priceVO.price : null;
      const detailApiModels =
          detailApiComponents.map((entry) => entry?.model || {})
              .filter(Boolean);
      const allDetailImageUrls = unique([
        ...detailApiModels.map(
            (model) => publicAssetUrl(model.picUrl || model.imageUrl)),
        ...Array
            .from(document.querySelectorAll(
                'img.descV8-singleImage-image, [data-name="singleImage"], [class*="descV8"] img'))
            .map((image) => publicAssetUrl(image.currentSrc || image.src))
      ]);
      const detailImageUrls = allDetailImageUrls.slice(0, maxDetailImages);
      const detailVideos =
          detailApiModels
              .map((model) => ({
                     url: publicAssetUrl(model.videoUrl || model.playUrl) ||
                         null,
                     thumbnailUrl: publicAssetUrl(
                                       model.thumbnail || model.thumbnailUrl) ||
                         null
                   }))
              .filter((video) => video.url || video.thumbnailUrl);
      const detailTexts =
          unique(detailApiModels.flatMap(
                     (model) =>
                         [model.title, model.text, model.content, model.desc,
                          model.description]))
              .filter((text) => text !== '已经到最底了')
              .slice(0, 200);
      const includedDetailImages =
          input.includeDetailImages !== false ? detailImageUrls : [];
      const title = clean(
          item.title || components.titleVO?.title?.title || meta('og:title') ||
          document.title);
      const totalReviewText = clean(components.rateVO?.totalCount) || null;
      const totalReviewCount = countValue(totalReviewText);
      const delivery = components.deliveryVO || {};
      const bodyText = clean(document.body?.innerText);
      const salesText =
          clean(components.titleVO?.salesDesc || item.vagueSellCount) ||
          clean(
              bodyText.match(/已售\s*[\d,.]+(?:万|萬|亿|億)?\+?/)?.[0]) ||
          null;
      const result = {
        itemId: clean(item.itemId || itemId),
        canonicalUrl:
            `${location.origin}/item.htm?id=${encodeURIComponent(itemId)}`,
        source: location.hostname === 'detail.tmall.com' ? 'tmall' : 'taobao',
        title,
        description: clean(meta('description') || meta('og:description'))
                         .slice(0, 5000) ||
            null,
        sales: {text: salesText, count: countValue(salesText)},
        price: {
          currency: 'CNY',
          value: priceValue(mainPrice.priceText),
          text: clean(mainPrice.priceText) ||
              cardText(document.body, ['[class*="highlightPrice--"]']) || null,
          label: clean(mainPrice.priceTitle) || null,
          qualifier: clean(mainPrice.priceDesc) || null,
          original: originalPrice ? {
            value: priceValue(originalPrice.priceText),
            text: clean(originalPrice.priceText) || null,
            label: clean(originalPrice.priceTitle) || null
          } :
                                    null
        },
        seller: {
          id: clean(seller.sellerId) || null,
          shopId: clean(seller.shopId) || null,
          name: clean(seller.shopName || seller.sellerNick) || null,
          shopUrl: publicAssetUrl(seller.pcShopUrl) || null,
          iconUrl: publicAssetUrl(seller.shopIcon) || null,
          type: clean(seller.sellerType) || null,
          ratings: (Array.isArray(seller.evaluates) ? seller.evaluates : [])
                       .map((entry) => ({
                              name: clean(entry?.title),
                              score: priceValue(entry?.score),
                              level: clean(entry?.levelText) || null
                            }))
        },
        endorsements: (Array.isArray(components.itemEndorseVO?.endorseList) ?
                           components.itemEndorseVO.endorseList :
                           [])
                          .map((entry) => ({
                                 type: clean(entry?.type),
                                 text: unique(entry?.textList || []).join(' ')
                               }))
                          .filter((entry) => entry.text),
        promotions: promotionGroups,
        guarantees:
            [...new Map(guaranteeGroups.map((entry) => [entry.name, entry]))
                 .values()],
        delivery: {
          from: clean(delivery.deliveryFromAddr) || null,
          to: clean(delivery.deliveryToAddr) || null,
          freight: clean(delivery.freight) || null,
          estimate: clean(delivery.agingDesc) || null
        },
        parameters,
        sku: {
          properties: skuProperties,
          variants,
          availability: {
            quantity: Number.isFinite(Number(skuInfo['0']?.quantity)) ?
                Number(skuInfo['0'].quantity) :
                null,
            text: clean(skuInfo['0']?.quantityText) || null,
            purchaseLimit: Number(skuInfo['0']?.limit) || null
          }
        },
        services:
            (Array.isArray(res.services?.allServices) ?
                 res.services.allServices :
                 [])
                .map((service) => ({
                       id: clean(service?.serviceId) || null,
                       name: clean(service?.name),
                       description:
                           clean(service?.extraDisplayName || service?.desc) ||
                           null,
                       options: (Array.isArray(service?.uniqueServices) ?
                                     service.uniqueServices :
                                     [])
                                    .map((option) => clean(option?.name))
                                    .filter(Boolean)
                     }))
                .filter((service) => service.name),
        media: {
          images: unique((Array.isArray(item.images) ? item.images : [])
                             .map(publicAssetUrl)),
          videos:
              (Array.isArray(item.videos) ? item.videos : [])
                  .map((video) => ({
                         id: clean(video?.videoId) || null,
                         url: publicAssetUrl(video?.url) || null,
                         thumbnailUrl:
                             publicAssetUrl(video?.videoThumbnailURL) || null
                       }))
                  .filter((video) => video.url || video.thumbnailUrl)
        },
        details: {
          url: publicAssetUrl(item.pcADescUrl) || null,
          imageCount: allDetailImageUrls.length,
          images: includedDetailImages,
          videos: detailVideos,
          texts: detailTexts,
          apiLoaded: detailApiComponents.length > 0,
          imagesIncluded: input.includeDetailImages !== false,
          truncated: input.includeDetailImages !== false &&
              allDetailImageUrls.length > maxDetailImages
        },
        reviews: {
          requested: reviewLimit,
          count: reviewItems.length,
          totalText: totalReviewText,
          totalCount: totalReviewCount,
          favorableRate:
              clean(components.rateVO?.favorableRate?.rateText) || null,
          keywords: (Array.isArray(components.rateVO?.keywords) ?
                         components.rateVO.keywords :
                         [])
                        .map((entry) => ({
                               name: clean(entry?.title),
                               countText: clean(entry?.count),
                               count: countValue(entry?.count)
                             })),
          items: reviewItems,
          apiPages: reviewApiPages,
          apiHasNext: reviewApiHasNext,
          drawerOpened: reviewDrawerOpened,
          scrolls: reviewScrolls,
          complete: reviewItems.length >= reviewLimit,
          truncated: totalReviewCount === null ?
              reviewItems.length >= reviewLimit :
              reviewItems.length < totalReviewCount
        }
      };
      return {
        data: result,
        warnings: [
          ...(home?.serverData !== 'success' ?
                  ['页面结构化商品数据未完整加载，部分字段来自当前 DOM。'] :
                  []),
          ...(!detailModuleReady() && !detailApiComponents.length ?
                  [
                    '商品详情模块尚未完成加载，图文详情、参数和扩展评价可能不完整。'
                  ] :
                  []),
          ...(detailApiFailed ?
                  ['图文详情读取接口未成功返回，已回退到当前页面内容。'] :
                  []),
          ...(reviewApiFailed ?
                  ['评价读取接口未成功返回，已回退到当前页面和评价抽屉。'] :
                  []),
          ...(reviewItems.length < reviewLimit ?
                  [`请求 ${reviewLimit} 条评价，当前页面只加载到 ${
                      reviewItems.length} 条。`] :
                  []),
          ...(input.includeDetailImages !== false &&
                      allDetailImageUrls.length > maxDetailImages ?
                  [`图文详情图片达到 ${maxDetailImages} 张上限，结果已截断。`] :
                  [])
        ]
      };
    }
  }
}
