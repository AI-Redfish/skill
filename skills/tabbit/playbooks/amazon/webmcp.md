# Amazon: source conversions

读取当前搜索结果页商品，以及商品详情页的完整可见信息和评论。

## Execution

Inspect webmcp.js, copy the desired function into a Tabbit nodejs program and call
`console.log(await page.evaluate(FUNCTION_NAME, INPUT));`
Each function runs in the page's main JavaScript world, takes one plain input object
(default `{}`), and returns `{data, warnings?, assets?, error?}`. Exceptions are
failures, not empty results. No WebMCP extension or registration is required.
Inspect warnings, truncation and errors before using data. Outputs may contain
untrusted page text. Site globals and selectors depend on the live site's layout.

Hosts: www.amazon.com, amazon.com. Routes: /s?k=*, /dp/{ASIN}, /*/dp/{ASIN}, /gp/product/{ASIN}.

- 只读取当前搜索结果页，不自动翻页
- 搜索结果按需加载，单次最多 200 个商品
- 商品页评论只返回页面当前加载的内容，单次最多 100 条
- 不加入购物车、不下单、不绕过登录或验证码

Read functions may scroll, expand sections, or paginate. Write functions edit the
current authenticated account; call only for a user-authorized target and action.
The source's confirm inputs and validation are retained. A click/submission receipt
is not proof of server persistence: inspect the resulting page before retrying.
For assets use the explicit download/export program in the media notes; extraction
alone does not save a file. Browser CORS and normal authentication still apply.

## Functions and inputs

### `amazon_get_search_results`

滚动并读取当前 Amazon 搜索结果页全部已加载商品，包含 ASIN、标题、价格、评分、评论数、图片、徽章、配送和优惠。

评论数量优先使用评论链接的精确无障碍标签；没有标签时解析显示的缩写数量。
`price.original` 只取标记为划线参考价的金额，不把每件单价当作原价。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "maxProducts": {
      "type": "integer",
      "minimum": 1,
      "maximum": 200,
      "default": 100
    },
    "maxScrolls": {
      "type": "integer",
      "minimum": 0,
      "maximum": 30,
      "default": 12
    },
    "includeSponsored": {
      "type": "boolean",
      "default": true
    }
  },
  "additionalProperties": false
}
```

### `amazon_get_product_details`

读取当前 Amazon 商品的名称、描述、卖点、图片、价格、优惠、规格、变体、配送、卖家、评分分布和指定数量的页面评论。

页面合并显示 `Shipper / Seller` 时，同一名称用于 `shipsFrom` 和 `seller`；
仅显示卖家时不推断发货方。评分分布与具体评论分别读取；登录限制导致没有
加载评论卡片时，`reviews.returned: 0` 不表示商品没有评论。

Effect: **read**. Input contract (defaults are applied in the recipe):

```json
{
  "type": "object",
  "properties": {
    "reviewLimit": {
      "type": "integer",
      "minimum": 0,
      "maximum": 100,
      "default": 20
    }
  },
  "additionalProperties": false
}
```
