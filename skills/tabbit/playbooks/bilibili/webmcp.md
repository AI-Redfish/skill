# Bilibili: source conversions

读取视频信息、字幕和评论，下载浏览器可直接访问的媒体。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: www.bilibili.com. Routes: /video/BV*, /video/av*.

- 不绕过登录、DRM 或地区限制
- 分轨媒体不自动合并
- 评论单次最多 200 条

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `bilibili_get_video_context`

读取当前 Bilibili 视频的标题、作者、时长、字幕和可用格式。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `bilibili_download_video`

下载当前页面可直接取得的音视频合一格式；会写入本地文件。

Effect: **download**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "quality": {
      "type": "string",
      "maxLength": 32
    }
  },
  "additionalProperties": false
}
```

### `bilibili_export_subtitles`

按语言导出当前视频已有字幕；会写入本地文件。

Effect: **export**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "language": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32
    },
    "format": {
      "type": "string",
      "enum": [
        "srt",
        "vtt",
        "json"
      ],
      "default": "srt"
    }
  },
  "required": [
    "language"
  ],
  "additionalProperties": false
}
```

### `bilibili_extract_comments`

分页读取当前视频评论，单次最多 200 条。

Reads mounted comments only; it does not scroll, expand replies, or request later
site pages. `cursor` is an offset into the current loaded list. Reuse it with the
same `includeReplies` setting while the list order is unchanged. `hasMore` and
`truncated` describe remaining entries in that list, not site-wide completeness.
With `includeReplies: true`, already rendered replies follow their parent in
`items` and include `parentId`; replies count toward `limit`. Unavailable counts
and timestamps are `null`. IDs fall back to page-local positions when the page
does not expose an ID.


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
{site: "bilibili", sourceOrigin})`. Capture `sourceOrigin = new URL(page.url()).origin`
before extraction and reject `result.error` first. This uses existing `page.fetch`
and `artifactPath`; the recipe does not execute automatically. It converts JSON/XML
captions to SRT/VTT/JSON, enforces the source CDN allowlists and origin checks,
and never overwrites an artifact. CORS/session failures remain visible.
The browser fetch transport caps responses at 8 MiB (subtitles at 5 MiB);
larger audio/video requires a native site download and is not supported by this
recipe. Media URLs alone are not successful downloads. Partial batches can leave
earlier saved files when a later asset fails; inspect those before retrying.
