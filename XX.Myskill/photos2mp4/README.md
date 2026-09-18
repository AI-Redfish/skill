# pptx_video_builder — 批量图片 + 背景音乐 → PPTX → MP4 视频

一个 Python 命令行工具：把一批图片组装成 PPTX（一图一页、可配切换效果、自动换片、
跨页循环背景音乐），并可调用本机 **Microsoft PowerPoint** 将其导出为 **MP4 视频**。

专为 AI Skill 场景设计：命令即能力、JSON 输出、退出码语义明确，AI 可直接调用。

## 文件结构

```
├── pptx_video_builder.py    # 主脚本（全部能力所在）
├── make_test_assets.py      # 测试素材生成器（纯标准库，零依赖）
├── test_assets/             # 测试素材：6 张不同尺寸的图片 + 26s 背景音乐 + 逐页切换示例
│   ├── images/*.png
│   ├── bgm.wav
│   └── transitions.json
└── .venv/                   # uv 创建的 Python 虚拟环境（python-pptx + pywin32 已装好）
```

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.9+ | 建议 3.12 |
| `python-pptx` | 必装（build / set-transitions / selftest） |
| `pywin32` | export / list-transitions 实测需要；**需本机安装 Microsoft PowerPoint 2010+**（WPS 不支持） |
| `mutagen` | 可选，仅 `--auto-fit-music` 需要 |

### 用 uv 一键准备环境（推荐）

```bat
uv venv .venv --python 3.12
uv pip install --python .venv python-pptx pywin32
```

下文命令均以 `.venv\Scripts\python.exe` 调用（也可激活 venv 后直接用 `python`）。

## 快速开始（一条龙：图片 + 音乐 → MP4）

```bat
:: 1. 生成测试素材（可选，已有素材可跳过）
.venv\Scripts\python.exe make_test_assets.py

:: 2. 图片 + 音乐 直接出视频
.venv\Scripts\python.exe pptx_video_builder.py all ^
    --images test_assets\images --music test_assets\bgm.wav ^
    --output test_assets\my_video.mp4 ^
    --transition fade --transition-duration 0.8 --advance 3
```

产物：`test_assets\my_video.pptx`（中间产物，可留作手动放映）与
`test_assets\my_video.mp4`（约 6 页 × 3 秒，含背景音乐）。

---

## 命令详解

### 1. `build` — 图片(+音乐) → PPTX

```bat
python pptx_video_builder.py build --images <路径...> --output <out.pptx> [选项]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--images <路径...>` | 必填 | 图片文件 / 目录 / 通配符，可混用多个；按文件名**自然排序**（img2 < img10） |
| `--output <文件>` | 必填 | 输出 `.pptx` 路径 |
| `--recursive` | 关 | 目录递归收集图片 |
| `--fit <模式>` | `contain` | contain 等比完整显示 / cover 等比铺满裁边 / stretch 拉伸 |
| `--background <色>` | `black` | 背景色：颜色名（`black/white/navy…`）或 `#RRGGBB` |
| `--slide-size <尺寸>` | `16:9` | `16:9` / `4:3` / `16:10` / `1280x720`（像素@96dpi） |
| `--music <文件>` | 无 | 背景音乐：mp3 / m4a / wav / wma / aac / flac |
| `--music-no-loop` | 关 | 不循环（默认循环播放到结束） |
| `--music-volume <1-100>` | 100 | 音量 |
| `--auto-fit-music` | 关 | 按音乐时长均分每页停留时间（需 mutagen），视频随音乐结束 |
| `--transition <名>` | `fade` | 全部页的切换效果，见下方效果表 |
| `--direction <方向>` | 无 | 方向：`left/right/up/down`、`horz/vert`、`in/out`、`throughblack`… |
| `--transition-duration <秒>` | 无 | 切换动画时长（0.1~10s；需 PPT 2010+，旧版降级为快/中/慢） |
| `--advance <秒>` | 5.0 | 每页停留秒数（自动换片；**导出视频的节奏来源**，0=手动） |
| `--opt <键=值>` | 可重复 | 附加参数，如 `--opt spokes=3`、`--opt pattern=hexagon` |
| `--transitions-json <文件>` | 无 | 逐页覆盖，见下文 |
| `--json` | 关 | 结果以 JSON 输出到 stdout |

### 2. `set-transitions` — 修改已有 PPTX 的切换方式

```bat
python pptx_video_builder.py set-transitions --pptx <文件> --transition <名> [选项]
```

- `--transition` 与 `--transitions-json` 至少给一个；其余参数同 `build`
- `--advance` 缺省时**沿用文件中原有的换片时间**
- 只改换片时间也行：`--advance 4`（自动以无效果切换承载）
- 逐页 JSON 中含 `advance` 的页以 JSON 为准

### 3. `list-transitions` — 切换效果目录 + 本机实测

```bat
python pptx_video_builder.py list-transitions [--json] [--no-verify]
```

默认启动本机 PowerPoint 做**真实探测**（生成探针文件 → 让 PowerPoint 重新保存 →
比对切换 XML 是否存活），输出每个效果 `[支持] / [不支持]`。
`--no-verify` 跳过实测仅输出理论目录。PowerPoint 不可用时仍输出目录，退出码 3。

### 4. `export` — PPTX → MP4

```bat
python pptx_video_builder.py export --pptx <in.pptx> --output <out.mp4> [选项]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--resolution` | 720 | `480` / `720` / `1080` |
| `--fps` | 30 | `24` / `30` / `60` |
| `--quality` | 85 | 1~100 |
| `--timeout <秒>` | 1800 | 导出超时 |
| `--slide-seconds <秒>` | 自动 | 无换片时间页面的兜底时长 |

> ⚠️ 视频节奏来自每页的自动换片时间（`--advance`）。若 PPTX 完全没有换片时间，
> 导出会给出警告，视频可能停在第 1 页。

### 5. `all` — build + export 一条龙

```bat
python pptx_video_builder.py all --images <路径...> --output <out.mp4> [build 选项 + export 选项]
```

中间 PPTX 默认生成在与视频同名的 `.pptx`，可用 `--pptx` 指定路径。

### 6. `selftest` — 离线自检（不需要 PowerPoint）

```bat
python pptx_video_builder.py selftest [--keep] [--json]
```

11 项检查：包结构 / 全部经典切换 XML / p14+morph 兼容包裹与必填属性 /
set-transitions / contain·cover·stretch 几何 / 自然排序 / 逐页 JSON /
参数校验 / CLI 冒烟 / 音乐循环音量 / 切换时长降级。

---

## 逐页切换 JSON（`--transitions-json`）

```json
[
  {"slide": 1, "transition": "fade",    "duration": 0.8, "advance": 3.0},
  {"slide": 2, "transition": "push",    "direction": "left", "advance": 2.5},
  {"slide": 3, "transition": "wipe",    "direction": "up", "advance": 2.5},
  {"slide": 4, "transition": "wheel",   "options": {"spokes": "3"}, "advance": 2.5},
  {"slide": 5, "transition": "reveal",  "direction": "throughblack", "advance": 2.5},
  {"slide": 6, "transition": "glitter", "direction": "l", "options": {"pattern": "hexagon"}, "advance": 3.5}
]
```

- `slide`：1 起始页码；**省略时按数组位置顺序对应**（第 1 个未指定者→第 1 页）
- 每个字段均可选；未指定的页沿用命令行全局值
- `direction` 友好别名自动归一化：`left→l`、`up→u`、`horizontal→horz`、`throughblack`…

## 切换效果总表（40 种）

### 经典（PowerPoint 2007+，21 种）

| 名称 | direction | 其它参数 |
|------|-----------|----------|
| blinds / checker / comb | `horz`\|`vert` | |
| circle / diamond / dissolve / newsflash / plus / random / wedge | — | |
| cover / pull | `d`\|`l`\|`r`\|`u`\|`ld`\|`lu`\|`rd`\|`ru` | |
| cut / fade | `throughblack` | |
| push / wipe | `d`\|`l`\|`r`\|`u` | |
| randombar | `horz`\|`vert` | |
| split | `in`\|`out` | `orient=horz\|vert` |
| strips | `ld`\|`lu`\|`rd`\|`ru` | |
| wheel | `1`\|`2`\|`3`\|`4`\|`8` | 或 `--opt spokes=N` |
| zoom | `in`\|`out` | |

### PowerPoint 2010+（18 种，旧版自动回退为 fade）

| 名称 | direction | 其它参数 |
|------|-----------|----------|
| conveyor★ / ferris★ / flip★ / gallery★ / switch★ | `l`\|`r` | |
| vortex | `l`\|`r` | |
| flythrough | `in`\|`out` | `hasBounce=0\|1` |
| glitter | `d`\|`l`\|`r`\|`u` | `pattern=diamond\|hexagon` |
| shred | `in`\|`out` | `pattern=strip\|rectangle` |
| reveal | `throughblack` | |
| warp | `in`\|`out` | |
| doors / flash / honeycomb / pan / prism / ripple / window | — | |

★ `dir` 为 schema 必填属性，未指定时自动补 `l`（PowerPoint 严格校验，缺失会拒开文件）。

### PowerPoint 2019/365（1 种）

| 名称 | 其它参数 |
|------|----------|
| morph（平滑，对纯图片页无意义） | `option=byObject\|byWord\|byChar`（必填，自动补 `byObject`） |

## 背景音乐行为

写入第 1 页（OOXML 音频形状 + 时间轴）：

- 放映/导出视频时**自动开始播放**，**跨全部幻灯片**（numSld=999）
- 默认**循环**直到演示结束（`--music-no-loop` 关闭）
- 音乐图标放在页面外 + `showWhenStopped=0`，**放映和视频中不可见**
- 导出 MP4 时音乐会被渲染进视频音轨

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数 / 校验错误 |
| 3 | PowerPoint 不可用或 COM 操作失败 |
| 4 | 导出超时 / 失败 |
| 130 | 用户中断 |

日志走 **stderr**；`--json` 时数据走 **stdout**（便于 AI 解析）。

## 常见问题

- **报“PowerPoint 不可用”（退出码 3）**：未安装 Microsoft PowerPoint 或 pywin32；
  WPS 无法替代 PowerPoint 的 COM 接口。
- **视频停在第 1 页**：PPTX 缺少自动换片时间。`build` 加 `--advance 秒`，
  或 `export` 加 `--slide-seconds 秒`。
- **`.webp` 图片被跳过**：PowerPoint 兼容性考虑，请先转成 png/jpg。
- **中文乱码**：脚本已强制 UTF-8 输出；旧 cmd 可先执行 `chcp 65001`。
- **机器间的效果差异**：以 `list-transitions` 实测结果为准（不同 PowerPoint
  版本对个别效果的支持与存留可能不同）。

## 作为 AI Skill 的调用范式

```text
1. python pptx_video_builder.py selftest                       # 验证环境
2. python pptx_video_builder.py list-transitions --json        # 获取可用效果矩阵
3. python pptx_video_builder.py all \
       --images <dir> --music <file> --output <out.mp4> \
       --transition <效果> --advance <每页秒数> [--json]        # 产出视频
   # 需要逐页节奏/效果时，先写 transitions.json 再加 --transitions-json
```

判断依据：退出码 0 = 成功；3 = 无 PowerPoint（改用仅 build 的流程）；
其他非零 = 读取 stderr 日志定位。
