async function searchUsers(args = {}) {
  const query = args.query || '';
  const requested = Number(args.maxResults ?? 25);
  const maxResults = Number.isFinite(requested) ?
      Math.max(1, Math.min(100, Math.trunc(requested))) :
      25;
  if (!query)
    throw new Error('search query is required');

  await page.goto(
      `https://x.com/search?f=user&q=${encodeURIComponent(query)}`,
      {waitUntil: 'load'});

  const results = page.locator('[data-testid="primaryColumn"]');
  await results.locator('[data-testid="UserCell"], [data-testid="emptyState"]')
      .first()
      .waitFor({state: 'visible'});
  return await results.locator('[data-testid="UserCell"]')
      .evaluateAll(
          (cells, limit) =>
              cells
                  .map(el => {
                    const links = [...el.querySelectorAll(
                        'a[role="link"]:not([aria-hidden="true"])')];
                    return {
                      name: links[0]?.innerText?.trim() || '',
                      handle: links.map(a => a.innerText.trim())
                                  .find(text => /^@\w+$/.test(text)) ||
                          '',
                      // Search cards do not expose follower counts.
                      followers: '',
                    };
                  })
                  .filter(user => user.handle)
                  .slice(0, limit),
          maxResults);
}
