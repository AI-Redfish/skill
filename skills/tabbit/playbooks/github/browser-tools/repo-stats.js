async function(args) {
  const about = [...document.querySelectorAll('h2')]
                    .find(h => h.textContent.trim() === 'About')
                    ?.parentElement;
  return {
    stars: document.querySelector('a[href$="/stargazers"]')
               ?.innerText.replace(/\s*stars?$/i, '')
               .trim() ||
        '',
    forks: document.querySelector('a[href$="/forks"]')
               ?.innerText.replace(/\s*forks?$/i, '')
               .trim() ||
        '',
    language:
        document.querySelector('a[href*="/search?l="] [itemprop="keywords"]')
            ?.innerText.trim() ||
        '',
    name: document.querySelector('[aria-label="Breadcrumbs"] li:last-child a')
              ?.innerText.trim() ||
        '',
    description: about?.querySelector('p')?.innerText.trim() || '',
  };
}
