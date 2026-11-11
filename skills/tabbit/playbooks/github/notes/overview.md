# GitHub Overview

## Page structure
- Navigation: Header with logo, search, notifications
- Repository page: `[data-view-component]` wraps the repo body
- File tree: `#repo-files-toc` or `Box-row`
- Search results: `main .search-title a`; `#search-results-count` reports `0 results` for an empty search.
- Issues: `[data-testid="issue-pr-title-link"]` links inside list items; `.blankslate-heading` says `No results` for an empty list.

## Navigation patterns
- Repo URL: `https://github.com/{owner}/{repo}`
- Search URL: `https://github.com/search?q={query}&type=repositories`
- Issues URL: `https://github.com/{owner}/{repo}/issues`
- PR URL: `https://github.com/{owner}/{repo}/pulls`

## Common selectors
- Repo name: last link in `[aria-label="Breadcrumbs"]`
- Counts: `a[href$="/stargazers"]`, `a[href$="/forks"]`
- Language: `a[href*="/search?l="] [itemprop="keywords"]`
- Description: paragraph beside the `About` heading

Wait for results or an explicit empty state before extracting. The recipes read
only the loaded page. Before injecting repo stats, wait for About and the
Languages list, which loads separately. Missing fields return `""`,
which does not prove absence while a section is still loading.

## Using the files

Read each Node recipe into a submission with the existing `page` binding:

- `tools/search-repos.js`: `await searchRepos({query: "browser", maxResults: 25})`.
  The limit defaults to 25 and is clamped to 1–100. Returns `{name, owner, stars, link}`;
  links are repository paths and stars are displayed strings, including `"0"`.
- `tools/open-issues.js`: `await getOpenIssues({owner: "example", repo: "project"})`.
  Returns `{title, number}` for the loaded open-issue list, not all pages.
- `browser-tools/repo-stats.js`: pass the function expression to `page.evaluate`
  on a loaded repository page. No arguments; returns name, description, stars,
  forks, and primary language. Missing fields are `""`, distinct from `"0"` counts.

Neither Node recipe paginates. Readiness recognizes the documented English empty
states; other layouts/locales, login walls, and blocked pages may time out. Do not
report a timeout as zero results. Stats depend on separately loaded sections and
English About/count labels; an empty language is unavailable, not proof of no code.
