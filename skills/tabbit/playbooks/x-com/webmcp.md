# X: source conversions

读取主页信息流、帖子对话和博主最新帖子，并发布或互动。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: x.com. Routes: /home, /{handle}, /{handle}/status/{id}.

- 只处理当前登录态可见内容
- 信息流和回复按需加载，最多返回 200 条并标记 truncated
- 主页读取帖子对话时会在后台临时打开详情页
- 发布、回复、引用和转帖必须传 confirm=true
- 点赞只会确保已点赞，不会取消已有点赞
- 不读取或导出 Cookie、CSRF token 或内部鉴权头

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `x_get_home_feed`

滚动并读取当前主页所选时间线中已观察到的帖子，保留引用内容、媒体、链接和互动数。

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

### `x_get_post_thread`

在主页或帖子详情页读取目标帖、可见上下文、回复和每条帖子内嵌的引用内容。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^\\d{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+"
    },
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

### `x_get_profile_latest_posts`

读取当前博主主页最新发布的 6 个非置顶帖子；不把旧置顶帖计入最新列表。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `x_publish_post`

在 X 主页发布单个帖子；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 25000
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

### `x_publish_thread`

在 X 主页按顺序发布 2–25 条组成的 Thread；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "posts": {
      "type": "array",
      "minItems": 2,
      "maxItems": 25,
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 25000
      }
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "posts",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `x_publish_article`

在 X 主页打开文章编辑器并发布标题和正文；必须传 confirm=true，且账号需有文章权限。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "minLength": 1,
      "maxLength": 200
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100000
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "title",
    "content",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `x_like_post`

点赞目标帖子；如果已经点赞则不重复操作，也不会取消点赞。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^\\d{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+"
    }
  },
  "additionalProperties": false
}
```

### `x_reply_post`

回复目标帖子；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^\\d{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+"
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 25000
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

### `x_quote_post`

带文字引用目标帖子并发布；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^\\d{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+"
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 25000
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

### `x_repost_post`

转帖目标帖子；如果已经转帖则不重复操作，必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "postId": {
      "type": "string",
      "pattern": "^\\d{1,32}$"
    },
    "postUrl": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2048,
      "pattern": "^https:\\/\\/x\\.com\\/[A-Za-z0-9_]{1,15}\\/status\\/\\d+"
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


## Temporary-page workflows

From `/home`, use `readXThreadInTemporaryPage(input)` or
`publishXArticleInTemporaryPage(input)` in [temporary-pages.js](temporary-pages.js),
after copying webmcp.js into the same nodejs program. They reproduce the source
background temporary-tab behavior with `context.newPage()` and close only the
created page. Inspect the returned result before retrying write operations.
