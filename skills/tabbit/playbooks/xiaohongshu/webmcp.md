# 小红书: source conversions

读取笔记正文、图片和可见评论。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: www.xiaohongshu.com. Routes: /explore/*, /discovery/item/*.

- 不处理登录墙或验证码
- 图片下载单次最多 20 张
- 评论单次最多 200 条

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `xiaohongshu_get_note_context`

读取当前笔记标题、作者、正文摘要和图片数量。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `xiaohongshu_get_post_images`

按原顺序返回图片；可选下载，下载时会写入本地文件。

Effect: **download**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "download": {
      "type": "boolean",
      "default": false
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20,
      "default": 20
    }
  },
  "additionalProperties": false
}
```

### `xiaohongshu_extract_comments`

分页读取当前笔记可见评论，单次最多 200 条。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 200,
      "default": 20
    },
    "cursor": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 512
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "includeReplies": {
      "type": "boolean",
      "default": false
    }
  },
  "additionalProperties": false
}
```


## Saving extracted assets

Copy the shared [media-assets.js](../media-assets.js) Nodejs recipe alongside
the selected callback, then call `saveMediaAssets(page, result.assets,
{site: "xiaohongshu", sourceOrigin})`. Capture `sourceOrigin = new URL(page.url()).origin`
before extraction and reject `result.error` first. This uses existing `page.fetch`
and `artifactPath`; the recipe does not execute automatically. It converts JSON/XML
captions to SRT/VTT/JSON, enforces the source CDN allowlists and origin checks,
and never overwrites an artifact. CORS/session failures remain visible.
The browser fetch transport caps responses at 8 MiB (subtitles at 5 MiB);
larger audio/video requires a native site download and is not supported by this
recipe. Media URLs alone are not successful downloads. Partial batches can leave
earlier saved files when a later asset fails; inspect those before retrying.
