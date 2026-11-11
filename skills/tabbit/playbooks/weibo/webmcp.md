# 微博: source conversions

读取首页信息流、帖子与评论、博主最新帖子，并发布或互动。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: weibo.com, www.weibo.com. Routes: /, /mygroups?gid=*, /u/{uid}, /{uid}/{mid}.

- 只处理当前登录态可见内容
- 信息流与评论按需加载，达到调用上限时标记 truncated
- 发布、回复、引用和转帖必须传 confirm=true
- 点赞只会确保已点赞，不会取消已有点赞
- 不读取或导出 Cookie、CSRF token 或内部鉴权头

Read functions may scroll, expand sections, or paginate. Post text expansion uses
the rendered text’s `展开` control; video-player `点击展开` controls are excluded. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `weibo_get_home_feed`

滚动并读取当前首页所选信息流中观察到的全部微博，保留正文、媒体、链接和互动数。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "maxPosts": {
      "type": "integer",
      "minimum": 1,
      "maximum": 200,
      "default": 100
    },
    "maxScrolls": {
      "type": "integer",
      "minimum": 0,
      "maximum": 50,
      "default": 20
    }
  },
  "additionalProperties": false
}
```

### `weibo_get_post_with_comments`

在首页或微博详情页读取目标微博的完整可见正文、媒体、评论和回复。

`comments.complete` 仅在看到评论结束标记且未达到数量上限时为 true。
`includeReplies=true` 时，仍有回复展开入口也会标记结果不完整；列表停止变化不代表回复已全部加载。
`includeReplies=false` 只判断顶层评论是否完整。展开入口本身不计为评论。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^[A-Za-z0-9]{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$"
    },
    "maxComments": {
      "type": "integer",
      "minimum": 1,
      "maximum": 500,
      "default": 200
    },
    "maxScrolls": {
      "type": "integer",
      "minimum": 0,
      "maximum": 50,
      "default": 20
    },
    "includeReplies": {
      "type": "boolean",
      "default": true
    }
  },
  "additionalProperties": false
}
```

### `weibo_get_profile_latest_posts`

读取当前博主主页最新发布的 6 条非置顶微博；不把旧置顶微博计入最新列表。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `weibo_publish_post`

在微博首页发布单条微博；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 5000
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "text",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `weibo_like_post`

点赞目标微博；如果已经点赞则不重复操作，也不会取消点赞。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^[A-Za-z0-9]{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$"
    }
  },
  "additionalProperties": false
}
```

### `weibo_reply_post`

回复目标微博；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^[A-Za-z0-9]{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$"
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 5000
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "text",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `weibo_quote_post`

带文字转发目标微博；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^[A-Za-z0-9]{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$"
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 5000
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "text",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `weibo_repost_post`

转发目标微博；可选自定义转发文字，必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^[A-Za-z0-9]{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/(?:www\\.)?weibo\\.com\\/\\d{1,20}\\/[A-Za-z0-9]{1,32}(?:[?#].*)?$"
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 5000
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "confirm"
  ],
  "additionalProperties": false
}
```
