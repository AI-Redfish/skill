# 反检测设计：为什么这样用 Playwright（电子税务局场景）

本文是 SKILL.md「反检测红线」的完整依据。核心结论一句话：
**不启动 Playwright 自带的 Chromium，而是附着（CDP attach）到本机真实 Chrome/Edge，
headed 运行 + 拟人化操作。**

## 1. 站点防护实测（2025-11）

- `curl https://etax.hubei.chinatax.gov.cn:8443/` → **HTTP 412**（无 JS 执行能力直接拒绝）
  → 该站部署动态 WAF（瑞数类，特征：JS 质询生成动态 Cookie + 环境检测）
- 推论 1：requests/curl/httpx 等纯 HTTP 方案**不可行**，一切操作必须在真实浏览器内完成
- 推论 2：下载发票 PDF 必须走浏览器下载事件（`expect_download`），
  不能用 API request 直拉（动态 Cookie 不在，依旧 412）

## 2. 三层方案（默认 A）

### 方案 A（默认）：CDP 附着真实浏览器

```bash
# 1. 启动本机真实 Chrome：专用 profile + 调试端口（browser_session.py 已封装）
chrome.exe --remote-debugging-port=9333 --user-data-dir=<skill_dir>/profiles/chrome \
  --no-first-run --no-default-browser-check
# 2. Playwright 附着，复用默认上下文（拿到全部真实 Cookie）
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
page = browser.contexts[0].new_page()
```

| 检测面 | 方案 A 表现 |
|---|---|
| `navigator.webdriver` | `false`（Playwright 自启会注入自动化标记；CDP 附着不会） |
| `--enable-automation` 开关 | 未设置（该开关是自启被识别的主因，我们不加） |
| TLS/HTTP2 指纹 (JA3) | 真实 Chrome（自带 Chromium 与正式版有差异） |
| 插件/字体/Canvas/WebGL/window.chrome | 100% 真实 |
| headless 特征 | 真实 headed 窗口 |
| 登录风控（新设备/异常环境） | 专用 profile 持久化 Cookie，一次人工登录长期复用 |

两个关键细节：
1. **Chrome 136+ 安全策略**：不再允许在默认 user-data-dir 上开调试端口，
   必须显式指定非默认 `--user-data-dir` —— 本 skill 的专用 profile 天然满足
2. **CDP 协议痕迹**：强 WAF 可探测 `Runtime.enable` 等协议泄露。
   对策：目标页面上最小化 `page.evaluate` 注入，优先用真实键鼠事件（human.py）；
   个别站点仍被拦再升级方案 C

### 方案 B（备选）：Playwright 直启真实渠道 headed

CDP 端口故障时降级（当前脚本未实现，必要时在 browser_session.py 增加）：

```python
ctx = p.chromium.launch_persistent_context(
    user_data_dir=<profile>, channel="chrome", headless=False,
    ignore_default_args=["--enable-automation"],
)
```

再用 init script 抹平 `navigator.plugins/languages`、`chrome.runtime` 等残余痕迹。
指纹基本真实，但仍有少量自动化痕迹，强风控下可能识别。

### 方案 C（兜底）：patchright

`patchright` 是消除 CDP 协议泄露（Runtime.enable 等）的 Playwright 补丁分支，
接口完全兼容，依赖声明换成 `patchright` 即可。仅在方案 A 遇到强风控站点时按站点启用。
缺点：版本滞后官方 playwright，不作默认。

## 3. 行为拟人（scripts/human.py，所有方案通用）

环境真实只是及格线，行为特征是二次风控重点：

| 动作 | 实现 |
|---|---|
| 输入 | 逐字符 `keyboard.type` + 每字符 40–130ms 随机延迟 + 偶发 150–400ms 停顿；**禁用 fill()**（瞬时赋值可被事件时序识别） |
| 点击 | 鼠标多段轨迹移动（随机步数/抖动 ±3px）→ 按下-抬起间隔 40–100ms；**禁用 locator.click() 坐标直点** |
| 节奏 | 动作间随机 0.3–1.2s；页面切换后 networkidle + 随机余量 |
| 滚动 | 分步 wheel 事件，带随机增量 |
| 频率 | 单线程单会话；低频；绝不并发批量 |

## 4. 合规红线（与 SKILL.md 同源）

- 登录凭据、短信验证码、图形/滑块验证：一律人工，脚本绝不读取或代填，禁止任何绕过
- 仅操作用户本人账号、本人业务数据；低频使用，不做批量抓取
- 开票提交属资金涉税敏感操作：提交前必须人工确认（浏览器前台可见，用户可随时接管）
