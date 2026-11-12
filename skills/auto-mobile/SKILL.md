---
name: auto-mobile
description: auto-mobile 系列之安卓手机控制：智能体从 Windows 电脑操控 Android 真机——打开指定 App、按页面内容点击/输入/滑动、读取页面元素树、截图。经 USB（默认）或 WiFi 连接，手机端跑 uiautomator2 服务（ATX），电脑端 uv 项目脚本 android_ctl.py 子命令式调用。当用户想"帮我在手机上打开 XX""点一下手机上的 XX""在手机 XX App 里输入""看看我手机当前屏幕""把手机页面内容读给我""自动化操作我的安卓手机"时使用。WHEN NOT：iPhone（走 WDA 路线，本 skill 暂不含）；批量群控多台设备；未授权操作他人设备。仅 Windows + Android 真机（已开 USB 调试）+ uv。
compatibility: 仅 Windows + Android 真机（荣耀 GT / MagicOS 已实测，原生安卓通用）；需手机开 USB 调试并授权电脑；电脑需 adb（winget Google.PlatformTools）与 uv；首次使用跑 `uv run python -m uiautomator2 init`，MagicOS 上手机须亮屏解锁并点「允许」安装确认。
metadata:
  author: AI-Redfish
  version: "1.0.0"
---

# auto-mobile — 安卓手机控制（uiautomator2，按页面内容操作）

本 skill 驱动电脑上的 Agent 操控 Android 真机。AI 负责：理解目标 → 读页面（info/dump）→ 决策操作 → 调用脚本执行 → 按输出验证 → 汇报。脚本 `android_ctl.py` 负责：连接、定位元素、点击/输入/滑动/截图等全部确定性操作。

## 路径约定

- Skill 目录：`<工作空间>/.agents/skills/auto-mobile/`，所有命令在此目录内执行。
- 运行产物（截图、元素树 XML）输出到 `<工作空间>/.agents/out/auto-mobile/`（已被 .gitignore 忽略，非 git 托管）。
- 背景知识：仓库记忆 `store/.agents/memory/learned/mobile-automation-from-pc.md`（双平台方案、荣耀真机坑、PYTHONHOME 解法）。

## 前置检查（每会话一次）

```bash
adb devices                          # 手机须在列且状态为 device；为空 → 排错章节
cd <skill 目录>
env -u PYTHONHOME -u PYTHONPATH uv run android_ctl.py info   # 首跑自动建 .venv
```

本仓库 Agent 会话环境有 PYTHONHOME 污染，`uv run` 必须加 `env -u PYTHONHOME -u PYTHONPATH` 前缀；用户自己的终端可直接 `uv run`。

## 命令清单

```bash
S="env -u PYTHONHOME -u PYTHONPATH uv run android_ctl.py"
$S info                                  # 当前前台 App（package/activity）
$S shot  <工作空间>/.agents/out/auto-mobile/s.png        # 截图
$S dump  <工作空间>/.agents/out/auto-mobile/page.xml     # 页面元素树 XML
$S tap   --text "设置"                    # 按可见文本点击（或 --res com.xxx:id/btn）
$S input --res com.xxx:id/et --text "你好" # 输入框写入（支持中文）
$S swipe up                              # 滑动 up/down/left/right
# WiFi 模式：先 adb tcpip 5555 && adb connect 手机IP:5555，命令加 --host 手机IP
```

**Agent 操作循环**：`info` 看在哪个 App → `dump` 读页面元素（text/resource-id 都在 XML 里）→ 定位目标元素 → `tap`/`input` → 再 `dump`/`info` 验证生效。元素找不到时先 dump 看页面真实内容，不盲点。

## 安全闸门（必须遵守）

1. 支付/下单/转账、删除数据、发送消息（聊天/邮件/评论）三类操作：**先向用户确认，再执行**。
2. 不读取、不传递密码与验证码；敏感字段（登录密码等）提示用户手动输入。
3. 默认 USB 模式；WiFi 模式端口无鉴权，仅限可信网络，用完断开。
4. 只操作用户自己的设备与账号；拒绝刷量、爬取、外挂类请求。

## 排错速查

| 现象 | 处理 |
| :-- | :-- |
| `adb devices` 空 | 手机选 USB「传输文件」模式；换数据线；或用「无线调试」配对 |
| `adb devices` 显示 unauthorized | 手机解锁，重插 USB，点「允许 USB 调试」 |
| 连接失败 Can't find any device | 确认已跑 `uv run python -m uiautomator2 init`；跑 `uv run python -m uiautomator2 doctor` |
| init 报 INSTALL_FAILED_ABORTED | MagicOS 需手机亮屏解锁，跑 init 后 10 秒内在手机点「允许」；补装 `adb shell pm install -r -t /data/local/tmp/unknown.apk` |
| SRE module mismatch | `uv run` 前加 `env -u PYTHONHOME -u PYTHONPATH` |
| 元素找不到 | 先 `dump` 看真实 text/resource-id；部分自绘控件无文本，改用坐标 `d.click(x, y)`（脚本暂未封装，可临时用 python -c） |

## 验收标准

- `info` 返回 JSON（package/activity）；`shot` 在输出目录生成非空 png；`tap` 后 `dump`/`info` 能观察到页面变化。
- 环境变化后（重装系统/新手机）重新执行前置检查即可，无需改脚本。
