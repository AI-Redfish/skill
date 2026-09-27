---
name: wedding-invitation
description: 制作动森(动物森友会)风格电子婚礼请柬 H5 页面，并把任意本地 HTML 页面自动翻页录制导出为竖屏 MP4 短片（1080x1920，含动森风合成 BGM）。当用户说「帮我做电子请柬/婚礼邀请函/H5 请柬」「把这个 HTML 页面导出成视频/MP4」「网页做成竖屏演示视频」「请柬配背景音乐自动播放」「要无效果/渐现/带音乐多种版本」时使用。视频生成固定四步四产物：①无切换无音乐 PPT ②渐现无音乐 PPT ③渐现带音乐 PPT ④MP4 成片，四个都要交付。覆盖参数化生成请柬（姓名/日期/场地/文案）、Playwright 无头浏览器自动翻页录制、纯代码合成音轨并精确对齐、ffmpeg 转码全流程。
compatibility: 脚本 Python 3.9+ 纯标准库（python3 直跑，无需 uv）；MP4 导出另需 node+npm 与 Chrome/Edge（自动探测），ffmpeg 缺失时自动从 PyPI 镜像获取；Windows/WSL/Linux 均可（WSL 坑位已固化处理）。
metadata:
  author: AI-Redfish
  version: "1.0.0"
---

# wedding-invitation — 动森风婚礼请柬 H5 + HTML→MP4 自动导出

两大能力：**A.** 一条命令参数化生成零依赖的动森风电子请柬 H5 单文件（翻页式 PPT，
可产出「无切换无音乐 / 渐现无音乐 / 渐现带音乐」三变体）；
**B.** 通用「HTML→竖屏 MP4」导出流水线（录制+配乐+转码），可脱离请柬独立复用。

```
场景A(请柬)     : 问信息(一次一问) → generate_h5.py → 用户预览确认 → (可选)场景B
场景B(视频四步) : ①PPT1无切换无音乐 → ②PPT2渐现无音乐 → ③PPT3渐现带音乐
                  → ④export_mp4.py 录制PPT3出MP4；四个产物全部保留交付
```

## 视频生成四步法（仅次于「双闭环」的最高优先级）

只要用户要「视频/成片」，必须按固定四步执行，**四个产物缺一不可，全部保留交付**：

| 步 | 产物 | 效果 | 生成命令（generate_h5.py 选项） |
|---|---|---|---|
| 1 | PPT1-无切换无音乐 | 翻页瞬切、无渐现/浮现动效、无 BGM | `--fx none --music off` |
| 2 | PPT2-渐现无音乐 | 带渐现（现出）翻页与浮现动效、无 BGM | `--fx fade --music off` |
| 3 | PPT3-渐现带音乐 | 渐现动效 + 页面内置 BGM | `--fx fade --music on` |
| 4 | MP4 视频 | 按 PPT3 录制转码，音轨由 synth_bgm 精确对齐合成 | `export_mp4.py --html <PPT3>` |

- 第 1~3 步推荐用 `--emit-all` 一条命令产出三个 PPT 文件（见场景 B 示例）
- 三个 PPT 的内容/版式完全一致，仅切换动效与音频不同；默认与请柬同目录同名不同后缀
- 第 4 步录制的画面不含音频；MP4 音轨由 synth_bgm.py 按同一乐谱/时间轴独立合成混流
- 用户只要视频时，也默认交付四件套（除非明确说只要 MP4）

## 双闭环流程（最高优先级，优先于其他任何行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环
1. 回答前先提问，**每次只问一个问题**，根据回答继续追问
2. 提问围绕：真实目标、背景、使用场景、输出对象、关键约束、优先级、
   成功标准、禁止事项、已有信息、可接受偏差
3. 对“用户真正想要什么”有 95% 信心才停止提问；未达 95% 只提问澄清，
   不给最终方案（用户消息已足以达到 95% 信心时可直接执行，
   但最终输出必须列出关键假设）

### 第二闭环：输出审查闭环
1. 形成答案后不直接输出，先自查：是否真正解决目标？是否遗漏关键约束？
   是否存在事实错误、逻辑漏洞、歧义、不可执行之处？
2. 发现问题→自行修正→再次审查，重复“审查—修正—再审查”，
   直到对输出结果至少有 95% 的准确性信心

### 最终输出要求
1. 先一句话复述用户真实需求
2. 再给出最终方案：明确、可执行、可直接使用
3. 说明关键假设、剩余不确定性，以及为什么已达到 95% 信心；
   不确定处明确标注，不假装确定

## 路径与输出位置约定

- `<skill_dir>` = 本 SKILL.md 所在目录；脚本一律 `python3 <skill_dir>/scripts/xxx.py` 调用
- 产物（HTML/MP4）默认写到**当前工作目录**或用户指定目录，绝不写入 skill 目录
- MP4 导出的临时目录 `<html同目录>/<html主名>-export/` 默认用后即删（`--keep-temp` 保留）

## 环境信息

本 skill **不需要任何账号/密码/令牌**，无 `.agents/.env` 键。

## 场景 A：生成动森风婚礼请柬 H5

1. **必问信息**（理解闭环，一次一问；已给出则跳过）：
   新郎/新娘姓名 → 婚礼日期(YYYY-MM-DD) → 场地名称与地址 →（可选）仪式时间、
   护照人设(头像 emoji/性格/最爱)、自定义打字文案
2. 生成（信息齐备后执行）：

```bash
python3 <skill_dir>/scripts/generate_h5.py \
  --groom 王青 --bride 桃十九 --date 2026-10-03 --time 12:08 \
  --venue "西安 · 温德姆大酒店" --addr "陕西省西安市温德姆大酒店" \
  --map-keyword "西安温德姆大酒店" --out 请柬.html
```

3. 让用户浏览器打开预览；确认后进入场景 B 视频生成四步法（四产物）
4. 视觉规范、文案模板、照片替换方法见 [references/design-guide.md](references/design-guide.md)

## 场景 B：视频生成四步法 → 竖屏 MP4（通用）

本 skill 生成的请柬：第 1~3 步一条命令出三个 PPT，第 4 步出视频：

```bash
# 第 1~3 步：一次生成 PPT1-无切换无音乐 / PPT2-渐现无音乐 / PPT3-渐现带音乐
python3 <skill_dir>/scripts/generate_h5.py \
  --groom 王青 --bride 桃十九 --date 2026-10-03 --time 12:08 \
  --venue "西安 · 温德姆大酒店" --addr "陕西省西安市温德姆大酒店" --emit-all
# → 婚礼请柬-王青桃十九-PPT1-无切换无音乐.html
# → 婚礼请柬-王青桃十九-PPT2-渐现无音乐.html
# → 婚礼请柬-王青桃十九-PPT3-渐现带音乐.html

# 第 4 步：录制 PPT3 导出 MP4（画面无音频，BGM 由 synth_bgm 按时间轴合成混流）
python3 <skill_dir>/scripts/export_mp4.py \
  --html 婚礼请柬-王青桃十九-PPT3-渐现带音乐.html \
  --stay "1500,5000,6000,9000,6500,5500,4500"
# 常用可选: --out 视频.mp4 --out-size 1080x1920 --no-bgm
#           --nav-mode go|selector|none --nav-selector ".next" --start-selector "#startBtn|none"
```

也可单独生成某一变体：`generate_h5.py ... --fx none|fade --music on|off --out 路径`。

**外部通用 HTML**（非本 skill 生成）没有变体概念，只有第 4 步。前提确认（一次一问）：
页面是否有全局翻页函数 `window.go(n)`（本 skill 生成的请柬有）？
没有则确认「下一页」按钮选择器或选择不翻页模式。

```bash
python3 <skill_dir>/scripts/export_mp4.py --html 请柬.html \
  --stay "1500,5000,6000,9000,6500,5500,4500"     # 每页停留 ms, 长度=页数
```

原理、时间轴对齐机制、参数调优、组件单独调用见
[references/html2mp4-guide.md](references/html2mp4-guide.md)；
WSL/npm/镜像等踩坑速查见 [references/tech-notes.md](references/tech-notes.md)。

## 参数决策指南

| 决策点 | 默认 | 说明 |
|---|---|---|
| 请柬必填信息 | 无 | 姓名/日期/场地缺失 → 进入理解闭环逐项问 |
| 仪式时间 | 12:08 | 页面已标注 `*`，需向用户确认 |
| 导出分辨率 | 1080x1920 竖屏 | 用户可指定如 720x1280 |
| 视频四产物 | 四件全出 | PPT1/PPT2/PPT3/MP4 缺一不可；用户明确只要 MP4 才可省略 PPT |
| 翻页动效 | fade(渐现) | `--fx none` = 无任何切换效果（PPT1 用） |
| 页面 BGM | on | `--music off` = 无音乐（PPT1/PPT2 用）；与 MP4 音轨互相独立 |
| 每页停留 | 7 段默认值(共约 38s) | 打字机页建议 ≥8000ms |
| 翻页模式 | go(请柬自带) | 通用页面按实际接口选择 |
| ffmpeg 来源 | 自动获取(PyPI wheel) | 系统已有则直接用 |

## 错误处理

| 退出码/现象 | 含义 | 处理 |
|---|---|---|
| exit 2 | 参数/输入错误 | 按 JSON error.message 修正参数 |
| ensure_ffmpeg 失败 | 镜像不可达 | 换网络/代理重试；或手动安装 ffmpeg 入 PATH |
| record_page: 未找到 node | 环境缺 Node | 安装 Node.js(nvm 常见路径会自动扫描) |
| record_page: 未找到浏览器 | 缺 Chrome/Edge | 安装任一即可 |
| record_page: playwright 安装失败 | 网络受限 | 设 npm 镜像(`npm config set registry`)重试 |
| record_page: 录制失败 | 页面/选择器问题 | `--keep-temp` + 手动跑 record.mjs 看 stderr |
| export_mp4: 转码失败 | webm/wav 异常 | `--keep-temp` 保留产物排查 |

## 输出规范

- 所有脚本 JSON 到 stdout（`status/...`），日志到 stderr；先读退出码与 JSON 再行动
- 交付时逐一汇报**四个产物绝对路径**（PPT1-无切换无音乐 / PPT2-渐现无音乐 /
  PPT3-渐现带音乐 / MP4），并附 MP4 的时长、分辨率、大小、音轨有无、降级项（如有）
- `--emit-all` 的 JSON 在 `variants` 数组里给出三个 PPT 的 path/fx/music

## 触发示例

- 帮我做一个动森风格的电子婚礼请柬，新郎王青新娘桃十九
- 把这个请柬 HTML 导出成竖屏视频发朋友圈
- 导出视频时把无效果 PPT、渐现 PPT、带音乐 PPT 和成片四种产物都给我
- 我们 10 月 3 号在西安温德姆办婚礼，做个 H5 邀请函还要能配音乐自动播放
- 把这个本地网页做成 1080x1920 的 MP4 演示视频

## 不适用场景

- 纸质请柬/平面设计排版（用设计工具类 skill）
- 给已有视频做剪辑、加字幕、转码（用视频处理工具）
- 咨询在线请柬平台（婚纪、易企秀等）的选型与使用 → 直接解答
- 需要真人出镜拍摄/实拍剪辑的婚礼影片
