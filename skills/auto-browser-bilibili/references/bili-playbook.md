# bili-playbook — B 站页面结构与 API 备忘

来源：AgentPhoto 项目 `scripts/xhs-clip-extension/background.js`（PAGE_EXTRACT_BILI）、
`scripts/bili-clip.mjs`（合并流程），2026-11 实战验证。页面结构变更时按本备忘排查。

## 数据来源（页面上下文注入，非裸 API）

| 数据 | 取法 |
| --- | --- |
| 元数据 | `window.__INITIAL_STATE__.videoData`（title/owner.name/desc/pic/duration/pages） |
| 视频流 | 页面内 `fetch('https://api.bilibili.com/x/player/playurl?bvid=<bvid>&cid=<cid>&qn=0&fnval=16&fourk=1', {credentials:'include'})` |
| 标签 | 页面内 `fetch('https://api.bilibili.com/x/web-interface/view/detail?bvid=<bvid>', {credentials:'include'})` → `data.Tags[].tag_name` |

要点：**必须注入页面执行**。页面上下文 fetch 自带登录 cookie 与 Referer，
可拿到账号可见的最高画质；脚本侧裸调 API 只有游客画质。

## 画质映射（playurl dash.video[].id → QN）

```
127=8K 超高清  126=杜比视界  125=HDR 真彩  120=4K 超清
116=1080P 60帧  112=1080P 高码率  80=1080P 高清  74=720P 60帧
64=720P 高清  32=480P 清晰  16=360P 流畅
```

编码选择：同画质下优先 `avc`（H.264，ffmpeg 合并兼容性最好）；
音频优先 `mp4a`（AAC）。DASH 为音视频分离流：`video.m4s` + `audio.m4s`。

## 分P

- `videoData.pages[]`：`{page, part, cid}`；`__INITIAL_STATE__.videoData.cid` 是当前 P 的 cid
- 抓第 N P：按 `pages` 找到对应 cid，再调 playurl
- 多 P 时 note.md 附 `# 分P列表` 并标注当前 P

## 合并（ffmpeg 流复制，不转码）

```
ffmpeg -y -i video.m4s -i audio.m4s -c copy -movflags +faststart video.mp4
```

- 成功后删除分离流；只保留 `video.mp4`
- 未检测到 ffmpeg 时保留分离流，装好后对目录补执行（脚本 `--merge <目录>`）

## 下载头（缺一即 403 或空响应）

| 域名 | 必需头 |
| --- | --- |
| bilivideo.com / bilivideo.cn / akamaized.net / hdslb.com | `Referer: https://www.bilibili.com/` + 浏览器 UA |

CDN 直链有时效性：提取后尽快下载；失败时 playurl 返回的 `backupUrl` 逐个重试。

## 排查路径

1. `notFound`：页面不是视频播放页（`/video/BV...`），或 `__INITIAL_STATE__` 未就绪
   → 确认链接、加大等待
2. `video=null`：playurl 返回空 → 未登录或该视频需付费/地区限制；检查浏览器登录态
3. 合并失败：ffmpeg 报错尾部 5 行即原因；常见为分离流不完整（下载中断）
4. 403：检查 Referer/UA；确认直链未过期（重新提取再下）
