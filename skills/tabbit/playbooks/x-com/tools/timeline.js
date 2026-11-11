function boundedInteger(value, fallback, max) {
  const number = value === undefined ? fallback : Number(value);
  if (!Number.isFinite(number))
    return fallback;
  return Math.max(1, Math.min(max, Math.trunc(number)));
}

async function getTimelinePosts(args = {}) {
  const maxPosts = boundedInteger(args.maxPosts, 50, 100);

  const posts = await page.evaluate(String.raw`(() => {
    const articles = [...document.querySelectorAll('[data-testid="tweet"]')]
    return articles.slice(0, ${maxPosts}).map(el => {
      const time = [...el.querySelectorAll('time')].find(node =>
        !node.closest('div[role="link"]') &&
        /^\/[A-Za-z0-9_]{1,15}\/status\/\d+(?:[?#]|$)/.test(node.closest('a[href]')?.getAttribute('href') || ''));
      return {
        text: el.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || '',
        author: el.querySelector('[data-testid="User-Name"]')?.querySelector('span')?.innerText?.trim() || '',
        handle: el.querySelector('[data-testid="User-Name"]')?.querySelector('a')?.getAttribute('href') || '',
        timestamp: time?.getAttribute('datetime') || '',
      };
    })
  })()`);

  return posts;
}
