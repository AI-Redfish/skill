# 闲鱼: source conversions

读取搜索结果和商品详情，并在明确确认后发布商品或回复当前会话。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: www.goofish.com. Routes: /search?q=*, /item?id=*, /publish, /im.

- 只处理当前登录态可见内容
- 搜索结果最多读取 50 页或 1000 件商品并按 itemId 去重
- 商品详情评论最多 100 条；网页版无评论区时明确返回 unavailable
- 发布和回复必须传 confirm=true
- 回复前必须核对当前会话收件人
- 不读取或导出 Cookie、鉴权头或私聊列表

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `goofish_get_search_results`

分页读取当前闲鱼搜索结果，返回商品名称、描述、价格、图片、标签、想要数、卖家和规范链接。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "maxItems": {
      "type": "integer",
      "minimum": 1,
      "maximum": 1000,
      "default": 1000
    },
    "maxPages": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "default": 50
    }
  },
  "additionalProperties": false
}
```

### `goofish_get_item_details`

读取当前商品的价格、描述、规格、优惠/服务、图片、卖家、想要数、浏览数和指定数量的可见评论。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "commentLimit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 20
    }
  },
  "additionalProperties": false
}
```

### `goofish_publish_item`

填写图片、描述、价格、发货和所在地并发布；必须传 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "images": {
      "type": "array",
      "minItems": 1,
      "maxItems": 9,
      "items": {
        "type": "object",
        "properties": {
          "filename": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255
          },
          "mimeType": {
            "type": "string",
            "pattern": "^image\\/(?:jpeg|png|webp|gif)$"
          },
          "base64": {
            "type": "string",
            "minLength": 1,
            "maxLength": 14000000
          }
        },
        "required": [
          "filename",
          "mimeType",
          "base64"
        ],
        "additionalProperties": false
      }
    },
    "description": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1500
    },
    "price": {
      "type": "string",
      "pattern": "^(?:0|[1-9]\\d{0,7})(?:\\.\\d{1,2})?$"
    },
    "originalPrice": {
      "type": "string",
      "pattern": "^(?:0|[1-9]\\d{0,7})(?:\\.\\d{1,2})?$"
    },
    "shipping": {
      "type": "string",
      "enum": [
        "free",
        "distance",
        "fixed",
        "none"
      ],
      "default": "free"
    },
    "shippingFee": {
      "type": "string",
      "pattern": "^(?:0|[1-9]\\d{0,5})(?:\\.\\d{1,2})?$"
    },
    "pickup": {
      "type": "boolean",
      "default": false
    },
    "location": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "images",
    "description",
    "price",
    "location",
    "confirm"
  ],
  "additionalProperties": false
}
```

### `goofish_reply_message`

核对当前会话收件人后发送回复；必须传 recipient 和 confirm=true。

Effect: **write**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "recipient": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2000
    },
    "confirm": {
      "type": "boolean",
      "enum": [
        true
      ]
    }
  },
  "required": [
    "recipient",
    "text",
    "confirm"
  ],
  "additionalProperties": false
}
```


## Preserve the current search

Use `readGoofishSearchInTemporaryPage(input)` from
[temporary-page.js](temporary-page.js), with webmcp.js in the same nodejs program,
to reproduce the source background workflow. The callback clicks pagination;
the wrapper keeps those changes in a temporary page and closes it in `finally`.
