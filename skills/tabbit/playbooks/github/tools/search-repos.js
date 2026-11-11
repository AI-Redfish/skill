function boundedInteger(value, fallback, max) {
  const number = value === undefined ? fallback : Number(value);
  if (!Number.isFinite(number))
    return fallback;
  return Math.max(1, Math.min(max, Math.trunc(number)));
}

async function searchRepos(args = {}) {
  const query = args.query || '';
  const maxResults = boundedInteger(args.maxResults, 25, 100);
  if (!query)
    throw new Error('search query is required');

  await page.goto(
      `https://github.com/search?q=${
          encodeURIComponent(query)}&type=repositories&s=stars&o=desc`,
      {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(
      () => document.querySelector('main .search-title a') ||
          /^0 results\b/.test(document.querySelector('#search-results-count')
                                  ?.textContent.trim()));

  return await page.evaluate(
      maxResults => [...document.querySelectorAll('main .search-title a')]
                        .slice(0, maxResults)
                        .map(a => {
                          const link = a.getAttribute('href');
                          const [, owner, name] = link.split('/');
                          const stars =
                              document
                                  .querySelector(`a[href="${link}/stargazers"]`)
                                  ?.innerText.trim() ||
                              '';
                          return {name, owner, stars, link};
                        }),
      maxResults);
}
