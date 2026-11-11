# 京东: source conversions

读取京东搜索结果，以及商品名称、价格、优惠、规格、图文详情和指定数量的评价。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: search.jd.com, item.jd.com. Routes: /Search?keyword=*, /{skuId}.html.

- 只读取当前登录态可见内容
- 搜索结果只覆盖当前结果页，不自动翻页
- 商品卡片按 SKU 去重并标记完整性
- `sponsored` 根据商品卡片上可见的“广告”标记判定；商品标题提及广告不算投放标记
- 详情页评价默认读取 20 条、单次最多 100 条
- 不加入购物车、不领券、不购买、不发布评价

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `jingdong_get_search_results`

滚动并读取当前京东搜索结果页的商品卡片，返回名称、价格、优惠、销量、评价、店铺、标签、图片和规范商品链接。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "maxItems": {
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

### `jingdong_get_product_details`

读取当前京东商品的名称、价格、店铺、参数、规格、优惠、服务、配送、媒体、图文详情和指定数量的评价。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "reviewLimit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 20
    },
    "maxReviewScrolls": {
      "type": "integer",
      "minimum": 0,
      "maximum": 30,
      "default": 12
    },
    "includeDetailImages": {
      "type": "boolean",
      "default": true
    },
    "maxDetailImages": {
      "type": "integer",
      "minimum": 1,
      "maximum": 200,
      "default": 100
    }
  },
  "additionalProperties": false
}
```
