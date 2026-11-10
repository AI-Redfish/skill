# redbook-playbook — 小红书页面结构与提取备忘

来源：AgentPhoto 项目 `scripts/xhs-clip-extension/background.js`（PAGE_EXTRACT）、
`scripts/xhs-fetch.mjs`（纯 CDP 抓取路线），2026-11 实战验证。
页面结构变更时按本备忘排查。

## 数据来源（页面上下文注入）

首选 `window.__INITIAL_STATE__.note.noteDetailMap`（SSR 全量数据：
图集不受懒加载限制、视频流可取直链）；DOM 提取仅作兜底。

### noteDetailMap 结构

```
__INITIAL_STATE__.note.noteDetailMap[<noteId>].note
├── title / desc / type ('normal'|'video')
├── user.nickname
├── tagList[].name
├── imageList[]
│   ├── urlDefault / infoList[].url     # 静态图（取最后一档 = 最高清）
│   ├── livePhoto (bool) / videoUrl     # 实况照片的动态视频
└── video.media.stream                  # 视频流（多代结构，见下）
```

### 视频流兼容（stream 组可能是数组或按画质 id 的对象 map）

| 代际 | key | 说明 |
| --- | --- | --- |
| 新版 | EF4 | mp4 容器含音轨，可直接播放，**优先** |
| 新版 | EF5 | fmp4 仅视频轨 |
| 旧版 | h264 / h265 / av1 | 按画质 id 分组 |

选择规则：mp4 format 优先，再按 `weight`（画质权重）取最高；
候选直链 `masterUrl` + `backupUrls[]` 逐个重试。

## 链接与路由

- 笔记详情路由：`/explore/<24位hex>` 或 `/discovery/item/<24位hex>`；
  搜索页/个人页弹层为任意 24 位 hex 段路由
- **xsec_token**：链接必须带（分享/复制链接自带），否则打不开详情页；
  拿不到时在浏览器手动打开后用 `--tab` 抓当前页
- 短链/SPA 跳转后 pathname 才变为详情路由，noteDetailMap 滞后填充——
  提取函数内轮询等待至多 15s（调用方 evaluate 超时需大于此值）
- `wrongNote` 校验：状态水合出的笔记与链接不一致时拒绝保存

## DOM 兜底选择器（state 不可用时）

| 字段 | 选择器（依次尝试） |
| --- | --- |
| 标题 | `#detail-title` → `.note-content .title` → `h1` → `meta[property="og:title"]` |
| 正文 | `#detail-desc` → `.note-text` → `.desc` → `article` → `meta[name="description"]`（排除 comment 容器） |
| 作者 | `.author-wrapper .username` → `[class*="author"] .username` |

正文清洗：去平台标记 `#xx[话题]#` → `#xx`；图片容器取标题+正文最小公共祖先，
向上找到第一个含 ≥200px 大图的层级（避免带走推荐流/侧栏大图）；
过滤 `avatar|icon|emoji|logo|qrcode`。

## 下载头

| 域名 | 头 |
| --- | --- |
| xhscdn.com / xiaohongshu.com | `Referer: https://www.xiaohongshu.com/` + 浏览器 UA；http 直链升级 https |

## 排查路径

1. `blocked`：页面被重定向到登录/风控页（URL 含 `website-login/error`、
   `error_code=`，或正文前 500 字含"存在风险/请登录"）→ 在测试 Chrome 登录后重试
2. `notScoped`：首页/列表页触发 → 打开单篇详情页再抓
3. `wrongNote`：链接与页面状态不一致 → 等页面加载完成后重试，确认是详情页
4. `videoDiag`：视频笔记但流未解析出 → 落 `dump-video.json` 诊断
   （mediaKeys/streamKeys），页面结构可能已升级，按上文结构核对
5. 正文为"（未提取到正文）"：DOM 选择器可能已变化 → 按 DOM 兜底选择器表核对
