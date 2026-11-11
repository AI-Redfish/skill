# 淘宝: source conversions

读取淘宝搜索结果，以及淘宝/天猫商品详情、优惠、规格、图文详情和指定数量的评价。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: s.taobao.com, item.taobao.com, detail.tmall.com. Routes: /search?q=*, /item.htm?id=*.

- 只读取当前登录态可见内容
- 搜索结果只覆盖当前结果页，不自动翻页
- 商品卡片按 itemId 去重并标记完整性
- 详情页评价默认读取 20 条、单次最多 100 条
- 不加入购物车、不领券、不购买、不发布评价

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `taobao_get_search_results`

滚动并读取当前淘宝搜索结果页的全部商品卡片，返回标题、价格、销量、店铺、地区、标签、图片和规范商品链接。

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

### `taobao_get_product_details`

读取当前淘宝或天猫商品的名称、价格、销量、店铺、参数、规格、库存、优惠、保障、配送、媒体、图文详情和指定数量的评价。

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
      "default": 10
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
