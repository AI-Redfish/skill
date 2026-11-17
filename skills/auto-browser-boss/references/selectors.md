# Boss直聘 DOM 选择器手册（牛人端）

> 来源：2026-11 实测探索（Chrome 157 + Playwright connectOverCDP）。Boss 为 Vue 动态渲染，`data-v-*` 随版本变化，选择器以 class 层级为主。失效时更新本文件与脚本选择器常量区。

## 页面路径（牛人端，均为 SPA 路由）

| 页面 | URL | 备注 |
|---|---|---|
| 推荐 | `/web/geek/recommend` | 卡片流 |
| 搜索 | `/web/geek/jobs?query={关键词}&city={城市代码}` | 左列表+右详情；旧版 `/web/geek/job` 301 到此 |
| 聊天 | `/web/geek/chat` | **/web/chat/index 是招聘端路径，勿用** |
| 风控登录 | `/web/user/?ka=bticket` | 出现即要求人工重新验证 |

## 推荐页（/web/geek/recommend）

- 职位卡：`li.item-boss`（scoped `data-v-53004459`，勿依赖）
- 沟通按钮：`a.btn.btn-startchat`，文案区分「立即沟通」/「继续沟通」，ka 形如 `personal_added_continue_{encryId}`
- 职位链接：`a[href*="/job_detail/"]`，URL 带 `securityId`（安全票据，过期失效）与 `ka=personal_added_job_*`

## 搜索页（/web/geek/jobs）

布局：左侧职位列表 + 右侧详情面板。**2026-11-17 实测验证**（含真实投递 1 次）。

- 卡片：`li.job-card-box`（scoped `data-v-6460f456`，实测**无** `.job-card-wrap` 外层、**无**卡内沟通按钮）
- 卡片信息：`.job-name`（职位，href 为 `/job_detail/*.html`）、`.job-salary`（薪资，**数字被字体混淆**，文本为 `-K`）、`.company-location`（地区，如「杭州·余杭区·仓前」）、`.boss-name`（公司）、`.job-info .tag-list li`（经验/学历）
- **投递链路（已验证）**：点卡片 `li.job-card-box` → 右侧详情面板打开 → 点面板内 `.job-detail-op a.op-btn.op-btn-chat` → 可能弹确认面板（点「继续沟通/打招呼/发送/确定」）
- 已沟通状态：详情按钮文本「已沟通/继续沟通」，跳过不重复投递
- 渲染等待：goto 后需轮询 8s+（4s 时 0 卡，8s+ 时 15 卡）
- 筛选器容器：`.filter-condition`，维度依次为：工作区域 / 职位类型 / 求职类型 / 薪资待遇 / 工作经验 / 学历要求 / 公司行业 / 公司规模 / 融资阶段；已选筛选显示在 URL query（如 `salary=13Z20` 等 boss 编码值，未解析，用点击交互或环境变量直传）
- 期望快捷入口：`.c-expect-select`
- 实测单页约 15~30 个职位卡；「更多」分页按钮在列表底部

## 聊天页（/web/geek/chat）

- 会话列表容器：`.chat-conversation`；顶部筛选 tab：全部 / 未读 / 新招呼 / 更多 / AI筛选
- 列表项：容器内 `li`，含时间、HR 姓名、公司/身份（招聘者/HRBP/人才经纪人）、消息预览、状态标识 `[送达]` `[已读]`
- 未读 badge：class 名未确认（探索中断），候选 `[class*="unread"]`、`[class*="badge"]`
- 输入框：未选中会话时不存在；选中后候选 `[contenteditable="true"]`
- 发送按钮：候选文本匹配「发送」（`a/button/span/div` 叶子节点）
- 消息气泡：class 未确认，候选 `[class*="msg-item"]`、`[class*="bubble"]`、`.message-item`；发送方区分（己方/对方）依赖气泡左右位置或 class，未验证

**已知缺口**：气泡/输入框/发送按钮精确结构需在首次真实回复运行时校准，回填本文件。

## 风控实测行为

1. 脚本 `goto` 聊天页或深层 URL → 被弹 about:blank 或 bticket 登录页（导航来源检测）。用户手动导航正常（未被标记时）。
2. 风控标记状态下：聊天页打开后会被整页强制跳到 `/web/geek/jobs`（手动导航也一样）。
3. 反自动化 JS 调 `window.close()`：唯一标签被关 = Chrome 整体退出。对策：启动带 `about:blank` 占位标签 + `add_init_script("window.close = function(){};")`。
4. 推荐/搜索页允许脚本 goto（实测多次通过）；登录态存于专用 profile，重启 Chrome 后保持。
5. Chrome 启动参数：`--remote-debugging-port=9222 --user-data-dir={profile} --no-first-run --no-default-browser-check --disable-blink-features=AutomationControlled`。

## 工程坑位

- evaluate 的 JS 用 Python raw string（正则 `\d` 转义）。
- SPA 渲染竞争：`Execution context was destroyed` → evaluate 重试循环 + sleep。
- 脚本导航前检查 `curl http://127.0.0.1:9222/json/version` 确认 CDP 存活。
- PEP 723 inline metadata + `uv run` 管理依赖（`dependencies = ["playwright"]`）。
