// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取搜索结果商品 — read. 滚动并读取当前 Amazon 搜索结果页全部已加载商品，包含
// ASIN、标题、价格、评分、评论数、图片、徽章、配送和优惠。
async function amazon_get_search_results(rawInput = {}) {
  const productAsin = (url) =>
      url.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i)
          ?.[1]
          ?.toUpperCase() ??
      null;
  const route = (url) => {
    if (url.pathname === '/s' && url.searchParams.has('k')) {
      const query = url.searchParams.get('k')?.trim() || '';
      const page = url.searchParams.get('page') || '1';
      return query ? {type: 'search', identity: `search:${query}:${page}`} :
                     null;
    }
    const asin = productAsin(url);
    return asin ? {type: 'product', identity: `product:${asin}`} : null;
  };
  const amazonAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['amazon.com', 'www.amazon.com'].includes(url.hostname) &&
        route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['amazon_get_search_results'] :
        ['amazon_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!amazonAdapter.matches(routeUrl) ||
      !amazonAdapter.toolNames(routeUrl).includes('amazon_get_search_results'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported Amazon page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['maxProducts', 'maxScrolls', 'includeSponsored'].includes(
                key)) &&
        (!('maxProducts' in rawInput) ||
         (Number.isInteger(rawInput['maxProducts']) &&
          rawInput['maxProducts'] >= 1 && rawInput['maxProducts'] <= 200)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 30)) &&
        (!('includeSponsored' in rawInput) ||
         (typeof rawInput['includeSponsored'] === 'boolean'))))
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
    const pause = (milliseconds) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const unique = (values) => [...new Set(values.map(clean).filter(Boolean))];
    const elementText = (node, maxLength = 10000) => {
      if (!node)
        return '';
      const copy = node.cloneNode(true);
      copy.querySelectorAll(
              'script,style,noscript,template,[aria-hidden="true"]')
          .forEach((entry) => entry.remove());
      return clean(copy.innerText || copy.textContent).slice(0, maxLength);
    };
    const firstText = (selectors, root = document, maxLength = 10000) => {
      for (const selector of selectors) {
        const value = elementText(root.querySelector(selector), maxLength);
        if (value)
          return value;
      }
      return '';
    };
    const parseCount = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([KMB])?/i);
      if (!match)
        return null;
      const amount = Number(match[1]);
      if (!Number.isFinite(amount))
        return null;
      const multiplier =
          {k: 1e3, m: 1e6, b: 1e9}[(match[2] || '').toLowerCase()] || 1;
      return Math.round(amount * multiplier);
    };
    const parseRating = (value) => {
      const match = clean(value).match(
          /([0-5](?:[.,]\d+)?)\s*(?:out of|von|sur|de)?\s*5/i);
      if (!match)
        return null;
      const rating = Number(match[1].replace(',', '.'));
      return Number.isFinite(rating) ? rating : null;
    };
    const money = (value) => {
      const rawText = clean(value);
      if (!rawText)
        return null;
      const numberText = rawText.match(/\d[\d,]*(?:\.\d{1,2})?/)?.[0];
      const amount = numberText ? Number(numberText.replace(/,/g, '')) : null;
      const currency = rawText.includes('$') ? 'USD' :
          rawText.includes('£')              ? 'GBP' :
          rawText.includes('€')              ? 'EUR' :
          rawText.includes('¥')              ? 'JPY' :
                                               null;
      return {
        rawText,
        amount: Number.isFinite(amount) ? amount : null,
        currency
      };
    };
    const productUrl = (asin) => `${location.origin}/dp/${asin}`;
    const blockedText =
        clean(document.body?.innerText || document.body?.textContent)
            .slice(0, 2000);
    if (/enter the characters you see|sorry, we just need to make sure|robot check|type the characters you see/i
            .test(`${document.title} ${blockedText}`)) {
      return {
        data: null,
        error: {
          code: 'PERMISSION_DENIED',
          message: 'Amazon 要求完成人机验证，请先在页面中手动完成。',
          recoverable: true
        }
      };
    }
    const cardToProduct = (card) => {
      const asin = clean(card.dataset.asin).toUpperCase();
      const title = firstText(
          ['h2 a span', 'h2 span', '[data-cy="title-recipe"] h2'], card, 1000);
      if (!/^[A-Z0-9]{10}$/.test(asin) || !title)
        return null;
      const sponsored =
          Boolean(card.querySelector(
              '.puis-sponsored-label-text, [aria-label="Sponsored"], [aria-label="赞助"]')) ||
          /(?:^|\s)Sponsored(?:\s|$)/i.test(firstText(
              ['.puis-label-popover-default', '.s-sponsored-label-info-icon'],
              card, 100));
      const currentPrice = firstText(
          [
            '.a-price:not(.a-text-price) .a-offscreen',
            '[data-cy="price-recipe"] .a-offscreen'
          ],
          card, 100);
      const originalPrice = firstText(
          ['.a-price.a-text-price[data-a-strike="true"] .a-offscreen'], card,
          100);
      const image =
          card.querySelector('img.s-image, [data-cy="image-container"] img');
      const ratingText =
          firstText(
              [
                '.a-icon-star-small .a-icon-alt',
                '.a-icon-star-mini .a-icon-alt', '[aria-label*="out of 5"]'
              ],
              card, 100) ||
          clean(card.querySelector('[aria-label*="out of 5"]')
                    ?.getAttribute('aria-label'));
      const reviewLink = card.querySelector('a[href*="#customerReviews"]');
      const reviewText = clean(
          reviewLink?.getAttribute('aria-label') || reviewLink?.textContent);
      const delivery = firstText(
          [
            '[data-cy="delivery-recipe"]',
            '[data-cy="delivery-recipe"] .a-color-base',
            '.s-align-children-center + .a-row'
          ],
          card, 1000);
      const coupon =
          firstText(['.s-coupon-unclipped', '[class*="coupon"]'], card, 500);
      const purchaseVolume = firstText(
          ['[class*="social-proofing"]', '.a-size-base.a-color-secondary'],
          card, 300);
      const badges =
          unique(
              Array
                  .from(card.querySelectorAll(
                      '.a-badge-text, .a-badge-label, [data-component-type="s-status-badge-component"]'))
                  .map((node) => elementText(node, 120)))
              .slice(0, 20);
      return {
        asin,
        position: Number(card.dataset.index) || null,
        title,
        url: productUrl(asin),
        image: image ? {
          url: absolute(image.currentSrc || image.src),
          alt: clean(image.alt) || null
        } :
                       null,
        price: {current: money(currentPrice), original: money(originalPrice)},
        rating: parseRating(ratingText),
        ratingText: ratingText || null,
        reviewCount: parseCount(reviewText),
        reviewCountText: reviewText || null,
        sponsored,
        prime:
            Boolean(card.querySelector('.a-icon-prime, [aria-label*="Prime"]')),
        badges,
        purchaseVolume: purchaseVolume || null,
        delivery: delivery || null,
        coupon: coupon || null
      };
    };
    {
      if (location.pathname !== '/s')
        throw new Error(
            'UNSUPPORTED_ROUTE: 该操作只在 Amazon 搜索结果页可用。');
      const maxProducts =
          Math.min(200, Math.max(1, Number(input.maxProducts ?? 100)));
      const maxScrolls =
          Math.min(30, Math.max(0, Number(input.maxScrolls ?? 12)));
      const includeSponsored = input.includeSponsored !== false;
      const originalY = window.scrollY;
      const products = new Map();
      let scrolls = 0;
      let idle = 0;
      const collect = () => {
        const before = products.size;
        const cards = Array.from(document.querySelectorAll(
            '[data-component-type="s-search-result"][data-asin]'));
        for (const card of cards) {
          const product = cardToProduct(card);
          if (product && (includeSponsored || !product.sponsored))
            products.set(product.asin, product);
        }
        return products.size - before;
      };
      collect();
      while (products.size < maxProducts && scrolls < maxScrolls && idle < 2) {
        const previousHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(720, window.innerHeight * 0.9), behavior: 'auto'});
        await pause(350);
        const added = collect();
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === previousHeight) ?
            idle + 1 :
            0;
        scrolls += 1;
      }
      const observed = Array.from(products.values());
      const items = observed.slice(0, maxProducts);
      const stoppedAtLimit = observed.length > maxProducts ||
          (observed.length >= maxProducts && scrolls < maxScrolls);
      const stoppedAtScrollLimit = scrolls >= maxScrolls && idle < 2;
      const truncated = stoppedAtLimit || stoppedAtScrollLimit;
      if (document.documentElement.scrollHeight > window.innerHeight) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(50);
      }
      return {
        data: {
          query: clean(new URL(location.href).searchParams.get('k')),
          pageNumber:
              Number(new URL(location.href).searchParams.get('page') || '1') ||
              1,
          resultSummary: firstText(
                             [
                               '.sg-col-inner .a-section .a-size-base',
                               '[data-component-type="s-result-info-bar"]'
                             ],
                             document, 500) ||
              null,
          items,
          count: items.length,
          scrolls,
          includeSponsored,
          truncated,
          stopReason: stoppedAtLimit ? 'max_products' :
              stoppedAtScrollLimit   ? 'max_scrolls' :
                                       'page_end'
        },
        warnings: [
          '只读取当前 Amazon 搜索结果页，不自动打开下一页。',
          ...(truncated ? ['结果达到调用上限；truncated=true。'] : [])
        ]
      };
    }
  }
}


// 读取商品完整详情 — read. 读取当前 Amazon
// 商品的名称、描述、卖点、图片、价格、优惠、规格、变体、配送、卖家、评分分布和指定数量的页面评论。
async function amazon_get_product_details(rawInput = {}) {
  const productAsin = (url) =>
      url.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i)
          ?.[1]
          ?.toUpperCase() ??
      null;
  const route = (url) => {
    if (url.pathname === '/s' && url.searchParams.has('k')) {
      const query = url.searchParams.get('k')?.trim() || '';
      const page = url.searchParams.get('page') || '1';
      return query ? {type: 'search', identity: `search:${query}:${page}`} :
                     null;
    }
    const asin = productAsin(url);
    return asin ? {type: 'product', identity: `product:${asin}`} : null;
  };
  const amazonAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['amazon.com', 'www.amazon.com'].includes(url.hostname) &&
        route(url) !== null,
    toolNames: (url) => route(url)?.type === 'search' ?
        ['amazon_get_search_results'] :
        ['amazon_get_product_details']
  };
  const routeUrl = new URL(location.href);
  if (!amazonAdapter.matches(routeUrl) ||
      !amazonAdapter.toolNames(routeUrl).includes('amazon_get_product_details'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported Amazon page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => ['reviewLimit'].includes(key)) &&
        (!('reviewLimit' in rawInput) ||
         (Number.isInteger(rawInput['reviewLimit']) &&
          rawInput['reviewLimit'] >= 0 && rawInput['reviewLimit'] <= 100))))
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
    const pause = (milliseconds) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const unique = (values) => [...new Set(values.map(clean).filter(Boolean))];
    const elementText = (node, maxLength = 10000) => {
      if (!node)
        return '';
      const copy = node.cloneNode(true);
      copy.querySelectorAll(
              'script,style,noscript,template,[aria-hidden="true"]')
          .forEach((entry) => entry.remove());
      return clean(copy.innerText || copy.textContent).slice(0, maxLength);
    };
    const firstText = (selectors, root = document, maxLength = 10000) => {
      for (const selector of selectors) {
        const value = elementText(root.querySelector(selector), maxLength);
        if (value)
          return value;
      }
      return '';
    };
    const parseCount = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([KMB])?/i);
      if (!match)
        return null;
      const amount = Number(match[1]);
      if (!Number.isFinite(amount))
        return null;
      const multiplier =
          {k: 1e3, m: 1e6, b: 1e9}[(match[2] || '').toLowerCase()] || 1;
      return Math.round(amount * multiplier);
    };
    const parseRating = (value) => {
      const match = clean(value).match(
          /([0-5](?:[.,]\d+)?)\s*(?:out of|von|sur|de)?\s*5/i);
      if (!match)
        return null;
      const rating = Number(match[1].replace(',', '.'));
      return Number.isFinite(rating) ? rating : null;
    };
    const money = (value) => {
      const rawText = clean(value);
      if (!rawText)
        return null;
      const numberText = rawText.match(/\d[\d,]*(?:\.\d{1,2})?/)?.[0];
      const amount = numberText ? Number(numberText.replace(/,/g, '')) : null;
      const currency = rawText.includes('$') ? 'USD' :
          rawText.includes('£')              ? 'GBP' :
          rawText.includes('€')              ? 'EUR' :
          rawText.includes('¥')              ? 'JPY' :
                                               null;
      return {
        rawText,
        amount: Number.isFinite(amount) ? amount : null,
        currency
      };
    };
    const productUrl = (asin) => `${location.origin}/dp/${asin}`;
    const blockedText =
        clean(document.body?.innerText || document.body?.textContent)
            .slice(0, 2000);
    if (/enter the characters you see|sorry, we just need to make sure|robot check|type the characters you see/i
            .test(`${document.title} ${blockedText}`)) {
      return {
        data: null,
        error: {
          code: 'PERMISSION_DENIED',
          message: 'Amazon 要求完成人机验证，请先在页面中手动完成。',
          recoverable: true
        }
      };
    }
    {
      const asin =
          clean(
              document.querySelector('#ASIN')?.value ||
              location.pathname
                  .match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i)
                  ?.[1])
              .toUpperCase();
      if (!/^[A-Z0-9]{10}$/.test(asin))
        throw new Error(
            'UNSUPPORTED_ROUTE: 该操作只在 Amazon 商品详情页可用。');
      const reviewLimit =
          Math.min(100, Math.max(0, Number(input.reviewLimit ?? 20)));
      const originalY = window.scrollY;
      if (reviewLimit > 0 &&
          document.documentElement.scrollHeight > window.innerHeight) {
        for (const ratio of [0.3, 0.6, 0.85, 1]) {
          window.scrollTo({
            top: Math.round(document.documentElement.scrollHeight * ratio),
            behavior: 'auto'
          });
          await pause(180);
        }
      }
      const pairEntries = (selectors) => {
        const entries = [];
        const seen = new Set();
        for (const selector of selectors) {
          for (const row of Array.from(document.querySelectorAll(selector))) {
            const name =
                firstText(
                    ['th', '.a-span3', '.a-text-bold', '.label'], row, 500)
                    .replace(/:\s*$/, '');
            const value = firstText(['td', '.a-span9', '.value'], row, 3000) ||
                (row.matches('li') ?
                     elementText(row, 3000).replace(name, '').replace(
                         /^\s*:\s*/, '') :
                     '');
            const key = `${name}\u0000${value}`;
            if (name && value && !seen.has(key)) {
              seen.add(key);
              entries.push({name, value});
            }
          }
        }
        return entries.slice(0, 200);
      };
      const featureBullets = unique(Array
                                        .from(document.querySelectorAll(
                                            '#feature-bullets li .a-list-item'))
                                        .map((node) => elementText(node, 3000)))
                                 .slice(0, 100);
      const overview =
          pairEntries(['#productOverview_feature_div tr', '#poExpander tr']);
      const details = pairEntries([
        '#productDetails_feature_div table tr',
        '#productDetails_techSpec_section_1 tr',
        '#productDetails_techSpec_section_2 tr',
        '#productDetails_detailBullets_sections1 tr',
        '#detailBullets_feature_div li'
      ]);
      const dynamicImages = (() => {
        const raw = document.querySelector('#landingImage')
                        ?.getAttribute('data-a-dynamic-image');
        if (!raw)
          return [];
        try {
          return Object.keys(JSON.parse(raw));
        } catch {
          return [];
        }
      })();
      const imageNodes = Array.from(document.querySelectorAll(
          '#landingImage, #altImages img, .imageThumbnail img'));
      const images = unique([
                       ...dynamicImages.map(absolute),
                       ...imageNodes.map(
                           (image) => absolute(image.currentSrc || image.src)),
                       meta('og:image')
                     ])
                         .filter((url) => /^https:\/\//.test(url))
                         .slice(0, 100);
      const promotionSelectors = [
        '#couponText', '#couponFeature', '#dealBadge_feature_div',
        '#promotions_feature_div .a-row',
        '.reinventPriceSavingsPercentageMargin', '#primeExclusiveBadge',
        '[data-feature-name="promoPriceBlockMessage"]'
      ];
      const promotions =
          unique(
              promotionSelectors.flatMap(
                  (selector) => Array.from(document.querySelectorAll(selector))
                                    .map((node) => elementText(node, 1000))))
              .slice(0, 50);
      const variationNodes = Array.from(document.querySelectorAll(
          '#twister li[data-asin], #twister .a-button, [data-csa-c-type="widget"][data-feature-name="twister"] li'));
      const variations =
          variationNodes
              .map((node) => ({
                     asin: clean(node.dataset.asin) || null,
                     label: clean(node.getAttribute('title')) ||
                         firstText(['img', '.a-button-text'], node, 500) ||
                         elementText(node, 500),
                     selected: node.classList.contains('swatchSelect') ||
                         node.classList.contains('a-button-selected') ||
                         node.getAttribute('aria-checked') === 'true',
                     available: !node.classList.contains('swatchUnavailable') &&
                         !node.classList.contains('a-button-disabled')
                   }))
              .filter((entry) => entry.label)
              .slice(0, 100);
      const reviewNodes =
          Array.from(document.querySelectorAll('[data-hook="review"]'));
      const reviews =
          reviewNodes.slice(0, reviewLimit)
              .map((review) => {
                const ratingText = firstText(
                    [
                      '[data-hook="review-star-rating"] .a-icon-alt',
                      '[data-hook="cmps-review-star-rating"] .a-icon-alt',
                      '.review-rating .a-icon-alt'
                    ],
                    review, 100);
                const title =
                    firstText(['[data-hook="review-title"]'], review, 1000)
                        .replace(
                            /^\s*[0-5](?:[.,]\d+)?\s*out of 5 stars\s*/i, '');
                const authorLink = review.querySelector('.a-profile');
                return {
                  id: clean(review.id || review.dataset.reviewId) || null,
                  title: title || null,
                  rating: parseRating(ratingText),
                  ratingText: ratingText || null,
                  author: {
                    name: firstText(['.a-profile-name'], review, 500) || null,
                    profileUrl:
                        absolute(authorLink?.getAttribute('href')) || null
                  },
                  date: firstText(['[data-hook="review-date"]'], review, 500) ||
                      null,
                  verifiedPurchase:
                      Boolean(review.querySelector('[data-hook="avp-badge"]')),
                  variant:
                      firstText(['[data-hook="format-strip"]'], review, 500) ||
                      null,
                  body: firstText(['[data-hook="review-body"]'], review, 10000),
                  helpfulCount: parseCount(firstText(
                      ['[data-hook="helpful-vote-statement"]'], review, 300)),
                  images:
                      unique(
                          Array
                              .from(review.querySelectorAll(
                                  '[data-hook="review-image-tile"] img, .review-image-tile'))
                              .map(
                                  (image) =>
                                      absolute(image.currentSrc || image.src)))
                          .slice(0, 20)
                };
              })
              .filter((review) => review.body || review.title);
      const histogram =
          Array
              .from(document.querySelectorAll(
                  '#histogramTable tr, #histogramTable li'))
              .map((row) => {
                const rowText = clean(row.querySelector('[aria-label]')
                                          ?.getAttribute('aria-label')) ||
                    elementText(row, 500);
                const stars = Number(rowText.match(/([1-5])\s*star/i)?.[1]);
                const percent =
                    Number(rowText.match(/(\d{1,3})\s*(?:%|percent\b)/i)?.[1]);
                return Number.isFinite(stars) && Number.isFinite(percent) &&
                        percent <= 100 ?
                    {stars, percent} :
                    null;
              })
              .filter(Boolean);
      let currentPrice = firstText(
          [
            '#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen',
            '#corePrice_feature_div .priceToPay .a-offscreen',
            '#corePrice_feature_div .apex-pricetopay-value .a-offscreen',
            '#apex_desktop .a-price:not(.a-text-price) .a-offscreen',
            '#priceblock_ourprice', '#priceblock_dealprice'
          ],
          document, 100);
      if (!currentPrice) {
        // Some price-to-pay widgets leave their accessibility text empty.
        const price = document.querySelector(
            '#corePriceDisplay_desktop_feature_div .priceToPay, #corePrice_feature_div .apex-pricetopay-value');
        const whole = clean(price?.querySelector('.a-price-whole')?.textContent)
                          .replace(/\.$/, '');
        const fraction =
            clean(price?.querySelector('.a-price-fraction')?.textContent);
        if (/^\d[\d,]*$/.test(whole) && /^\d{2}$/.test(fraction))
          currentPrice =
              `${clean(price?.querySelector('.a-price-symbol')?.textContent)}${
                  whole}.${fraction}`;
      }
      const originalPrice = firstText(
          [
            '.basisPrice .a-offscreen',
            '#corePrice_feature_div .a-price.a-text-price[data-a-strike="true"] .a-offscreen'
          ],
          document, 100);
      const merchantName = firstText(
          [
            '#merchantInfoFeature_feature_div .offer-display-feature-text-message'
          ],
          document, 1000);
      const merchantLabel = firstText(
          ['#merchantInfoFeature_feature_div .offer-display-feature-label'],
          document, 100);
      const reviewCountText =
          firstText(['#acrCustomerReviewText'], document, 100);
      const ratingText =
          clean(document.querySelector('#acrPopover')?.getAttribute('title')) ||
          firstText(
              ['#acrPopover .a-icon-alt', '[data-hook="rating-out-of-text"]'],
              document, 100);
      const breadcrumbNodes = Array.from(document.querySelectorAll(
          '#wayfinding-breadcrumbs_container a, #wayfinding-breadcrumbs_container li span'));
      const data = {
        asin,
        canonicalUrl: productUrl(asin),
        title: firstText(['#productTitle'], document, 2000) ||
            meta('og:title') || document.title,
        brand: firstText(['#bylineInfo'], document, 1000) ||
            overview.find((entry) => /brand/i.test(entry.name))?.value || null,
        brandUrl:
            absolute(
                document.querySelector('#bylineInfo')?.getAttribute('href')) ||
            null,
        breadcrumbs:
            unique(breadcrumbNodes.map((node) => elementText(node, 500))),
        badges: unique(
            Array
                .from(document.querySelectorAll(
                    '#title_feature_div .a-badge-text, #acBadge_feature_div .a-badge-text, #dealBadge_feature_div'))
                .map((node) => elementText(node, 500))),
        price: {
          current: money(currentPrice),
          original: money(originalPrice),
          savings: firstText(
                       ['.savingsPercentage', '#regularprice_savings'],
                       document, 200) ||
              null
        },
        promotions,
        availability:
            firstText(['#availability span', '#outOfStock'], document, 1000) ||
            null,
        delivery:
            firstText(
                [
                  '#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE',
                  '#deliveryBlockMessage', '#ddmDeliveryMessage'
                ],
                document, 2000) ||
            null,
        seller: firstText(['#sellerProfileTriggerId'], document, 1000) ||
            merchantName || firstText(['#merchant-info'], document, 1000) ||
            null,
        shipsFrom:
            firstText(
                [
                  '#tabular-buybox .tabular-buybox-text[tabular-attribute-name="Ships from"]',
                  '#fulfillerInfoFeature_feature_div .offer-display-feature-text-message',
                  '#fulfillerInfoFeature_feature_div'
                ],
                document, 1000) ||
            (/shipper\s*\/\s*seller/i.test(merchantLabel) ? merchantName :
                                                            null) ||
            null,
        rating: parseRating(ratingText),
        ratingText: ratingText || null,
        reviewCount: parseCount(reviewCountText),
        reviewCountText: reviewCountText || null,
        answeredQuestions: parseCount(firstText(
            ['#askATFLink', '#acrCustomerReviewLink + span'], document, 200)),
        featureBullets,
        description: firstText(['#productDescription'], document, 20000) ||
            meta('description') || '',
        aPlusContent: firstText(['#aplus'], document, 50000) || null,
        overview,
        details,
        images,
        variations,
        reviews: {
          requestedLimit: reviewLimit,
          returned: reviews.length,
          availableOnPage: reviewNodes.length,
          total: parseCount(reviewCountText),
          truncated: (parseCount(reviewCountText) || reviewNodes.length) >
              reviews.length,
          histogram,
          items: reviews
        }
      };
      if (document.documentElement.scrollHeight > window.innerHeight) {
        window.scrollTo({top: originalY, behavior: 'auto'});
        await pause(50);
      }
      return {
        data,
        warnings: [
          '评论只来自当前商品页已加载的评论卡片，不自动打开全部评论页。',
          ...(reviews.length < reviewLimit ?
                  [`请求 ${reviewLimit} 条评论，当前页面只提供 ${
                      reviews.length} 条。`] :
                  [])
        ]
      };
    }
  }
}
