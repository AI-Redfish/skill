async function(args) {
  const el = document.querySelector('[data-testid="tweet"]:focus') ||
      document.querySelector('[data-testid="tweet"]');
  if (!el)
    return {error: 'no active tweet found'};
  const time = [...el.querySelectorAll('time')].find(
      node => !node.closest('div[role="link"]') &&
          /^\/[A-Za-z0-9_]{1,15}\/status\/\d+(?:[?#]|$)/.test(
              node.closest('a[href]')?.getAttribute('href') || ''));
  return {
    text:
        el.querySelector('[data-testid="tweetText"]')?.innerText?.trim() || '',
    author:
        el.querySelector('[data-testid="User-Name"] span')?.innerText?.trim() ||
        '',
    timestamp: time?.getAttribute('datetime') || '',
  };
}
