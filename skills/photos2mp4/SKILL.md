---
name: photos2mp4
description: 将批量图片与背景音乐合成为 MP4 幻灯片视频：图片按自然排序一图一页组装成 PPTX（40 种切换效果、每页停留时长、contain/cover/stretch 适配、跨页循环背景音乐），再调用本机 PowerPoint 导出 MP4。当用户想把照片/图片做成视频、生成相册视频、幻灯片视频、图片轮播视频，或要求给已有 PPTX 设置/修改切换效果、自动换片时间、导出 MP4 时使用。注意：导出 MP4 需 Windows + Microsoft PowerPoint 2010+（WPS 不支持）；仅生成 PPTX 无此限制。
compatibility: 用 uv 运行（uv run，脚本头部 PEP 723 声明依赖：python-pptx + pywin32(仅 Windows) + mutagen）；export / list-transitions 实测需 Windows + Microsoft PowerPoint 2010+；无 uv 且已装齐依赖时也可直接 python 运行。
metadata:
  author: AI-Redfish
  version: "1.0.0"
---

# photos2mp4 — 批量图片 + 背景音乐 → MP4 视频

把一组图片变成带切换效果和背景音乐的 MP4 视频。核心路线：

```
图片组 + 音乐 ──build──▶ PPTX（一图一页 + 切换效果 + 自动换片 + 跨页循环音乐）
                              │
                        export（调用本机 PowerPoint COM）
                              ▼
                            MP4 视频
```

实现方式：`all` 一条龙（build + export），或分步 `build` → `export`。

## 双闭环流程（最高优先级，优先于其他默认行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环
1. 回答前先提问，**每次只问一个问题**，根据回答继续追问
2. 提问围绕：真实目标、背景、使用场景、输出对象、关键约束、优先级、
   成功标准、禁止事项、已有信息、可接受偏差
3. 对“用户真正想要什么”有 95% 信心才停止提问；未达 95% 只提问澄清，
   不给最终方案。用户消息已足以达到 95% 信心时（如图片、节奏、音乐均已明确），
   可直接执行 §2 默认决策表，但最终输出必须列出所采用的关键默认值作为假设

### 第二闭环：输出审查闭环
1. 形成答案后不直接输出，先自查：是否真正解决目标？是否遗漏关键约束
   （如导出 MP4 的 Windows + PowerPoint 前提）？是否存在事实错误、逻辑漏洞、
   歧义、不可执行之处？
2. 发现问题→自行修正→再次审查，重复“审查—修正—再审查”，
   直到对输出结果至少有 95% 的准确性信心

### 最终输出要求
1. 先一句话复述用户真实需求
2. 再给出最终方案：明确、可执行、可直接使用（含产物路径、页数、每页秒数、
   是否含音乐、分辨率）
3. 说明关键假设（采用的默认值）、剩余不确定性，以及为什么已达到 95% 信心；
   不确定处明确标注，不假装确定

## 路径与输出位置约定

- 以下 `<skill_dir>` 指本 SKILL.md 所在目录；所有脚本用 `<skill_dir>` 前缀调用，
  **不要**假设当前工作目录就是 skill 目录
- **产物（PPTX/MP4）一律不写入 skill 所在仓库**：
  - 未指定 `--output` 时，脚本自动写入默认产物目录
    **`<桌面>/photos2mp4_output/`**（时间戳命名；export 缺省为 `<pptx同名>.mp4`）
  - 用户可用 `PHOTOS2MP4_OUT_DIR` 环境变量重定向默认目录
  - 脚本内置守卫：目标路径位于本 skill 所在 git 仓库内时直接拒绝（退出码 2），
    并在错误信息中给出建议目录；除非用户明确要求写入仓库（此时可设
    `PHOTOS2MP4_ALLOW_REPO_OUTPUT=1` 放行），否则不要绕过守卫
- 用户指定了仓库之外的输出路径时，按用户指定的执行

## 0. 首次使用：环境准备（uv，零手工安装）

本 skill 的 Python 依赖用 **uv** 管理：三个脚本头部都带 PEP 723 内联依赖声明，
`uv run` 自动解析、安装并缓存到 uv 全局缓存（**不在 skill 目录创建任何文件**）。

```bash
# 若无 uv，先安装（任选其一）：
#   winget install --id=astral-sh.uv        # Windows
#   curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux/macOS

# 受限网络（直连 pypi 超时/TLS 失败）时，先换镜像源：
#   export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple   # 或其他镜像

# 验证（首次会自动装 python-pptx / pywin32(Windows) / mutagen，之后秒起）：
uv run <skill_dir>/pptx_video_builder.py selftest --json
```

自检通过（退出码 0）才继续；失败则读 stderr 日志修复环境。

所有命令统一 `uv run <skill_dir>/脚本 ...` 形式。依赖清单只在脚本头部声明，
不要另行创建 venv / pyproject。已装齐依赖的环境也可直接用 python 运行
（PEP 723 块是纯注释）。

## 1. 标准工作流

按顺序执行：

1. **自检**：`selftest`（见上）
2. **确认用户需求**（见 §2 参数决策），缺关键信息先问再动手
3. **（可选）探测可用效果**：仅当用户对切换效果有讲究、或 build 后 PowerPoint 打不开时：
   ```bash
   uv run <skill_dir>/pptx_video_builder.py list-transitions --json
   ```
   退出码 3 = 本机无 PowerPoint，跳过实测改用理论目录（`--no-verify`）
4. **生成视频**（`--output` 可省略，默认写入 `<桌面>/photos2mp4_output/`）：
   ```bash
   uv run <skill_dir>/pptx_video_builder.py all \
       --images <图片目录/文件...> \
       --music <音乐文件> --transition <效果> --advance <每页秒数> --json
   ```
   需要逐页不同效果/节奏时，先写 transitions JSON 文件再加
   `--transitions-json <file>`（格式见 [references/transitions.md](references/transitions.md)）
5. **按退出码汇报结果**（见 §4），成功时向用户报告 MP4 与 PPTX 路径、页数、时长

### 修改已有 PPTX（不是从图片开始）

- 改切换效果/换片时间：`set-transitions --pptx <file> --transition <名> [--advance 秒]`
- 已有 PPTX 直接导出：`export --pptx <file> --output <out.mp4>`
  ⚠️ PPTX 若无自动换片时间，导出的视频会停在第 1 页——加 `--advance`（set-transitions）
  或 `--slide-seconds`（export 兜底）

完整命令与参数表见 [references/commands.md](references/commands.md)。

## 2. 参数决策指南

用户没明说时，按以下默认决策；只对影响结果较大的项询问用户：

| 决策点 | 默认 | 说明 |
|--------|------|------|
| 图片来源 | 必填 | 文件/目录/通配符可混用；目录默认不递归（`--recursive` 开启）；按文件名自然排序（img2 < img10）；`.webp` 会被跳过（先转 png/jpg） |
| 输出位置 | `<桌面>/photos2mp4_output/` | 不问用户，直接用默认目录；**禁止写进 skill 所在仓库**（脚本会拦截）。用户明确指定路径时才另存 |
| 每页秒数 `--advance` | 问用户或 5.0 | **视频节奏的唯一来源**。有音乐时可按 `总时长/页数` 估算，或用 `--auto-fit-music` 自动均分 |
| 切换效果 `--transition` | `fade` | 拿不准就用 fade；用户要"动感"选 push/wipe/zoom，要"炫"选 glitter/wheel/ripple。全表见 references/transitions.md |
| 图片适配 `--fit` | `contain` | 尺寸不一的照片用 contain（完整显示、留边）；壁纸式铺满用 cover；尺寸完全一致可用 stretch |
| 背景音乐 `--music` | 无 | mp3/m4a/wav/wma/aac/flac；默认循环播放到演示结束，音量 `--music-volume 1-100` |
| 画面比例 `--slide-size` | `16:9` | 预设 `16:9/4:3/16:10`，或任意像素 `720x1280`（竖屏照片集适用） |
| 导出规格 | 720p/30fps | `--resolution 480/720/1080`、`--fps 24/30/60`、`--quality 1-100` |

**必须先向用户确认的信息**（缺了不要猜；逐项询问，一次只问一个）：
1. 图片在哪（路径/目录）
2. 每页停留多久或视频总时长（给音乐时可用 `--auto-fit-music` 免答）

输出位置无需询问：默认写入 `<桌面>/photos2mp4_output/`，成功后把完整路径告诉用户即可。

## 3. 逐页切换 JSON（`--transitions-json`）

需要对每页配不同效果/节奏时，先写一个 JSON 文件（示例参考
`<skill_dir>/test_assets/transitions.json`）：

```json
[
  {"slide": 1, "transition": "fade",    "duration": 0.8, "advance": 3.0},
  {"slide": 2, "transition": "push",    "direction": "left", "advance": 2.5},
  {"slide": 4, "transition": "wheel",   "options": {"spokes": "3"}, "advance": 2.5}
]
```

`slide` 为 1 起始页码，省略时按数组顺序对应；字段均可选，未指定页沿用命令行全局值。
注意：某页显式指定了 `transition` 但未写 `direction` 时，**不会**继承全局
`--direction`（各效果方向取值互不兼容，避免拼出非法组合）。

## 4. 退出码与错误处理

| 码 | 含义 | 处理 |
|----|------|------|
| 0 | 成功 | 向用户报告产物路径与摘要 |
| 1 | 一般错误 | 读 stderr 日志定位后修复重试 |
| 2 | 参数/校验错误 | 检查命令拼写与取值 |
| 3 | PowerPoint 不可用/COM 失败/版本低于 2010 | 无 PowerPoint、未装 pywin32 或版本过旧（如 2007 无 CreateVideo）。降级方案：只 `build` 出 PPTX 交给用户手动放映/导出，并明确告知 |
| 4 | 导出超时/失败 | 可加大 `--timeout` 重试；检查 PPTX 是否被 PowerPoint 打开占用 |
| 130 | 用户中断 | 停止 |

常见问题速查（完整版见 references/commands.md）：
- **视频停在第 1 页** → PPTX 缺自动换片时间，`--advance` 或 `--slide-seconds`
- **PowerPoint 拒开生成的 PPTX** → 用 `list-transitions` 实测该效果是否被支持
- **中文乱码** → 旧 cmd 先 `chcp 65001`（脚本已强制 UTF-8 输出）

## 5. 输出规范

- 命令一律加 `--json`，用 stdout 的 JSON 判断结果；日志在 stderr
- 产物默认落在 `<桌面>/photos2mp4_output/`（或 `PHOTOS2MP4_OUT_DIR` 指定目录）；
  任何情况下都不得写入本 skill 所在仓库
- 成功后向用户汇报：MP4 完整路径、（保留的）PPTX 路径、页数、每页秒数、是否含音乐、分辨率
- 用户只要 PPTX 时，用 `build` 而非 `all`，并说明导出 MP4 的前提（Windows + PowerPoint）

## 6. 测试 / 演示

```bash
# 素材与产物均生成在 <桌面>/photos2mp4_output/ 下，不污染仓库
uv run <skill_dir>/make_test_assets.py
uv run <skill_dir>/pptx_video_builder.py all \
    --images <桌面>/photos2mp4_output/test_assets/images \
    --music  <桌面>/photos2mp4_output/test_assets/bgm.wav \
    --transitions-json <skill_dir>/test_assets/transitions.json --json

# 回归测试套件（临时文件走系统 temp，产物走 PHOTOS2MP4_OUT_DIR，均不入仓库）
uv run <skill_dir>/tests/run_tests.py --full
```

## 触发示例

- 帮我把这批照片做成一个视频，配上这首歌
- 把 D:\photos 里的图片生成一个 1080p 的相册视频，每张停 4 秒
- 这些图片做成幻灯片视频，要有转场效果
- 给这个 PPTX 加上淡入淡出切换，每页自动翻页 5 秒，导出成 MP4
- 把这个 pptx 转成 mp4

## 不适用场景

- 需要逐帧动画、字幕、画中画等视频剪辑 → 用视频剪辑工具/skill
- 图片带文字解说、需要排版设计 → 用幻灯片生成类 skill（再走本 skill 的 export）
- Linux/macOS 上导出 MP4（无 PowerPoint COM）→ 只能 build 出 PPTX
