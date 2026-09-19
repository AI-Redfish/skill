---
name: wedding-invitation
description: 制作动森(动物森友会)风格电子婚礼请柬 H5 页面，并把任意本地 HTML 页面自动翻页录制导出为竖屏 MP4 短片（1080x1920，含动森风合成 BGM）。当用户说「帮我做电子请柬/婚礼邀请函/H5 请柬」「把这个 HTML 页面导出成视频/MP4」「网页做成竖屏演示视频」「请柬配背景音乐自动播放」时使用。覆盖参数化生成请柬（姓名/日期/场地/文案）、Playwright 无头浏览器自动翻页录制、纯代码合成音轨并精确对齐、ffmpeg 转码全流程。
compatibility: 脚本 Python 3.9+ 纯标准库（python3 直跑，无需 uv）；MP4 导出另需 node+npm 与 Chrome/Edge（自动探测），ffmpeg 缺失时自动从 PyPI 镜像获取；Windows/WSL/Linux 均可（WSL 坑位已固化处理）。
metadata:
  author: AI-Redfish
  version: "1.0.0"
---

# wedding-invitation — 动森风婚礼请柬 H5 + HTML→MP4 自动导出

两大能力：**A.** 一条命令参数化生成零依赖的动森风电子请柬 H5 单文件；
**B.** 通用「HTML→竖屏 MP4」导出流水线（录制+配乐+转码），可脱离请柬独立复用。

```
场景A(请柬)   : 问信息(一次一问) → generate_h5.py → 用户预览确认 → (可选)场景B导出MP4
场景B(导出MP4): 确认页面/翻页接口 → export_mp4.py (ensure_ffmpeg → record_page
                → synth_bgm → ffmpeg 混流) → 验证汇报
```

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

3. 让用户浏览器打开预览；确认后可进入场景 B 导出 MP4
4. 视觉规范、文案模板、照片替换方法见 [references/design-guide.md](references/design-guide.md)

## 场景 B：HTML → 竖屏 MP4 导出（通用）

前提确认（一次一问）：页面是否有全局翻页函数 `window.go(n)`（本 skill 生成的请柬有）？
没有则确认「下一页」按钮选择器或选择不翻页模式。

```bash
python3 <skill_dir>/scripts/export_mp4.py --html 请柬.html \
  --stay "1500,5000,6000,9000,6500,5500,4500"     # 每页停留 ms, 长度=页数
# 常用可选: --out 视频.mp4 --out-size 1080x1920 --no-bgm
#           --nav-mode go|selector|none --nav-selector ".next" --start-selector "#startBtn|none"
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
| 每页停留 | 7 段默认值(共约 38s) | 打字机页建议 ≥8000ms |
| BGM | 开启 | `--no-bgm` 关闭 |
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
- 交付时汇报：产物绝对路径、时长、分辨率、大小、音轨有无、降级项（如有）

## 触发示例

- 帮我做一个动森风格的电子婚礼请柬，新郎王青新娘桃十九
- 把这个请柬 HTML 导出成竖屏视频发朋友圈
- 我们 10 月 3 号在西安温德姆办婚礼，做个 H5 邀请函还要能配音乐自动播放
- 把这个本地网页做成 1080x1920 的 MP4 演示视频

## 不适用场景

- 纸质请柬/平面设计排版（用设计工具类 skill）
- 给已有视频做剪辑、加字幕、转码（用视频处理工具）
- 咨询在线请柬平台（婚纪、易企秀等）的选型与使用 → 直接解答
- 需要真人出镜拍摄/实拍剪辑的婚礼影片
