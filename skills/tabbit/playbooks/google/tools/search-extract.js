function boundedInteger(value, fallback, max) {
  const number = value === undefined ? fallback : Number(value);
  if (!Number.isFinite(number))
    return fallback;
  return Math.max(1, Math.min(max, Math.trunc(number)));
}

async function searchAndExtract(args = {}) {
  const query = args.query || '';
  const maxResults = boundedInteger(args.maxResults, 10, 100);
  if (!query)
    throw new Error('search query is required');

  await page.goto(
      `https://www.google.com/search?q=${encodeURIComponent(query)}`,
      {waitUntil: 'domcontentloaded'});
  await page.locator('#search').waitFor({state: 'attached'});

  return await page.evaluate((limit) => {
    const results = new Map();
    for (const heading of document.querySelectorAll('#search h3')) {
      const link = heading.closest('a[href]');
      const block = heading.closest('[data-snc], .tF2Cxc');
      const title = heading.innerText.trim();
      if (!link || !block || !title ||
          !heading.checkVisibility({visibilityProperty: true}) ||
          results.has(link.href))
        continue;
      results.set(link.href, {
        title,
        url: link.href,
        snippet:
            block.querySelector('[data-sncf], .VwiC3b')?.innerText.trim() || '',
      });
      if (results.size === limit)
        break;
    }
    return [...results.values()];
  }, maxResults);
}
