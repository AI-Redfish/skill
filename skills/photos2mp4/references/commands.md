# 命令与参数详解

> 本文件是 SKILL.md 的扩展参考，按需加载。`<skill_dir>` 指 skill 根目录。

## 依赖管理（uv / PEP 723）

- 三个脚本头部均带 PEP 723 内联依赖声明：
  - `pptx_video_builder.py` / `tests/run_tests.py`：
    `python-pptx` + `pywin32(仅 sys_platform=='win32')` + `mutagen`
  - `make_test_assets.py`：零依赖
- **统一用 `uv run <脚本> ...`**：uv 自动解析依赖、构建缓存环境（存于 uv 全局
  缓存，不在 skill 目录建 venv/pyproject），首次稍慢、之后秒级启动
- `--auto-fit-music` 所需的 mutagen 已含在内联依赖中，无需额外参数
- 无 uv 环境的兑底：已装齐依赖时可直接 `python <脚本> ...`（PEP 723 块是纯注释）
- 升级依赖版本：改脚本头部声明中的版本约束后，uv 会自动重新解析
- 受限网络（直连 pypi 失败）：设置镜像源环境变量，如
  `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`

## 输出位置与仓库保护

- `build / export / all` 的 `--output` 均可省略：
  - build / all：写入默认产物目录 `<桌面>/photos2mp4_output/photos_<时间戳>.<ext>`
  - export：写入 `<默认产物目录>/<pptx同名>.mp4`
  - 环境变量 `PHOTOS2MP4_OUT_DIR` 可重定向默认产物目录
- 脚本内置守卫：目标路径位于本 skill 所在 git 仓库内时直接拒绝（退出码 2），
  错误信息含建议目录；`PHOTOS2MP4_ALLOW_REPO_OUTPUT=1` 可显式放行
- `selftest` / `list-transitions` 实测的临时文件均写入系统 temp，不落仓库

## 1. `build` — 图片(+音乐) → PPTX

```bash
uv run <skill_dir>/pptx_video_builder.py build --images <路径...> [--output <out.pptx>] [选项]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--images <路径...>` | 必填 | 图片文件 / 目录 / 通配符，可混用多个；按文件名**自然排序**（img2 < img10） |
| `--output <文件>` | 默认目录 | 输出 `.pptx` 路径；缺省写入 `<桌面>/photos2mp4_output/`（时间戳命名） |
| `--recursive` | 关 | 目录递归收集图片 |
| `--fit <模式>` | `contain` | contain 等比完整显示 / cover 等比铺满裁边 / stretch 拉伸 |
| `--background <色>` | `black` | 背景色：颜色名（`black/white/navy…`）或 `#RRGGBB` |
| `--slide-size <尺寸>` | `16:9` | `16:9` / `4:3` / `16:10` / 任意像素 `1280x720`（@96dpi） |
| `--music <文件>` | 无 | 背景音乐：mp3 / m4a / wav / wma / aac / flac |
| `--music-no-loop` | 关 | 不循环（默认循环播放到结束） |
| `--music-volume <1-100>` | 100 | 音量 |
| `--auto-fit-music` | 关 | 按音乐时长均分每页停留时间（需 mutagen），视频随音乐结束 |
| `--transition <名>` | `fade` | 全部页的切换效果，见 [transitions.md](transitions.md) |
| `--direction <方向>` | 无 | 方向：`left/right/up/down`、`horz/vert`、`in/out`、`throughblack`… |
| `--transition-duration <秒>` | 无 | 切换动画时长（0.1~10s；需 PPT 2010+，旧版降级为快/中/慢） |
| `--advance <秒>` | 5.0 | 每页停留秒数（自动换片；**导出视频的节奏来源**，0=手动） |
| `--opt <键=值>` | 可重复 | 附加参数，如 `--opt spokes=3`、`--opt pattern=hexagon` |
| `--transitions-json <文件>` | 无 | 逐页覆盖，见 [transitions.md](transitions.md) |
| `--json` | 关 | 结果以 JSON 输出到 stdout |

## 2. `set-transitions` — 修改已有 PPTX 的切换方式

```bash
uv run <skill_dir>/pptx_video_builder.py set-transitions --pptx <文件> --transition <名> [选项]
```

- `--transition` / `--transitions-json` / `--advance` 至少给一个
- `--advance` 缺省时**沿用文件中原有的换片时间**
- 只改换片时间也行：`set-transitions --pptx <文件> --advance 4` ——
  已有切换效果会被保留，仅原地更新 advTm；无切换的页面以 none 承载
- 逐页 JSON 中含 `advance` 的页以 JSON 为准
- 就地修改目标 PPTX，不产生新文件，不受仓库守卫限制

## 3. `list-transitions` — 切换效果目录 + 本机实测

```bash
uv run <skill_dir>/pptx_video_builder.py list-transitions [--json] [--no-verify]
```

默认启动本机 PowerPoint 做**真实探测**（生成探针文件 → 让 PowerPoint 重新保存 →
比对切换 XML 是否存活；探针文件走系统 temp），输出每个效果 `[支持] / [不支持]`。
低于要求版本的档次（如 PowerPoint 2007 遇到 2010+ 效果）会直接标记为不支持并附
`requires_powerpoint_*` 注记——因为旧版会原样保留兼容包裹 XML，实测会误报支持。
`--no-verify` 跳过实测仅输出理论目录。PowerPoint 不可用时仍输出目录，退出码 3。

用途：不同 PowerPoint 版本对个别效果的支持与存留可能不同；生成的 PPTX 在
PowerPoint 中打不开时，先用它排查是哪个效果导致的。

## 4. `export` — PPTX → MP4

```bash
uv run <skill_dir>/pptx_video_builder.py export --pptx <in.pptx> [--output <out.mp4>] [选项]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--output <文件>` | `<默认目录>/<pptx同名>.mp4` | 输出 `.mp4` 路径 |
| `--resolution` | 720 | `480` / `720` / `1080` |
| `--fps` | 30 | `24` / `30` / `60` |
| `--quality` | 85 | 1~100 |
| `--timeout <秒>` | 1800 | 导出超时 |
| `--slide-seconds <秒>` | 自动 | 无换片时间页面的兜底时长 |

> ⚠️ 视频节奏来自每页的自动换片时间（`--advance`）。若 PPTX 完全没有换片时间，
> 导出会给出警告，视频可能停在第 1 页。

> 导出过程中不要让 PowerPoint 弹出任何对话框占用；大文件注意 `--timeout`。

## 5. `all` — build + export 一条龙

```bash
uv run <skill_dir>/pptx_video_builder.py all --images <路径...> [--output <out.mp4>] [build 选项 + export 选项]
```

中间 PPTX 默认生成在与视频同名的 `.pptx`（同一目录），可用 `--pptx` 指定路径；
`--output` 缺省时视频与中间 PPTX 均写入默认产物目录。

## 6. `selftest` — 离线自检（不需要 PowerPoint）

```bash
uv run <skill_dir>/pptx_video_builder.py selftest [--keep] [--json]
```

11 项检查：包结构 / 全部经典切换 XML / p14+morph 兼容包裹与必填属性 /
set-transitions / contain·cover·stretch 几何 / 自然排序 / 逐页 JSON /
参数校验 / CLI 冒烟 / 音乐循环音量 / 切换时长降级。临时文件走系统 temp。

## 7. `make_test_assets.py` — 测试素材生成器（零依赖）

```bash
uv run <skill_dir>/make_test_assets.py
```

在默认产物目录的 `test_assets/` 子目录下生成 6 张不同尺寸 PNG + 约 26s 背景音乐
WAV；可用 `PHOTOS2MP4_OUT_DIR` 重定向。不写入 skill 目录，避免污染 git 工作区。
逐页切换示例 `transitions.json` 随 skill 自带于 `<skill_dir>/test_assets/`。

## 8. `tests/run_tests.py` — 回归测试套件

```bash
uv run <skill_dir>/tests/run_tests.py [--full] [--keep] [-k 关键词]
```

覆盖：selftest / build 各参数组合 / 音乐循环与音量 / 三种 fit 几何 / 页面尺寸与
背景色 / 逐页 JSON / p14 兼容包裹 / auto-fit / 参数错误 / **默认输出目录 /
仓库守卫** / set-transitions / list-transitions / 100 图性能 / export（无
PowerPoint 环境自动 SKIP）。临时文件走系统 temp，产物走 `PHOTOS2MP4_OUT_DIR`，
均不落仓库。退出码 0 = 全部通过。

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数 / 校验错误（含仓库守卫拒绝写入） |
| 3 | PowerPoint 不可用或 COM 操作失败 |
| 4 | 导出超时 / 失败 |
| 130 | 用户中断 |

日志走 **stderr**；`--json` 时数据走 **stdout**（便于 AI 解析）。

## 常见问题

- **报"PowerPoint 不可用"（退出码 3）**：未安装 Microsoft PowerPoint 或 pywin32；
  WPS 无法替代 PowerPoint 的 COM 接口。
- **报"拒绝把…写入本 skill 所在仓库"（退出码 2）**：输出路径落在 skill 所在 git
  仓库内。改用仓库外路径或使用默认目录；确有需要时设 `PHOTOS2MP4_ALLOW_REPO_OUTPUT=1`。
- **视频停在第 1 页**：PPTX 缺少自动换片时间。`build` 加 `--advance 秒`，
  或 `export` 加 `--slide-seconds 秒`。
- **`.webp` 图片被跳过**：PowerPoint 兼容性考虑，请先转成 png/jpg。
- **中文乱码**：脚本已强制 UTF-8 输出；旧 cmd 可先执行 `chcp 65001`。
- **机器间的效果差异**：以 `list-transitions` 实测结果为准（不同 PowerPoint
  版本对个别效果的支持与存留可能不同）。
