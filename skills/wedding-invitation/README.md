# wedding-invitation

动森（动物森友会）风格电子婚礼请柬 H5 生成器 + 通用「HTML→竖屏 MP4」自动导出流水线。

## 快速开始

```bash
# 1. 生成请柬三变体 PPT（无切换无音乐 / 渐现无音乐 / 渐现带音乐，一次全出）
python3 scripts/generate_h5.py --groom 王青 --bride 桃十九 \
  --date 2026-10-03 --time 12:08 --venue "西安 · 温德姆大酒店" --emit-all

# 2. 第 4 步：导出竖屏 MP4（1080x1920，含合成 BGM，全流程自动：ffmpeg 自举/录制/配乐/转码）
python3 scripts/export_mp4.py --html 婚礼请柬-王青桃十九-PPT3-渐现带音乐.html
```

## 视频生成四步法（四产物缺一不可）

| 步 | 产物 | 内容 |
|---|---|---|
| 1 | `*-PPT1-无切换无音乐.html` | 翻页瞬切、无渐现/浮现动效、无 BGM |
| 2 | `*-PPT2-渐现无音乐.html` | 渐现（现出）翻页与浮现动效、无 BGM |
| 3 | `*-PPT3-渐现带音乐.html` | 渐现动效 + 页面内置 BGM |
| 4 | `*.mp4` | 按 PPT3 录制 + synth_bgm 按时间轴合成配乐的成片 |

步骤 1~3 可用 `--emit-all` 一条命令产出；也可用 `--fx none|fade --music on|off` 单独生成某变体。

## 脚本清单

| 脚本 | 用途 |
|---|---|
| scripts/generate_h5.py | 参数化生成动森请柬 HTML（7 页：票券/护照/打字对话/倒计时/相册…；--fx/--music 控制动效与音乐变体，--emit-all 一次出三个 PPT） |
| scripts/export_mp4.py | HTML→MP4 总编排 |
| scripts/record_page.py | Playwright 无头浏览器自动翻页录制（webm + timeline.json） |
| scripts/synth_bgm.py | 纯标准库合成动森风 BGM 音轨（与翻页时刻精确对齐） |
| scripts/ensure_ffmpeg.py | ffmpeg 探测/自举（PyPI 镜像 wheel 提取，WSL 坑位已处理） |

## 测试

```bash
cd <skill_dir> && python3 -m unittest discover -s tests -v
```

## 文档

- 使用与触发：见 [SKILL.md](SKILL.md)
- 视觉规范：[references/design-guide.md](references/design-guide.md)
- 导出流水线原理：[references/html2mp4-guide.md](references/html2mp4-guide.md)
- 踩坑记录：[references/tech-notes.md](references/tech-notes.md)

## 依赖

- Python 3.9+（全部脚本纯标准库）
- MP4 导出：Node.js + Chrome/Edge（自动探测）；ffmpeg 自动获取，无需 root
