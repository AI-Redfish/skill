# Google Search Overview

## Page structure
- Search input: `textarea[name="q"]` or `input[name="q"]`
- Results container: `div#search`
- Result title/link: `#search h3` inside `a[href]`
- Result scope: nearest `[data-snc]` or `.tF2Cxc`; avoids neighboring results and sitelinks
- Result snippet: `[data-sncf]` or `.VwiC3b` within that scope

## Navigation
- Use `page.goto` with `https://www.google.com/search?q=...`
- Wait for `#search` to be attached before extraction; it can be hidden when empty. Consent or CAPTCHA pages require user action
- URLs are the page's actual links and may be Google redirects
- Pagination links at bottom: `a[href*="/search?q="]`

## Common selectors
- Query box: `textarea[name="q"]`
- Search button: `input[type="submit"]`
- Auto-complete dropdown/items: `[role="listbox"] [role="option"]`
- After typing, wait for visible options before evaluating the autocomplete snippet; hidden options are ignored

## Using the files

Read `tools/search-extract.js` into your Node submission with the existing `page`
binding, then call `await searchAndExtract({query: "browser testing", maxResults: 10})`.
The limit defaults to 10 and is clamped to 1–100. Results are `{title, url, snippet}`;
missing snippets are `""`. Only visible organic headings in supported result blocks
on the loaded page are included, deduplicated by URL. No pagination occurs.
`#search` attachment alone does not establish that asynchronous results are complete.

`browser-tools/autocomplete.js` is a function expression for `page.evaluate` on
the current page, after typing and waiting for suggestions. It takes no arguments
and returns unique visible suggestion strings. An empty array only means no
supported visible options were found at that moment.
