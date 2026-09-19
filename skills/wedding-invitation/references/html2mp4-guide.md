# HTML→MP4 通用导出流水线（html2mp4-guide）

`export_mp4.py` 编排四步，全部组件可独立调用：

```
ensure_ffmpeg.py ─┐
                  ├─→ record_page.py ─→ synth_bgm.py ─→ ffmpeg 混流转码 ─→ 验证
                  │      (webm+timeline)   (wav 对齐)      (1080x1920)      (Duration/分辨率)
```

## 1. ensure_ffmpeg.py — 依赖自举

探测顺序：系统 PATH → `<home>/.agents/cache/ffmpeg/` → PyPI 镜像下载
imageio-ffmpeg wheel（提取静态二进制，支持 linux/win 双平台，无需 root）。
镜像依次尝试：清华 → 阿里 → pypi.org。
**WSL 注意**：必须用 linux 二进制（win exe 在 WSL 直接 exec 报 Invalid argument）。

## 2. record_page.py — 无头浏览器录制

- 生成 `record.mjs`（Playwright-core + 系统 Chrome/Edge）并运行
- **路径坑固化**：WSL 调 win-node.exe 时命令行传 `/mnt/...` 参数会被错误转换，
  因此所有路径在生成 mjs 时写入文件内部，运行时不传路径参数
- 自动探测顺序：node（PATH → `/mnt/*/develop/nvm/v*/node.exe` 等）；浏览器
  （Chrome/Edge Windows 常见路径 → PATH chromium）
- playwright-core 缺失时自动 `npm install --prefix`（win 侧用 node.exe+npm-cli.js）
- **saveAs 顺序坑固化**：`context.close()` → `video.saveAs()` → `browser.close()`
- 翻页三种模式：`go`（页面有全局 `window.go(n)`，本 skill 请柬默认）、
  `selector`（点击 `--nav-selector`）、`none`（只录不翻）
- 产出：`videos/record.webm`（视口同尺寸）+ `timeline.json`

## 3. timeline.json 与音画对齐原理

```json
{ "music": 1.68, "blips": [1.68, 6.69, 12.7, 21.7, 28.2, 33.7], "end": 38.5 }
```

- `music`：入口按钮点击时刻（BGM 起播点，与页面行为一致：点击才播）
- `blips`：每次翻页时刻（此处插「哔」音效）
- `end`：最后翻页 + 尾页停留（音频在其 -0.5s 开始淡出，+1.2s 截止）
- Playwright `recordVideo` 不录系统音频 → 音轨由 synth_bgm.py 按同一乐谱
  参数独立合成，再混流——这就是"代码配乐"方案，无需录音/外部音频文件

## 4. synth_bgm.py — 纯标准库合成

44.1kHz/16bit 单声道 wav。音色公式与页面 WebAudio 完全一致：
基音 sine + 3.01 倍频泛音(快速衰减) = 木琴；triangle = 贝斯；
square 7.2kHz 短衰减 = hi-hat；指数包络 `exp(-5.5·t)` 近似 exponentialRamp。

## 5. ffmpeg 转码

```
ffmpeg -y -i webm [-i wav] -filter_complex "[0:v]scale=W:H:flags=lanczos,format=yuv420p[v]"
  -map [v] [-map 1:a -c:a aac -b:a 192k -shortest]
  -c:v libx264 -crf 18 -preset medium -movflags +faststart out.mp4
```

- 视口与输出同比例（540x960→1080x1920）整数倍 lanczos 放大；比例不符自动
  等比缩放+pad 黑边
- faststart：元数据前置，微信/朋友圈秒开
- 验证：`ffmpeg -i out.mp4` 解析 Duration 与分辨率写回 JSON

## 参数调优速查

| 目标 | 参数 |
|---|---|
| 某页多停留 | `--stay` 对应位增大（打字机页建议 ≥8000ms，文案约 95 字×62ms+标点停顿） |
| 更短的视频 | 减 stay 或删页（改 HTML） |
| 横屏 16:9 | `--viewport 960x540 --out-size 1920x1080` |
| 更高画质 | `-crf 18` → 16（export_mp4.py 内常量） |
| 换 BGM 速度/音量 | synth_bgm.py `--tempo/--volume`（单测可验证） |

## 组件单独调用示例

```bash
python3 scripts/ensure_ffmpeg.py --workdir ~            # 仅装 ffmpeg
python3 scripts/record_page.py --html x.html --workdir ./w --nav-mode selector --nav-selector ".arrow"
python3 scripts/synth_bgm.py --timeline w/timeline.json --out w/bgm.wav
```
