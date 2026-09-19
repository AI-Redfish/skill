# 踩坑记录（tech-notes）

来自真实会话验证，修改脚本前先读，避免踩回已解决的坑。

## WSL ↔ Windows interop

| 坑 | 现象 | 解法（已固化进脚本） |
|---|---|---|
| `/mnt/...` 参数转换坏 | win-node.exe 收到 `D:\mnt\d\...` | 路径全部写入生成的 .mjs 文件内，运行时不传路径参数 |
| .cmd 不能从 bash 执行 | `npm.cmd: unexpected EOF` | 用 `node.exe <npm-cli.js>` 调 npm |
| WSL exec 下载来的 win exe | `Invalid argument`（ffmpeg.exe 完整合法） | WSL 环境一律用 linux 静态二进制（ensure_ffmpeg.py 判定） |
| cmd.exe 间接执行 | `拒绝访问` | 同上，不走 cmd |
| 相对路径执行 exe 也异常 | 偶发 | 用绝对路径 |

## npm / 网络

- `npm install` 官方源在大包（playwright-core+ffmpeg-static）时可能 600s+
  "超时"但实际已装完：**以 node_modules 存在性为准**，不要只信退出码
- `npm.cmd --version` 在 WSL bash 报错但 npm 本体可用；install 需 `--prefix`
  显式给 Windows 风格目标目录
- 可用镜像实测（2026-09）：PyPI 清华 ✅、ghfast.top(GitHub 代理) ✅、
  johnvansickle/外网直连 ❌、codeload.github.com ❌
- imageio-ffmpeg wheel 内含静态 ffmpeg（linux: `binaries/ffmpeg-linux-x86_64-*`，
  win: `binaries/ffmpeg-win-x86_64-*.exe`），走 PyPI 镜像即可获取，无需 root

## Playwright

- `recordVideo` **不含音频**（无论 headless 与否）→ 音轨独立合成再混流
- `video.saveAs()` 必须在 `context.close()` 之后、`browser.close()` **之前**，
  否则 `Target page, context or browser has been closed`
- headless 模式录屏正常支持；浏览器用 `executablePath` 指系统 Chrome/Edge
  （playwright-core 不带浏览器下载）
- `addInitScript` 在页面加载前注入，可消除首帧桌面样式闪烁

## 页面/媒体

- 移动端 H5 在宽视口下会触发"桌面手机框"样式：注入覆盖 CSS 让内容铺满
- 微信内置浏览器：单文件 HTML 可直接打开；`clipboard API` 可能受限，
  需 `execCommand('copy')` 降级；音频必须由用户手势触发（页面用"点击开启"）
- ffmpeg 输出 MP4 必须显式 `format=yuv420p`（部分播放器不认 yuv444）+
  `-movflags +faststart`
- 打字机时长估算：字数 × 62ms + 中文标点每个 +260ms，用于校准 stay
