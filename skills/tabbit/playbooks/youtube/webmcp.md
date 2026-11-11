# YouTube: source conversions

读取首页信息流，以及视频详情、下载地址、评论和字幕。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: www.youtube.com, m.youtube.com. Routes: /, /watch?v=*.

- 首页按需加载，单次最多读取 200 个视频
- 首页不展示点赞数时返回 null
- 只返回播放器已提供的直接下载地址，不破解签名、DRM 或付费内容
- 评论单次最多 200 条

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `youtube_get_home_feed`

滚动并读取 YouTube 首页当前信息流中的视频、Shorts、封面、标题、频道、时长、观看数和发布时间。

播放列表、课程等合集卡片不作为视频返回；缺失或非时钟格式的时长返回
`durationSeconds: null`，显示 `0:00` 时返回 `0`。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "maxVideos": {
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

### `youtube_get_video_download_urls`

读取当前播放器直接提供的临时媒体地址和格式信息；不会破解签名或 DRM。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "all",
        "muxed",
        "video",
        "audio"
      ],
      "default": "all"
    },
    "maxResults": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 50
    }
  },
  "additionalProperties": false
}
```

### `youtube_get_video_comments`

自动加载评论区并分页读取评论；默认 20 条，单次最多 200 条。

顶层评论的 `replyCount` 来自该评论线程的回复按钮；按钮存在但数量不可读时
返回 `null`。展开的回复单独返回，不把回复正文当作数量。

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

### `youtube_get_video_details`

读取标题、完整描述、频道、时长、观看数、点赞数、发布时间、分类、封面和字幕轨等信息。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### `youtube_get_subtitle_file`

下载当前视频已有字幕；默认选择第一条字幕并导出为 SRT。

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
  "additionalProperties": false
}
```


## Saving extracted assets

Copy the shared [media-assets.js](../media-assets.js) Nodejs recipe alongside
the selected callback, then call `saveMediaAssets(page, result.assets,
{site: "youtube", sourceOrigin})`. Capture `sourceOrigin = new URL(page.url()).origin`
before extraction and reject `result.error` first. This uses existing `page.fetch`
and `artifactPath`; the recipe does not execute automatically. It converts JSON/XML
captions to SRT/VTT/JSON, enforces the source CDN allowlists and origin checks,
and never overwrites an artifact. CORS/session failures remain visible.
The browser fetch transport caps responses at 8 MiB (subtitles at 5 MiB);
larger audio/video requires a native site download and is not supported by this
recipe. Media URLs alone are not successful downloads. Partial batches can leave
earlier saved files when a later asset fails; inspect those before retrying.
