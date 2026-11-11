// Nodejs recipe: paste webmcp.js and this definition, then explicitly call it.
// Pagination runs in a scratch tab, preserving the user's original search page.
async function readGoofishSearchInTemporaryPage(input = {}) {
  const url = new URL(page.url());
  if (url.origin !== 'https://www.goofish.com' || url.pathname !== '/search' ||
      !url.searchParams.get('q')) {
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a Goofish search with a keyword first.');
  }
  const tab = await context.newPage();
  try {
    await tab.goto(url.href, {waitUntil: 'domcontentloaded'});
    return await tab.evaluate(goofish_get_search_results, input);
  } finally {
    await tab.close();
  }
}
