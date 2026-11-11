// Nodejs recipes; paste webmcp.js first, then these definitions, then call one.
// Uses only existing page/context APIs. Never closes the user's original page.
async function readXThreadInTemporaryPage(input = {}) {
  let postUrl = input.postUrl;
  if (!postUrl) {
    postUrl = await page.evaluate(({postId}) => {
      for (const time of document.querySelectorAll(
               'article[data-testid="tweet"] time')) {
        const href = time.closest('a[href]')?.getAttribute('href') || '';
        const match = href.match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
        if (match && postId && match[2] === postId)
          return `https://x.com/${match[1]}/status/${match[2]}`;
      }
      return null;
    }, input);
  }
  const match = typeof postUrl === 'string' &&
      postUrl.match(
          /^https:\/\/x\.com\/([A-Za-z0-9_]{1,15})\/status\/(\d{1,32})(?:[/?#].*)?$/);
  if (!match)
    throw new Error(
        'VALIDATION_ERROR: Supply a full X postUrl or a loaded postId.');
  const tab = await context.newPage();
  try {
    await tab.goto(
        `https://x.com/${match[1]}/status/${match[2]}`,
        {waitUntil: 'domcontentloaded'});
    return await tab.evaluate(x_get_post_thread, {...input, postId: match[2]});
  } finally {
    await tab.close();
  }
}
async function publishXArticleInTemporaryPage(input) {
  // The page callback independently validates all text and confirm=true.
  if (input?.confirm !== true)
    throw new Error('VALIDATION_ERROR: confirm=true is required.');
  const tab = await context.newPage();
  try {
    await tab.goto(
        'https://x.com/compose/articles', {waitUntil: 'domcontentloaded'});
    return await tab.evaluate(x_publish_article, input);
  } finally {
    await tab.close();
  }
}
