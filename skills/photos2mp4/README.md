# photos2mp4 — 批量图片 + 背景音乐 → PPTX → MP4 视频（AI Skill）

一个 Agent Skill：把一批图片组装成 PPTX（一图一页、可配切换效果、自动换片、
跨页循环背景音乐），并可调用本机 **Microsoft PowerPoint** 将其导出为 **MP4 视频**。

专为 AI 调用设计：命令即能力、JSON 输出、退出码语义明确。

## 文件结构

```
photos2mp4/
├── SKILL.md                # Skill 主指令（agent 加载入口）
├── pptx_video_builder.py   # 主脚本（全部能力所在）
├── make_test_assets.py     # 测试素材生成器（纯标准库，零依赖）
├── tests/
│   └── run_tests.py        # 回归测试套件（不依赖 pytest）
├── references/             # 扩展参考（按需加载）
│   ├── commands.md         # 全部命令完整参数、退出码、常见问题
│   └── transitions.md      # 40 种切换效果总表、逐页 JSON、背景音乐行为
└── test_assets/
    └── transitions.json    # 逐页切换示例（随 skill 自带）
```

**产物不落仓库**：PPTX/MP4 默认写入 `<桌面>/photos2mp4_output/`；测试素材、
selftest/实测探针等临时文件走系统 temp 或该产物目录。脚本内置守卫，拒绝把
产物写进本 skill 所在 git 仓库。详见 [references/commands.md](references/commands.md)。

## 环境要求

依赖用 **uv** 管理（脚本头部 PEP 723 内联声明，`uv run` 自动解析缓存，
不在本目录创建任何环境文件）：

| 依赖 | 说明 |
|------|------|
| uv + Python 3.9+ | `uv run` 自动装 python-pptx / pywin32(仅 Windows) / mutagen |
| Microsoft PowerPoint 2010+ | 仅 export / list-transitions 实测需要（WPS 不支持）；仅 build 无此要求 |

无 uv 时：`winget install --id=astral-sh.uv`（Windows）或
`curl -LsSf https://astral.sh/uv/install.sh | sh`；已装齐依赖的环境也可直接 python 运行。

## 快速开始

```bat
:: 1. 离线自检（首次自动装依赖并缓存，之后秒起）
uv run pptx_video_builder.py selftest

:: 2. 图片 + 音乐 直接出视频（--output 可省略，默认写入 <桌面>\photos2mp4_output\）
uv run pptx_video_builder.py all ^
    --images <图片目录> --music <音乐文件> ^
    --transition fade --transition-duration 0.8 --advance 3 --json

:: 3. 回归测试（可选）
uv run tests\run_tests.py
```

产物：MP4 与中间 PPTX 均在 `<桌面>\photos2mp4_output\`，不污染本仓库。

## 文档

- Agent 调用方式与工作流：[SKILL.md](SKILL.md)
- 命令与参数详解：[references/commands.md](references/commands.md)
- 切换效果总表：[references/transitions.md](references/transitions.md)
