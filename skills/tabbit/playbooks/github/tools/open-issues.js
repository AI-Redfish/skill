const OWNER_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const REPO_RE = /^[A-Za-z0-9._-]+$/;

async function getOpenIssues(args = {}) {
  const owner = args.owner || '';
  const repo = args.repo || '';
  if (!OWNER_RE.test(owner) || !REPO_RE.test(repo) || repo === '.' ||
      repo === '..') {
    throw new Error('valid GitHub owner and repo are required');
  }

  await page.goto(
      `https://github.com/${encodeURIComponent(owner)}/${
          encodeURIComponent(repo)}/issues?q=is%3Aissue%20state%3Aopen`,
      {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(
      () =>
          document.querySelector('main [data-testid="issue-pr-title-link"]') ||
          document.querySelector('main .blankslate-heading')
                  ?.textContent.trim() === 'No results');

  return await page.evaluate(
      () => [...document.querySelectorAll(
                 'main [data-testid="issue-pr-title-link"]')]
                .map(a => ({
                       title: a.innerText.trim(),
                       number: a.pathname.match(/\/issues\/(\d+)$/)?.[1] || '',
                     })));
}
