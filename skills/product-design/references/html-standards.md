# HTML 原型产出规范

> 每个页面一个自包含单文件 HTML。用户双击即可打开，断网完整可用。

## 文件与结构

- 位置：`<产物目录>/pages/<page>.html`，页面名小写英文（index / dashboard / order-list）
- 单文件 ≤ 2000 行；超出先精简内容，不拆文件、不外置 CSS/JS
- 必备骨架（每个页面如此开头）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>页面名 — 项目名</title>
  <style>/* 全部内联 */</style>
</head>
<body>
  <!-- 语义化标签：header/nav/main/section/footer -->
</body>
</html>
```

## 自包含硬规则（离线可用）

1. CSS 全部内联在 `<style>`；JS 逻辑内联在 `<script>`（仅交互原型需要的部分）
2. 字体用系统栈（见 design-system-guide.md 第 3 节），**禁 Google Fonts 等外链字体**
3. 图标/插画/占位图一律**内联 SVG 或纯 CSS 图形**，**禁外链图片**（Unsplash/picsum/CDN）
4. 无任何 `http(s)://` 资源引用（check_html.py W007 会拦截）
5. 禁框架依赖（React/Tailwind CDN 等）——手写语义化 CSS；可复用设计 token 用 CSS 变量：
   ```css
   :root { --accent: #3B82F6; --ink: #18181B; --radius-card: 16px; ... }
   ```

## 设计系统落地

- 生成前先读 `DESIGN.md`，把第 2/3 节的色板与字体映射为 `:root` CSS 变量
- 组件样式严格按 DESIGN.md 第 4 节（圆角值、阴影值、按钮态直接照抄 token）
- 多页面间导航互链：`<a href="./dashboard.html">` 相对路径互跳，形成可点击穿的原型

## 交互态要求（原型要"活"）

- hover/active/focus 三态必须写（按钮、卡片、链接、输入框）
- 弹层用 `<dialog>` 或 CSS `:target`/checkbox 技巧实现真交互，不要求真实业务逻辑
- 列表/网格按动效档加级联入场（`animation-delay: calc(var(--index) * 100ms)`）
- 移动端 App 界面：底部标签栏可切换（锚点或少量 JS），保持单文件内多"屏"切换

## 移动端 App 界面呈现

两种形态按用户需求选（默认 A）：
- **A. 手机壳单页**：页面背景深灰居中放 390px 宽手机框（圆角 48px、内含状态栏 9:41 + 信号电量 SVG 简笔），框内渲染 App 界面；适合展示单屏设计
- **B. 全屏移动页**：无手机壳，直接移动端布局 + viewport；适合多屏连续浏览与真机投屏
- 手机壳与界面都遵守 DESIGN.md；状态栏不追求还原真机，示意即可

## 响应式（硬要求）

- 至少一个 `@media` 断点（≤768px 塌缩单列）；桌面优先的页面补 ≥1024px 宽屏优化
- `min-height: 100dvh` 替代 `height: 100vh`
- 移动端触控目标 ≥44px、正文 ≥14px、禁横向滚动
- 生成后跑 `check_html.py`（error 清零）→ 建议 `screenshot.py` 三视口截图核对

## 内容真实性

- 文案用符合业务的真实感中文（导航项、按钮字、示例记录），**禁 Lorem ipsum / "占位内容" / test123**
- 人名用真实感中文姓名（陈晓萌、周远航），禁张三/李四/John Doe
- 数字用有机值（47.2%、¥1,284、3 分 12 秒），禁 99%/1234567 式整数派
- **统计指标（成功率、SLA、响应时间等）用户未提供时**：用 `[待补充指标]` 式占位或明确示例值，交付时统一标注"示例数据，需替换"——不编造看似真实的业务数据

## 可访问性基线

- 语义化标签（button 就用 `<button>`，不用 div 模拟）；图片/图形 SVG 加 `aria-label` 或 `role="img"`
- 文字对比度：正文 ≥ 4.5:1，大标题 ≥ 3:1（深灰字 #71717A 级别不要放在浅灰底上做正文）
- 禁用 outline: none 而不补焦点样式
