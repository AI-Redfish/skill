# 排障手册：微信 GUI 自动化的实测坑与解法

> 何时读：脚本失败且 `error` 不在上表常见原因中，或需要修改脚本适配新版微信时。
> 来源：微信 4.0（Weixin.exe）Windows 客户端实测；类名兼容 3.9 / 4.0。

## 1. 会话定位的匹配规则（为什么这样设计）

- **会话列表 / 搜索下拉条目**：可访问名是多行文本，**第一行 = 会话名**。
  匹配条件必须是「第一行精确等于目标」：
  - `StartsWith` 前缀匹配会误点：群名以目标开头的**群聊条目**（消息发进群）、
    聊天记录分类的摘要条目（点开是预览不是会话）。
- **文件传输助手是「功能」不是联系人**：搜索结果页的功能入口是 Button，名如
  「文件传输助手 手机和电脑之间传输文件 前往」。识别规则：`Name` 以目标开头
  且**含「前往」**，且必须**先于 ListItem 检查**——聊天记录分类下存在与文件
  传输助手的聊天记录条目（第一行同名），先匹配 ListItem 会点开聊天记录预览。
- **搜索下拉首条建议行与目标同名时必须跳过**（实测踩坑）：建议、功能、聊天
  记录各分组同属一个列表，分组标题行也是 ListItem；「文件传输助手」的搜索
  建议行与「功能」分组入口首行同名且排在最前，按「第一个首行匹配」点会进
  搜一搜页而不是会话。解法：按分组头（搜索网络结果/功能/联系人/聊天记录等）
  维护当前分组状态，建议分组（搜索网络结果等）下的行一律不点。
- **点击坐标**：列表条目点左中部（`X+60, Y+H/2`，避开右侧时间/角标），
  功能卡片用中心点。

## 2. 会话验证（防发错窗口的最后防线）

发送前必须确认当前处于目标会话，判定依据（按序）：
1. 聊天输入框 `Edit.Name == 目标`（独立聊天窗口形态有 Name；
   部分版本输入框 Name 为空，见下）
2. 聊天区 `Document` 名 = 「会话名 - 昵称」：精确等于或以「会话名 - 」开头
   才命中（防「张三」误判进「张三丰」）；**显式排除「目标 - 搜一搜」**
   （搜索结果页 Document 同为「<搜索词> - ?」格式，不排除会误判已进入会话）
3. 验证不过 → 取消发送（此时还没粘贴正文，微信停留原状态无副作用）。
   **不要按 Esc「恢复」**：实测微信 4.0 收到 Esc 会把主窗口隐藏，
   连带后续调用报「未找到微信主窗口」。

## 3. UIA「失明」状态（元素数=1，验证/点击全部落空）

- 现象：窗口 Win32 层完全正常（可见、可激活、标题正确），但 UIA 树后代
  长期只有 1 个元素。Move / Resize / 点击 / Alt+Tab / 最小化→还原均无法恢复。
- 恢复方式：**重启微信客户端**（唯一实测有效手段）。
- 脚本内置 `_ensure_uia_ready`：发送前轮询 UIA 元素数，>30 视为就绪；
  未就绪时重试「最小化→还原」并等待，超时后继续尝试（宁可失败不假成功）。

## 4. 窗口隐藏到托盘（点 X / Esc 后「未找到微信主窗口」）

- 微信 4.0 点 X = `SW_HIDE` 隐藏到托盘；Esc 同样会隐藏窗口。
- 解法：`EnumWindows` 时包含隐藏窗口，按类名（`WeChatMainWndForPC` /
  `Qt51514QWindowIcon` / `mmui::MainWindow`）+ 标题（微信/WeChat/Weixin）
  找到隐藏主窗口，`ShowWindow(SW_RESTORE)` + `SW_SHOW` 自动唤出。

## 5. 停留在非聊天视图（Ctrl+F 无效）

微信重启后可能停在内容流等视图：搜索框不存在，Ctrl+F 无反应。
解法：发送流程开始时点击左侧栏「聊天」按钮（兜底「微信」按钮）回聊天列表；
按钮限定窗口左缘 200px 内，避免误点内容区同名元素。

## 6. 剪贴板操作（64 位必踩）

- `GlobalLock` 必须显式声明 `restype = ctypes.c_void_p`：64 位 Python 下
  默认 `c_int` 会截断 64 位指针 → `string_at` 读剪贴板 access violation。
  参考实现曾靠「剪贴板为空时提前返回 + 内联补设 restype」侥幸掩盖，
  剪贴板非空且堆地址 >4GB 时必崩。
- 读取剪贴板按 `GlobalSize` 限量读再解码，不用无界 `wstring_at`。
- 发送后稍等 ~0.8s 再恢复剪贴板（微信读完前覆写偶发 access violation）。

## 7. 编码（中文乱码三件套）

1. **stdout/stdin 显式 UTF-8**：`sys.stdin/stdout.reconfigure(encoding="utf-8")`——
   Windows 管道默认跟随系统编码（GBK），工作流引擎按 UTF-8 解码会乱码
2. **PowerShell 管道传参必乱**：`echo '中文' | uv run ...` 时 PS5.1 用 ASCII
   编码管道，中文变 `?` 后才进进程，无法恢复——必须用命令行参数
   （argv 走宽字符 API，天然 Unicode）
3. **stderr 诊断**：向 `sys.stderr.buffer` 直接写 UTF-8 字节，不污染 stdout

## 8. 输入框聚焦（ok:true 但消息没发出的假成功）

激活窗口 ≠ 聚焦输入框。已处于目标会话时直接粘贴，若焦点不在输入框，
Ctrl+V/回车落空。解法：粘贴前用 UIA 定位聊天输入框并鼠标点击中心：
- `Edit.Name == 目标`（独立聊天窗口形态）
- 或 `Name` 为空且 `宽 >= 200 且 高 >= 30`（主窗口内嵌形态）
- 搜索框（Name=搜索 / value=搜索词 / 窄条）不匹配

## 9. 输入框焦点与「搜索残留」并存的验证陷阱

点击功能卡片进入会话后，搜一搜页面的搜索框仍残留搜索词
（`Edit.value == 目标`）。验证逻辑**不能**按「存在 value==目标的 Edit」早退
判未进入——会误杀真正的会话输入框（Name==目标）。正确顺序：先扫全部 Edit
找 `Name==目标`（命中立即判成功），搜索残留的否定由 Document 的
「- 搜一搜」显式排除承担。

## 10. 本机视频号播放缓存无法直接提取（实测 2026-11-11）

适用：微信 4.x（Weixin 4.2.0.13，装在 `D:\program\weixin`），数据目录 `D:\program\xwechat_files\<wxid>\`（不在 `%USERPROFILE%\Documents`）；主窗口类 `Qt51514QWindowIcon`（mmui::MainWindow）。

- 播放缓存实际位置：`%APPDATA%\Tencent\xwechat\radium\users\<uid>\xworker\liteapp\local\assets\tmp\wxalite*\finder\finder_videoCache_*`。每次播放会话一个文件（≈512KB–1.2MB），内容全随机（无 mp4 头）＝加密/混淆存储。
- `xwechat_files`（msg/video、cache、resource）与 `%TEMP%` 均无明文视频；multitab `Cache_Data` 里只有 gzip 页面资源与 JPEG 封面。
- 结论仅适用于本机缓存：差分能发现缓存活动，但未验证可还原为 MP4；不能据此推断网页授权媒体也不可下载。优先走 §13 后台授权解析，失败且获授权后才走 §11 录屏。

## 11. 录屏重制路线（画面 + 系统声音 → mp4，实测通过）

- 画面：`ffmpeg -y -f gdigrab -framerate 20 -offset_x 0 -offset_y 0 -video_size 1920x1080 -i desktop -c:v libx264 -preset veryfast -crf 28 -t 900 screen.mkv`。录 mkv 而非 mp4：强杀进程后 mkv 仍可读；`-t` 给上限防挂死。
- 声音：soundcard WASAPI loopback（ffmpeg 的 dshow 无 loopback 设备，录不了系统声音）。选设备 `isloopback and 'Realtek' in name`，48000/2ch/s16le 写 raw，事后 `ffmpeg -f s16le -ar 48000 -ac 2 -i raw …` 重封。
- **长录制不要用 `uv run` 包装**：uv 父进程被回收时会连带杀掉子进程（实测 200 秒后音频进程静默消失、无日志）。用 `uv venv` 建独立环境装 soundcard，直接跑 venv 的 python.exe；ffmpeg 无包装不受影响。
- 验证 loopback 抓到声音：录 6 秒并在第 2 秒播 `C:\Windows\Media\notify.wav`，`volumedetect` 的 max 应 > -40dB（纯静音 ≈ -91dB）。
- 合成与对齐：`silencedetect` 找音频语音区间；抽帧（`fps=1/10` + 缩略图）定位录屏中播放器区间；`ffmpeg -ss/-to` 裁剪后 `-map 0:v -map 1:a -c:a aac -shortest` 合成。
- 前台抢占坑：机器被人工使用时 `SetForegroundWindow` / `SwitchToThisWindow` / `SetWindowPos(TOPMOST)` 均不可靠（前台反复被用户窗口抢回），坐标点击会落到别的窗口——**涉及人工播放的步骤直接请用户手动操作**，不要自动化点击。

## 12. faster-whisper 转写环境坑（uv 实测）

- `uv run` 默认解析到 Python 3.14：`av` 无对应 wheel → 源码编译失败。需 `--python 3.11 --with "av==12.3.0"`（faster-whisper 的 `decode_audio` 调 `av.open(metadata_errors=…)`，av 版本不匹配报 TypeError）。
- HuggingFace 直连曾报 `SSL: UNEXPECTED_EOF`。先检查网络与本地模型缓存；已缓存时使用 `HF_HUB_OFFLINE=1`。镜像是第三方服务，只有用户明确同意后才设置 `HF_ENDPOINT`，不默认静默切换。
- 已验证组合：Python 3.11.9、`faster-whisper==1.2.1`、`av==12.3.0`、small CPU int8。现由转写脚本的 PEP 723 声明固定依赖，使用 `uv run --no-project --python 3.11 <skill_dir>/scripts/transcribe_video.py <视频>`。

## 13. 元宝授权解析与后台媒体下载

何时读：用户只提供视频号分享链接，希望后台获取视频、字幕、全文或总结。已在一个公开视频实测成功；接口并非稳定公开 API，其他链接及长期可用性未保证。

1. 在 Tabbit 观察到的已登录元宝标签页，用 `page.fetch("/api/weixin/get_parse_result", ...)` 发 JSON：`{type:"video_channel_url", url:shareUrl, scene:1}`。设置 `method:"POST"`、`Content-Type: application/json`、`as:"json"`。HTTP 200 且 `code:0` 后读取 `data.playable_url`；401 时请用户登录。
2. `playable_url` 是授权播放页，不是 MP4。仅在内存解析其 `token` 和 `eid`，检查 origin 为 `https://channels.weixin.qq.com`。不保存或打印含签名的 URL、Cookie、令牌。
3. 用 `page.request.post("https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info", ...)`，请求体 `{baseReq:{generalToken:token}, exportId:eid}`，headers 的 Origin 为播放页 origin，Referer 为完整授权播放页。已观察 HTTP 201、`errCode:0`；媒体在 `data.feedInfo.videoUrl`。不依赖播放页导航成功。
4. `page.request.get(mediaUrl)` 获取媒体。曾观察 Range 探测 206、完整 GET 200；下载脚本先探测大小，再请求完整范围。只允许 HTTPS 腾讯媒体域名，不请求响应注入的任意地址。
5. 脚本通过 Tabbit result/resource 分页接收媒体，`--max-bytes` 最大 65536，按 `nextOffset` 直到 `eof`，拼接 `data` 后才解析 JSON。stdout 为空先查同一 request-id 的 receipt；失败响应不输出原始错误，以免泄漏签名。
6. 下载只检查长度与 MP4 头；仍必须用 ffprobe 检查时长、音视频流，再用 ffmpeg 完整解码。不可把 HTTP 成功、扩展名或 MP4 头当作完整性证明。

分享页面二维码用于手机微信观看，不是浏览器授权登录。扫码后手机播放不表示电脑浏览器已登录。元宝登录是独立步骤；不要求用户导出凭据。

脚本消费一次性授权只向对应腾讯接口发送用户提供的分享链接和临时授权，不上传本地文件、聊天记录或浏览器凭据。下载有体积上限，不自动解密缓存或绕过私密内容、删除状态与权限拒绝。

参考：`https://github.com/ltaoo/wx_channels_download/blob/main/internal/workers/sph/worker.js`。仅借鉴授权解析思路，脚本为本地独立实现；本次调用链以会话实测为依据，不视为官方 API 承诺。
