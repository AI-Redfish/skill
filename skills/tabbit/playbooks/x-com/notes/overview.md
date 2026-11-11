# X (Twitter) Overview

## Page structure
- Main navigation: Left sidebar `[data-testid="AppTabBar"]`
- Timeline content: `[data-testid="primaryColumn"]`
- Tweet items: `[data-testid="tweet"]` — each contains text, author, timestamp
- Compose box: `[data-testid="twaCreateTweetText"]`

## Anti-click-wrap
- Tweet text is inside `[data-testid="tweetText"]`, click target is `[data-testid="tweet"]`
- Actions (reply/retweet/like) are inside `div[role="group"]` at the bottom of each tweet card

## Common selectors
- Tweet text: `[data-testid="tweetText"]`
- Author name: `[data-testid="User-Name"] span`
- Timestamp: `time` element with `datetime` attribute
- Search input: `[data-testid="SearchBox_Search_Input"]`
- User search results: `[data-testid="primaryColumn"] [data-testid="UserCell"]`; wait for a result or `[data-testid="emptyState"]`. UserCell also appears in sidebar recommendations, so scope it to the primary column. Read display name and @handle from the card's profile links; follower counts are not exposed.
- Compose textarea: `[data-testid="twaCreateTweetTextarea"]`

## Using the files

Read each Node recipe into a submission with the existing `page` binding:

- `tools/search-users.js`: `await searchUsers({query: "browser", maxResults: 25})`.
  Limit defaults to 25, clamped to 1–100. Returns `{name, handle, followers}` from
  loaded primary-column user cards, excluding cards without an @handle. Followers
  are always `""` (unavailable), never inferred as zero.
- `tools/timeline.js`: `await getTimelinePosts({maxPosts: 50})` on the current
  timeline. Limit defaults to 50, clamped to 1–100. Returns text, author, profile
  path in `handle`, and timestamp from currently rendered posts. It does not wait
  for readiness or scroll; an empty array cannot distinguish loading, login, or
  an empty timeline. Inspect readiness before invoking it.
- `browser-tools/extract-post.js`: pass the function expression to `page.evaluate`.
  It selects a focused tweet article, falling back to the first rendered article;
  focus on a descendant is not treated as article focus. No arguments. Returns
  text, author, and timestamp, or `{error: "no active tweet found"}`.

Missing optional post fields are `""`. None of these files retrieves a complete
history or paginates. Search waits for a visible card or explicit empty state;
login/blocked/not-ready pages may time out and must not be reported as empty results.
