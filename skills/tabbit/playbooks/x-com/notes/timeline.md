# X Timeline Navigation

## Scrolling timeline
- Timeline is inside `[data-testid="primaryColumn"]`
- Posts load lazily as you scroll — use Playwright scrolling and observe newly loaded posts before continuing
- Virtual list: DOM only renders visible articles + buffer

## Extracting posts
- Query `[data-testid="tweet"]` for post elements
- Each post has `[data-testid="tweetText"]` for content
- Author info at `[data-testid="User-Name"]`
- Always extract in one pass via browser-side closure

## Pinned post
- Pinned post is the first `[data-testid="tweet"]` in timeline
- Identify the visible pinned label before filtering a post; position alone does not prove it is pinned
