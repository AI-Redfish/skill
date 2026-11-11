// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取搜索结果商品 — read.
// 滚动并读取当前京东搜索结果页的商品卡片，返回名称、价格、优惠、销量、评价、店铺、标签、图片和规范商品链接。
async function jingdong_get_search_results(rawInput = {}) {
  const route = (url) => {
    if (url.protocol !== 'https:')
      return null;
    if (url.hostname === 'search.jd.com' &&
        url.pathname.replace(/\/+$/, '') === '/Search') {
      const keyword = url.searchParams.get('keyword') || '';
      const page = url.searchParams.get('page') || '1';
      return {type: 'search', identity: `search:${keyword}:${page}`};
    }
    if (url.hostname === 'item.jd.com') {
      const skuId = url.pathname.match(/^\/(\d{5,32})\.html$/)?.[1];
      if (skuId)
        return {type: 'item', identity: `item:${skuId}`};
    }
    return null;
  };
  const jingdongAdapter = {
    matches: (url) => route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['jingdong_get_search_results'] :
        ['jingdong_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!jingdongAdapter.matches(routeUrl) ||
      !jingdongAdapter.toolNames(routeUrl).includes(
          'jingdong_get_search_results'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 京东 page for this recipe.');
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
    const decodeRepeatedly = (value) => {
      let result = clean(value);
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const decoded = decodeURIComponent(result);
          if (decoded === result)
            break;
          result = decoded;
        } catch {
          break;
        }
      }
      return result;
    };
    const numericValue = (value) => {
      const match = clean(value).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
      const parsed = match ? Number(match[0]) : NaN;
      return Number.isFinite(parsed) ? parsed : null;
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
    const firstText = (root, selectors) => {
      for (const selector of selectors) {
        const value = clean(root.querySelector(selector)?.textContent);
        if (value)
          return value;
      }
      return '';
    };
    {
      if (location.pathname.replace(/\/+$/, '') !== '/Search')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在京东搜索结果页可用。');
      const maxItems =
          Math.min(200, Math.max(1, Number(input.maxItems ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const originalY = window.scrollY;
      const items = new Map();
      const productFromCard = (card) => {
        const skuId = clean(card.dataset.sku);
        if (!/^\d{5,32}$/.test(skuId))
          return null;
        let chatParams = null;
        const chatHref =
            card.querySelector('a[href*="chat.jd.com"]')?.getAttribute('href');
        if (chatHref) {
          try {
            chatParams = new URL(chatHref, location.href).searchParams;
          } catch {
            chatParams = null;
          }
        }
        const titleCandidates =
            Array.from(card.querySelectorAll('[title]'))
                .map((node) => clean(node.getAttribute('title')))
                .filter(
                    (value) => value.length >= 8 &&
                        !/^(?:已售|累计|\d|¥)/.test(value));
        const title = decodeRepeatedly(chatParams?.get('wname')) ||
            firstText(card,
                      [
                        '.p-name em', '.p-name a',
                        '[class*="goods_title_container"] [title]'
                      ]) ||
            titleCandidates.sort(
                (left, right) => right.length - left.length)[0] ||
            '';
        const priceTexts =
            Array.from(card.querySelectorAll('.p-price i, [class*="_price_"]'))
                .map((node) => clean(node.textContent))
                .filter((value) => /^¥?\s*\d[\d,.]*(?:\.\d+)?$/.test(value));
        const priceText =
            priceTexts.sort((left, right) => left.length - right.length)[0] ||
            null;
        const referencePriceText =
            firstText(card, ['[class*="_gray_"]', '.p-price del']) || null;
        const image =
            Array.from(card.querySelectorAll('img[data-src], img[src]'))
                .find((node) => {
                  const src = publicAssetUrl(
                      node.currentSrc || node.getAttribute('data-src') ||
                      node.src);
                  return /(?:360buyimg|jdimg)\.com/.test(src) &&
                      !/(?:imagetools|icon|logo)/i.test(src);
                });
        const titled = unique(Array.from(card.querySelectorAll('[title]'))
                                  .map((node) => node.getAttribute('title')));
        const badgeTexts = unique([
                             ...Array.from(card.querySelectorAll('img[alt]'))
                                 .map((node) => node.alt),
                             ...titled.filter(
                                 (value) => value.length <= 80 &&
                                     value !== title && !/^\d/.test(value))
                           ]).slice(0, 30);
        const metricTexts = unique([
          ...titled.filter(
              (value) =>
                  /评价|已售|人种草|人加购|人浏览|好评/.test(
                      value)),
          ...Array.from(card.querySelectorAll('[class*="volume"] span'))
              .map((node) => node.textContent)
        ]);
        const commentText = decodeRepeatedly(chatParams?.get('commentNum')) ||
            metricTexts.find((value) => /评价/.test(value)) || null;
        const sellingPoints =
            unique(
                Array.from(card.querySelectorAll('[class*="text-list"] span'))
                    .map((node) => clean(node.textContent).replace(/^\|/, '')))
                .slice(0, 20);
        const promotions =
            unique(titled.filter(
                       (value) =>
                           /补贴|优惠|立减|满\d+减|券|礼金|赠/.test(
                               value)))
                .slice(0, 20);
        const sellerName = decodeRepeatedly(chatParams?.get('seller')) ||
            Array.from(card.querySelectorAll('span, a'))
                .map((node) => clean(node.textContent))
                .find(
                    (value) => value.length <= 80 &&
                        /(?:店|旗舰店|专卖店|自营店)$/.test(value)) ||
            null;
        const stockText = decodeRepeatedly(chatParams?.get('stock')) ||
            Array.from(card.querySelectorAll('span, div'))
                .map((node) => clean(node.textContent))
                .find(
                    (value) =>
                        /^(?:有货|无货|预定|预约中|北京无货)$/
                            .test(value)) ||
            null;
        const rankText =
            titled.find((value) => /榜第\d+名/.test(value)) || null;
        return {
          skuId,
          canonicalUrl: `https://item.jd.com/${skuId}.html`,
          title,
          imageUrl: publicAssetUrl(
                        image?.currentSrc || image?.getAttribute('data-src') ||
                        image?.src) ||
              null,
          price: {
            currency: 'CNY',
            value: numericValue(priceText),
            text: priceText,
            label: firstText(card, ['[class*="_subsidy_"]']) || null,
            referenceText: referencePriceText,
            referenceValue: numericValue(referencePriceText)
          },
          seller: {name: sellerName},
          stockText,
          sellingPoints,
          promotions,
          badges: badgeTexts,
          metrics: {
            texts: metricTexts,
            commentText,
            commentCount: countValue(commentText),
            favorableRate: numericValue(chatParams?.get('evaluationRate'))
          },
          rankText,
          sponsored: Array.from(card.querySelectorAll('[class*="_ad_"]'))
                         .some(
                             (node) => clean(node.textContent) === '广告' &&
                                 node.getClientRects().length > 0)
        };
      };
      const collect = () => {
        const before = items.size;
        const cards = Array.from(document.querySelectorAll(
            '.plugin_goodsCardWrapper[data-sku], #J_goodsList [data-sku], .gl-item[data-sku]'));
        for (const card of cards) {
          const item = productFromCard(card);
          if (item && !items.has(item.skuId))
            items.set(item.skuId, item);
          if (items.size >= maxItems)
            break;
        }
        return items.size - before;
      };
      collect();
      let scrolls = 0;
      let idle = 0;
      let atEnd = window.scrollY + window.innerHeight >=
          document.documentElement.scrollHeight - 8;
      while (items.size < maxItems && scrolls < maxScrolls && idle < 3 &&
             !atEnd) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(720, window.innerHeight * 0.85), behavior: 'auto'});
        await pause(450);
        const added = collect();
        scrolls += 1;
        atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const resultItems = [...items.values()].slice(0, maxItems);
      const hitLimit = items.size >= maxItems;
      const complete = !hitLimit && (atEnd || idle >= 3);
      const stopReason = hitLimit ? 'max_items' :
          complete                ? 'current_page_end' :
                                    'max_scrolls';
      if (!/jsdom/i.test(navigator.userAgent))
        window.scrollTo({top: originalY, behavior: 'auto'});
      await pause(80);
      return {
        data: {
          query: new URL(location.href).searchParams.get('keyword') || '',
          pageScope: 'current_page',
          items: resultItems,
          count: resultItems.length,
          scrolls,
          complete,
          truncated: !complete,
          stopReason
        },
        warnings: [
          '结果只覆盖当前京东搜索结果页，不自动打开下一页；商品价格、库存和优惠以调用时页面显示为准。',
          ...(!complete ?
                  ['达到调用上限前未确认当前结果页结束，truncated=true。'] :
                  [])
        ]
      };
    }
  }
}


// 读取商品完整信息 — read.
// 读取当前京东商品的名称、价格、店铺、参数、规格、优惠、服务、配送、媒体、图文详情和指定数量的评价。
async function jingdong_get_product_details(rawInput = {}) {
  const route = (url) => {
    if (url.protocol !== 'https:')
      return null;
    if (url.hostname === 'search.jd.com' &&
        url.pathname.replace(/\/+$/, '') === '/Search') {
      const keyword = url.searchParams.get('keyword') || '';
      const page = url.searchParams.get('page') || '1';
      return {type: 'search', identity: `search:${keyword}:${page}`};
    }
    if (url.hostname === 'item.jd.com') {
      const skuId = url.pathname.match(/^\/(\d{5,32})\.html$/)?.[1];
      if (skuId)
        return {type: 'item', identity: `item:${skuId}`};
    }
    return null;
  };
  const jingdongAdapter = {
    matches: (url) => route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['jingdong_get_search_results'] :
        ['jingdong_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!jingdongAdapter.matches(routeUrl) ||
      !jingdongAdapter.toolNames(routeUrl).includes(
          'jingdong_get_product_details'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported 京东 page for this recipe.');
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
    const numericValue = (value) => {
      const match = clean(value).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
      const parsed = match ? Number(match[0]) : NaN;
      return Number.isFinite(parsed) ? parsed : null;
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
    const firstText = (root, selectors) => {
      for (const selector of selectors) {
        const value = clean(root.querySelector(selector)?.textContent);
        if (value)
          return value;
      }
      return '';
    };
    {
      const skuId = location.pathname.match(/^\/(\d{5,32})\.html$/)?.[1] || '';
      if (!skuId)
        throw new Error('UNSUPPORTED_ROUTE: 当前京东商品 SKU 无效。');
      const reviewLimit =
          Math.min(100, Math.max(1, Number(input.reviewLimit ?? 20)));
      const maxReviewScrolls =
          Math.min(30, Math.max(0, Number(input.maxReviewScrolls ?? 12)));
      const maxDetailImages =
          Math.min(200, Math.max(1, Number(input.maxDetailImages ?? 100)));
      const originalY = window.scrollY;
      const detailHeading = document.querySelector('#SPXQ-title');
      if (detailHeading &&
          (!document.querySelector('#detail-main') ||
           !document.querySelector('.attrs .item'))) {
        if (typeof detailHeading.scrollIntoView === 'function')
          detailHeading.scrollIntoView({block: 'start', behavior: 'auto'});
        await pause(400);
        for (let step = 0; step < 8 &&
             (!document.querySelector('#detail-main') ||
              !document.querySelector('.attrs .item'));
             step += 1) {
          window.scrollBy(
              {top: Math.max(700, window.innerHeight * 0.8), behavior: 'auto'});
          await pause(450);
        }
      }
      const detailSection =
          document.querySelector('#SPXQ-title')?.parentElement || null;
      const highlights = detailSection ?
          Array.from(detailSection.querySelectorAll('.highlight-attrs .item'))
              .map((node) => ({
                     name: firstText(node, ['.desc .text', '.desc']),
                     value: firstText(node, [':scope > .title', '.title'])
                   }))
              .filter((entry) => entry.name || entry.value) :
          [];
      const parameters = detailSection ?
          Array.from(detailSection.querySelectorAll('.attrs .item'))
              .map((node) => ({
                     name: firstText(node, ['.label .text', '.label']),
                     value: firstText(node, ['.value .text', '.value'])
                   }))
              .filter((entry) => entry.name || entry.value) :
          [];
      const detailMain = detailSection?.querySelector('#detail-main') || null;
      const detailTextBlocks = detailMain ?
          unique(Array
                     .from(detailMain.querySelectorAll(
                         '.ssd-widget-text span, [class*="widget-text"]'))
                     .map((node) => node.textContent))
              .slice(0, 200) :
          [];
      const detailImageCandidates = [];
      if (detailMain) {
        for (const image of Array.from(detailMain.querySelectorAll('img')))
          detailImageCandidates.push(
              image.currentSrc || image.getAttribute('data-src') ||
              image.getAttribute('data-lazy-img') || image.src);
        const css = Array.from(detailMain.querySelectorAll('style'))
                        .map((node) => node.textContent || '')
                        .join('\n');
        for (const match of css.matchAll(/url\((?:["']?)([^)"']+)/g))
          detailImageCandidates.push(match[1] || '');
        for (const node of Array.from(
                 detailMain.querySelectorAll('[style*="background"]'))) {
          const match = node.style.backgroundImage.match(/url\(["']?([^"')]+)/);
          if (match?.[1])
            detailImageCandidates.push(match[1]);
        }
      }
      const allDetailImages =
          unique(detailImageCandidates.map(publicAssetUrl)
                     .filter((url) => /(?:360buyimg|jdimg)\.com/.test(url)));
      const detailImages = input.includeDetailImages === false ?
          [] :
          allDetailImages.slice(0, maxDetailImages);
      const galleryImages =
          unique(
              Array
                  .from(document.querySelectorAll(
                      '.zoom-img, [class*="thumbnail"] img, [class*="preview"] img'))
                  .map(
                      (image) => publicAssetUrl(
                          image.currentSrc || image.getAttribute('data-src') ||
                          image.src))
                  .filter(
                      (url) => /(?:360buyimg|jdimg)\.com/.test(url) &&
                          !/(?:imagetools|icon|logo)/i.test(url)))
              .slice(0, 50);
      const variants =
          Array.from(document.querySelectorAll('.specification-group'))
              .map((group) => ({
                     name: firstText(group, ['.specification-group-label']),
                     options:
                         Array
                             .from(group.querySelectorAll(
                                 '.specification-item-sku'))
                             .map((option) => ({
                                    value:
                                        firstText(
                                            option,
                                            ['.specification-item-sku-text']) ||
                                        clean(option.textContent),
                                    selected:
                                        option.className.includes('selected'),
                                    disabled:
                                        option.className.includes('disabled')
                                  }))
                             .filter((option) => option.value)
                   }))
              .filter((group) => group.name || group.options.length);
      const discountRoot = document.querySelector('.page-right-discount');
      const activePromotions = discountRoot ?
          unique(
              Array
                  .from(discountRoot.querySelectorAll('.shareds > *, .shareds'))
                  .map((node) => node.textContent)
                  .filter(
                      (value) => !/^已享受[:：]?$/.test(clean(value)))) :
          [];
      const availablePromotions = discountRoot ?
          unique(Array
                     .from(discountRoot.querySelectorAll(
                         '.again-shareds > *, .again-shareds'))
                     .map((node) => node.textContent)
                     .filter(
                         (value) => !/^可再享[:：]?$/.test(clean(value)))) :
          [];
      const deliveryText =
          Array
              .from(document.querySelectorAll(
                  '.horizontal-layout, [class*="delivery"], [class*="address"]'))
              .map((node) => clean(node.textContent))
              .find((value) => /^送至/.test(value) && value.length < 1000) ||
          null;
      const serviceText =
          firstText(
              document, ['.page-right-service', '[class*="service-panel"]']) ||
          null;
      const shopRoot =
          document.querySelector('.shop-plugin[data-shopid], [data-shopid]');
      const shopName = shopRoot ?
          Array.from(shopRoot.querySelectorAll('[class*="name"], span, a'))
                  .map((node) => clean(node.textContent))
                  .find(
                      (value) => value.length > 1 && value.length <= 100 &&
                          /(?:店|旗舰店|专卖店|自营店)$/.test(
                              value)) ||
              null :
          null;
      const categoryPath =
          unique(Array
                     .from(document.querySelectorAll(
                         '[class*="crumb"] a, .crumb a, .crumb-wrap a'))
                     .map((node) => node.textContent))
              .slice(0, 20);
      const reviews = new Map();
      const addReview = (review) => {
        if (!review?.content)
          return;
        const key =
            `${clean(review.author)}\u0000${clean(review.publishedAt)}\u0000${
                clean(review.content).slice(0, 500)}`;
        if (!reviews.has(key))
          reviews.set(key, review);
      };
      const previewReviews = () =>
          Array
              .from(
                  document.querySelectorAll('#comment-root ul.list > li.item'))
              .map((node) => ({
                     id: null,
                     author: firstText(node, ['.nickname']) || null,
                     publishedAt: null,
                     sku: null,
                     content: firstText(node, ['.info']) || '',
                     sellerReply: null,
                     purchaseTag: null,
                     media: Array.from(node.querySelectorAll('.imgs img.img'))
                                .map((image) => ({
                                       type: 'image',
                                       url: publicAssetUrl(
                                           image.currentSrc || image.src)
                                     }))
                                .filter((entry) => entry.url)
                   }));
      const modalReviews = () =>
          Array.from(document.querySelectorAll('#rateList .jdc-pc-rate-card'))
              .map((node) => {
                const sellerReplyNode =
                    Array.from(node.querySelectorAll('*')).find((entry) => {
                      const value = clean(entry.textContent);
                      return /^商家[:：]/.test(value) &&
                          !Array.from(entry.children)
                               .some(
                                   (child) => /^商家[:：]/.test(
                                       clean(child.textContent)));
                    });
                return {
                  id: null,
                  author: firstText(node, ['.jdc-pc-rate-card-nick']) || null,
                  publishedAt: firstText(node, ['.date']) || null,
                  sku:
                      firstText(node, ['.jdc-pc-rate-card-info .info']) || null,
                  content:
                      firstText(node, ['.jdc-pc-rate-card-main-desc']) || '',
                  sellerReply: clean(sellerReplyNode?.textContent)
                                   .replace(/^商家[:：]\s*/, '') ||
                      null,
                  purchaseTag: firstText(node, ['.jd-content-pc-tag']) || null,
                  media: Array.from(node.querySelectorAll('img[alt="pic"]'))
                             .map((image) => ({
                                    type: 'image',
                                    url: publicAssetUrl(
                                        image.currentSrc || image.src)
                                  }))
                             .filter((entry) => entry.url)
                };
              });
      previewReviews().forEach(addReview);
      const hadReviewModal =
          Boolean(document.querySelector('#rateList .jdc-page-overlay'));
      let openedReviewModal = false;
      let reviewScrolls = 0;
      let reviewStopReason = 'preview_only';
      if (reviews.size < reviewLimit) {
        if (!hadReviewModal) {
          const openAll = document.querySelector('#comment-root .all-btn') ||
              Array
                  .from(document.querySelectorAll(
                      '#comment-root button, #comment-root a, #comment-root [role="button"], #comment-root div'))
                  .find((node) => clean(node.textContent) === '全部评价') ||
              null;
          if (openAll) {
            openAll.click();
            openedReviewModal = true;
            for (let attempt = 0; attempt < 30 &&
                 !document.querySelector('#rateList .jdc-page-overlay');
                 attempt += 1)
              await pause(100);
          }
        }
        modalReviews().forEach(addReview);
        const scroller = document.querySelector(
                             '#rateList [class*="_rateListContainer_"]') ||
            Array.from(document.querySelectorAll('#rateList *'))
                .filter((node) => node.scrollHeight > node.clientHeight + 20)
                .sort(
                    (left, right) =>
                        right.scrollHeight - left.scrollHeight)[0] ||
            null;
        let idle = 0;
        while (reviews.size < reviewLimit && scroller &&
               reviewScrolls < maxReviewScrolls && idle < 3) {
          const before = reviews.size;
          scroller.scrollTop = Math.min(
              scroller.scrollHeight,
              scroller.scrollTop + Math.max(500, scroller.clientHeight * 0.8));
          scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
          await pause(350);
          modalReviews().forEach(addReview);
          reviewScrolls += 1;
          idle = reviews.size === before ? idle + 1 : 0;
          if (scroller.scrollTop + scroller.clientHeight >=
              scroller.scrollHeight - 4) {
            reviewStopReason = 'end';
            break;
          }
        }
        if (reviews.size >= reviewLimit)
          reviewStopReason = 'review_limit';
        else if (reviewStopReason !== 'end')
          reviewStopReason = reviewScrolls >= maxReviewScrolls ?
              'max_review_scrolls' :
              idle >= 3 ? 'idle' :
                          'preview_only';
      }
      if (openedReviewModal) {
        const close =
            document.querySelector('#rateList [class*="_closeIcon_"]');
        close?.click();
        await pause(80);
      }
      if (!/jsdom/i.test(navigator.userAgent))
        window.scrollTo({top: originalY, behavior: 'auto'});
      await pause(80);
      const title =
          firstText(
              document, ['.sku-title-name', '.sku-title-text', '.sku-name']) ||
          clean(meta('og:title')) ||
          document.title.replace(/【.*$/, '').trim();
      const currentPriceText =
          firstText(document, ['.product-price--main', '.p-price']) || null;
      const referencePriceText =
          firstText(
              document,
              ['.product-price--gray-line-through', '.product-price--gray']) ||
          null;
      const totalReviewText =
          firstText(
              document,
              [
                '.product-price-panel--options-comment-count', '#comment-title'
              ]) ||
          null;
      const reviewItems = [...reviews.values()].slice(0, reviewLimit);
      const totalReviewCount = countValue(totalReviewText);
      const reviewTags =
          Array.from(document.querySelectorAll('#comment-root .tags .item'))
              .map((node) => {
                const parts = Array.from(node.children)
                                  .map((child) => clean(child.textContent))
                                  .filter(Boolean);
                return {
                  name: parts[0] || clean(node.textContent),
                  countText: parts[1] || null,
                  count: countValue(parts[1])
                };
              })
              .filter((entry) => entry.name);
      return {
        data: {
          skuId,
          canonicalUrl: `https://item.jd.com/${skuId}.html`,
          title,
          description: clean(
                           meta('description') || meta('og:description') ||
                           firstText(document, ['.sku-subtitle', '.p-ad']) ||
                           detailTextBlocks.join('\n'))
                           .slice(0, 5000) ||
              null,
          categoryPath,
          price: {
            currency: 'CNY',
            value: numericValue(currentPriceText),
            text: currentPriceText,
            label:
                firstText(document, ['.product-price--activity-item--tag']) ||
                null,
            referenceValue: numericValue(referencePriceText),
            referenceText: referencePriceText
          },
          seller:
              {shopId: clean(shopRoot?.dataset.shopid) || null, name: shopName},
          promotions:
              {active: activePromotions, available: availablePromotions},
          deliveryText,
          serviceText,
          variants,
          media: {galleryImages},
          details: {
            highlights,
            parameters,
            textBlocks: detailTextBlocks,
            imageCount: allDetailImages.length,
            images: detailImages,
            imagesIncluded: input.includeDetailImages !== false,
            truncated: input.includeDetailImages !== false &&
                allDetailImages.length > maxDetailImages
          },
          reviews: {
            requested: reviewLimit,
            count: reviewItems.length,
            totalText: totalReviewText,
            totalCount: totalReviewCount,
            favorableRateText:
                firstText(document, ['#comment-root .applause-rate']) || null,
            tags: reviewTags,
            items: reviewItems,
            scrolls: reviewScrolls,
            truncated: totalReviewCount !== null ?
                reviewItems.length < totalReviewCount :
                reviewItems.length >= reviewLimit ||
                    !['end'].includes(reviewStopReason),
            stopReason: reviewStopReason
          }
        },
        warnings: [
          '价格、优惠、库存、配送和评价均来自当前京东页面，可能随地区、登录态和时间变化。',
          '评价按京东当前排序读取；工具会临时打开并关闭评价面板，不会点赞或发布评价。',
          ...(reviewItems.length < reviewLimit ?
                  [`页面只加载到 ${reviewItems.length} 条评价，少于请求的 ${
                      reviewLimit} 条。`] :
                  [])
        ]
      };
    }
  }
}
