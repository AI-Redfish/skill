# Scrapling 0.5.1 高级用法

> 何时读：需求涉及异步会话、browser 网络请求历史、自定义 Spider、代理、限流或 checkpoint 时加载。
> 适用范围：auto-crawler；API 以 Scrapling 0.5.1 官方文档及对应安装签名为准。

## 选择 Fetcher

- `Fetcher.get(url, ...)`：同步 HTTP，请求快；无 JavaScript。
- `AsyncFetcher.get(url, ...)`：异步 HTTP。
- `FetcherSession(...)`：多个 HTTP 请求共用会话。
- `StealthyFetcher.fetch(url, ...)`：Patchright 浏览器，支持 JS 与隐身选项。
- `AsyncStealthySession(...)`：Spider 使用的异步浏览器会话。
- Scrapling 0.5 移除了 `DynamicFetcher`、`DynamicSession` 和普通 Playwright 后端；用 Stealthy 对应类。
- 0.5.1 的 CDP 连接使用 `RemoteSession` / `AsyncRemoteSession`，不再给 `StealthySession` 传 `cdp_url`。

安装浏览器组件：

```bash
uv run --with "scrapling[fetchers]==0.5.1" scrapling install
```

在浏览器模式中按需使用 `headless`、`wait_selector`、`network_idle`、`page_action`。
`solve_cloudflare=True` 只用于用户明确授权的目标，不保证成功；默认不启用。
浏览器退出时清理用户临时状态，避免复用用户登录信息。

## 解析选择器

```python
from scrapling.fetchers import Fetcher

page = Fetcher.get("https://quotes.toscrape.com/")
texts = page.css(".quote .text::text").getall()
first = page.css(".quote .author::text").get("")
links = page.css("a::attr(href)").getall()
markdown = page.markdown(main_content_only=True)
```

Scrapling CSS 支持 `::text` 与 `::attr(name)`。XPath 用 `page.xpath(...)`。
结果是空列表时，不应声称采集成功；先核对页面、访问授权、robots 与选择器。
`Response` 继承 Selector，常用属性包括 `status`、`url`、`headers`、`text`、`html_content`、`body`。

## 定制 Spider

```python
from scrapling.spiders import Response, Spider

class QuotesSpider(Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/"]
    allowed_domains = {"quotes.toscrape.com"}
    robots_txt_obey = True
    concurrent_requests = 2
    concurrent_requests_per_domain = 2
    download_delay = 1.0
    autothrottle_enabled = True

    async def parse(self, response: Response):
        for quote in response.css(".quote"):
            yield {
                "text": quote.css(".text::text").get(""),
                "author": quote.css(".author::text").get(""),
                "_url": response.url,
            }
        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

result = QuotesSpider().start()
result.items.to_csv("quotes.csv")
```

- `parse` 必須是 async generator，yield item 或 `response.follow()` 請求。
- `allowed_domains` 不代表每個請求都免檢查；審查自定義 callback 中所有 URL。
- `robots_txt_obey=True` 是正式抓取的默認策略。robots.txt 抓取失敗時，該網域會被阻止。
- 初始 `concurrent_requests=4`、每域值 `0`、delay `0`；顯式設定較低並發與非零 delay。
- AutoThrottle 可增加延遲；robots 的 Crawl-delay / Request-rate 也可能增加延遲。
- 0.5 默认不自动重试被判定为 blocked 的请求。要增加 retry，先向用户说明站点规则并获得确认。
- 结果在 `CrawlResult.items`。`.to_json()`、`.to_jsonl()`、`.to_csv()`、`.to_xml()` 自动建父目录；导出路径需指向工作目录 `.agents/out/YYYYMMDD/auto-crawler/`。
- Spider 会把 items 放内存。超大任务改用 streaming/ItemPipeline；先查官方 Advanced features 文档，勿猜 API。
- checkpoint 由 `Spider(crawldir=..., interval=...)` 开启；恢复机制必须先用可重复公共样本验证。checkpoint 属运行数据，放 `.agents/out/YYYYMMDD/auto-crawler/checkpoints/`。

## 代理、认证与日志

- 统一脚本只从进程环境读取 `AUTO_CRAWLER_PROXY`。不读取 `.env`，不写入代码或日志。
- 定制 Spider 可覆写 `configure_sessions(manager)`，添加 `FetcherSession` 或 `AsyncStealthySession`。
- 代理需要用户名/密码时，先单独确认存储方式；不把凭据写入 URL、命令历史或报告。
- 使用 HTTP Basic、Cookie 或网站登录前，确认用户授权；不从本机浏览器自动读取 cookie。

## 官方文档

- [Fetcher 选择](https://scrapling.readthedocs.io/en/latest/fetching/choosing.html)
- [Fetcher API](https://scrapling.readthedocs.io/en/latest/api-reference/fetchers.html)
- [Response API](https://scrapling.readthedocs.io/en/latest/api-reference/response.html)
- [选择器](https://scrapling.readthedocs.io/en/latest/parsing/selection.html)
- [Spider 入门](https://scrapling.readthedocs.io/en/latest/spiders/getting-started.html)
- [v0.5 迁移](https://scrapling.readthedocs.io/en/latest/migrating-to-v0.5.html)
- [CLI 提取](https://scrapling.readthedocs.io/en/latest/cli/extract-commands.html)
