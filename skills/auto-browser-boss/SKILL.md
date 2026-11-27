---
name: auto-browser-boss
description: Boss直聘求职者端自动化，手动触发单次执行两个任务：①自动投简历——按 .env 筛选条件遍历搜索结果逐个点「立即沟通」，达到当日上限停止，支持两种模式：纯视觉模式（mss 截屏 + OS 级鼠标仿真，零 CDP/零连接，风控期可用，推荐）与 CDP 接管模式（风控降级后可用）；②自动回复消息——读取聊天页未读会话，按 FAQ 关键词匹配自动回复，答不了的记录并上报。当用户说「帮我投简历」「Boss直聘自动投递」「自动回复 Boss 消息」「看看哪些 HR 没回」时使用。WHEN NOT：招聘端（Boss 端）发职位；定时轮询与监听（skill 只单次执行，定时由用户自建）；iPhone、其他招聘平台（猎聘/拉勾等）。
compatibility: Windows + 本机 Chrome + uv（PEP 723 自动装依赖）；视觉模式另需 mss/opencv/pyautogui（自动装）且单显示器主屏运行；CDP 模式需专用 Chrome profile 已保存 Boss 登录态
metadata:
  author: agent
  version: "1.2.0"
---

# auto-browser-boss — Boss直聘求职者自动投递与自动回复

求职者身份（牛人端）。每次触发执行：投递一遍 + 回复一遍。两个最高优先级约束：**聊天页只能用户手动打开**（脚本 goto 聊天页会被风控拦截）；**达到当日投递上限必须停止**（默认 50/天）。

## 双闭环流程（最高优先级，优先于其他默认行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环
1. 回答前先提问，**每次只问一个问题**，根据回答继续追问
2. 提问围绕：真实目标、背景、使用场景、输出对象、关键约束、优先级、成功标准、禁止事项、已有信息、可接受偏差
3. 对「用户真正想要什么」有 95% 信心才停止提问；未达 95% 只提问澄清，不给最终方案（用户消息已足以达到 95% 信心时可直接执行，但最终输出必须列出关键假设）

### 第二闭环：输出审查闭环
1. 形成答案后不直接输出，先自查：是否真正解决目标？是否遗漏关键约束？是否存在事实错误、逻辑漏洞、歧义、不可执行之处？
2. 发现问题→自行修正→再次审查，重复「审查—修正—再审查」，直到对输出结果至少有 95% 的准确性信心

### 最终输出要求
1. 先一句话复述用户真实需求
2. 再给出最终方案：明确、可执行、可直接使用
3. 说明关键假设、剩余不确定性，以及为什么已达到 95% 信心；不确定处明确标注，不假装确定

## 路径与输出位置约定

| 内容 | 位置 | 生命周期 |
|---|---|---|
| 筛选条件/配置 | 运行时工作目录 `.agents/.env`（键：`BOSS_QUERY`、`BOSS_CITY_CODE`、`BOSS_SALARY`、`BOSS_EXPERIENCE`、`BOSS_DEGREE`、`BOSS_DAILY_LIMIT`、`BOSS_DELAY_MIN`、`BOSS_DELAY_MAX`、`BOSS_GREETING`、`BOSS_CDP_PORT`） | 首次触发交互式写入，之后复用 |
| ↑ 多城市多岗位 | `BOSS_QUERY` 与 `BOSS_CITY_CODE` 支持逗号分隔多值（如 `实施工程师,JAVA开发` / `101110100,101210100,101200100`），脚本按组合循环；**推荐用法**：AI 依次用 `--query X --city Y` 单组合触发，每组合一次调用、间隔自然拉长，避免连续导航触发风控 | 用户指定目标时更新写入 |
| ↑ 薪资/经验/学历编码值 | `BOSS_SALARY`/`BOSS_EXPERIENCE`/`BOSS_DEGREE` 为 Boss 筛选编码值（如 `salary=13Z20`），可选；取值方法：用户在 Chrome 搜索页点选筛选后，从地址栏 URL 抄取对应 query 值 | 用户提供时写入，缺省不过滤 |
| FAQ 知识库（**git 托管**） | `<工作空间>/.agents/data/auto-browser-boss/faq.md`（每条目两行：`关键词: a\|b` / `回复: 文案`；# 开头行忽略） | 首次触发时 AI 与用户共建；用户可直接改文件，下次触发生效 |
| 投递记录 | `.agents/out/YYYYMMDD/auto-browser-boss/apply-YYYYMMDD.jsonl` | 每日累积，用于当日上限判断与投递沉淀 |
| 未匹配消息 | `.agents/out/YYYYMMDD/auto-browser-boss/unmatched-YYYYMMDD.jsonl` | 每日累积，触发结束时上报 |
| Chrome profile | `.agents/out/auto-browser-boss/chrome-profile` | 持久登录态（不在日期目录，不参与清理） |

- **产物 git 托管指定**：FAQ 知识库**需要被 git 管理**，落在 `.agents/data/auto-browser-boss/faq.md`（可版本化、可追溯）；其余产物（投递记录、未匹配消息、Chrome profile、`.agents/.env` 筛选配置）**不需要被 git 管理**：投递/未匹配记录输出到 `<工作空间>/.agents/out/YYYYMMDD/auto-browser-boss/`（YYYYMMDD 为当天日期；非 git 托管产物目录，由 .gitignore 忽略）；Chrome profile 与 `.agents/.env` 为持久数据，不在日期目录。用户明确指定目录时以用户为准。
- **out 产物清理**：今日首次执行任务时检查一次 `.agents/out/` 日期目录；目录日期距今天超过 15 天提示用户可删除，用户确认后删除，AI 不自行删除；只清理日期目录，chrome-profile 等持久数据不清理。
- 脚本以运行时 cwd 为工作空间根解析路径；cwd 无 `.agents/` 时以 skill 目录所在工作空间为根。

## 用法

```bash
export PYTHONUTF8=1

# === 视觉模式（无痕，推荐；日常 Chrome 即可，不碰 CDP）===
# 首次校准（框选列表布局与按钮模板，换分辨率后需重跑）
uv run .agents/skills/auto-browser-boss/scripts/boss_apply_visual.py --calibrate
# 只定位不点击验证
uv run .agents/skills/auto-browser-boss/scripts/boss_apply_visual.py --dry-run --limit 3
# 正式投递当前屏可见卡片（额度与接管模式共享，自动接续）
uv run .agents/skills/auto-browser-boss/scripts/boss_apply_visual.py --label "杭州·实施"

# === CDP 接管模式（仅风控降级后可用，见风控须知）===
# 投递（达到当日上限自动停止）
uv run .agents/skills/auto-browser-boss/scripts/boss_apply.py
uv run .agents/skills/auto-browser-boss/scripts/boss_apply.py --dry-run --limit 3

# 回复（先让用户在 Chrome 手动打开聊天页 /web/geek/chat）
uv run .agents/skills/auto-browser-boss/scripts/boss_reply.py
uv run .agents/skills/auto-browser-boss/scripts/boss_reply.py --dry-run
```

## 视觉模式（无痕，风控期首选）

原理：mss 截屏 + OpenCV 模板匹配定位（零浏览器连接，页面无任何可探测 API），pyautogui OS 级鼠标仿真点击（isTrusted=true，与真手不可区分）。风控视角等同真人操作。

- **何时用**：L3 风控激活期、任何 CDP 受限期、日常 Chrome 投递。与 CDP 接管模式二选一。
- **首次使用**：先跑 `--calibrate`，按提示框选 4 样东西：①第一张卡片 ②第二张卡片 ③「立即沟通」按钮 ④弹窗「发送」按钮（后两步产物存 `assets/templates/`，git 托管；「继续沟通」模板可选）。分辨率/DPI 变更后必须重校准。
- **节奏（均衡档）**：卡间停顿 2.5~6s，每 8~12 张随机插入 8~15s 长停顿（模拟被打断），单卡约 7s，100 份约 20~30 分钟。
- **安全阀（脚本内置）**：连续 2 张定位失败即停；点击后页面无变化连续 2 次即停；`today_count("apply")` 与接管模式共享当日额度（BOSS_DAILY_LIMIT）；鼠标甩屏幕左上角或 Ctrl+C 紧急中断。
- **流程**：用户在 Chrome 打开目标组合搜索页 → 跑脚本投当前屏 → 用户翻页/换组合 → 再跑（`--label` 标组合，写入 jsonl）。MVP 单屏一轮，不自动滚动翻页。
- **限制**：单显示器主屏；运行期间占用鼠标；无 OCR 不记职位名（jsonl 记组合标签+序号）；列表页卡片需白底（行检测依赖白色占比，失效时调 layout.json 的 row_white_frac）；hover 快捷按钮不存在时自动 fallback 走「点卡片→详情面板」链路。

## 执行流程（AI 触发 skill 时）

1. 首次触发且 `.agents/.env` 缺 `BOSS_QUERY` 时，进入理解闭环一次一问，收集关键词、城市代码、每日上限，写入 `.env`；同时引导用户共建 `faq.md`（薪资/到岗/学历等高频问答）。
2. **投递模式选择**：默认视觉模式（无痕，不碰 CDP）；仅当视觉模式校准失败且风控已确认降级（冷却试水通过）时才用 CDP 接管模式。检查 CDP 存活（`curl http://127.0.0.1:9222/json/version`）仅接管模式需要。
3. 视觉模式投递：首次先引导 `--calibrate` 校准，再 `--dry-run --limit 3` 验证定位，通过后正式跑。请用户在日常 Chrome 打开目标组合搜索页并保持前台，跑 `boss_apply_visual.py --label "城市·岗位"`；投完当前屏请用户翻页/换组合，说「继续」再跑。
4. 请用户手动在 Chrome 打开聊天页 `https://www.zhipin.com/web/geek/chat` 并保持打开。
5. 回复：`uv run scripts/boss_reply.py`；按输出摘要与 unmatched 清单向用户报告。

### 风控须知（实测事实，必须遵守）

- **脚本导航已被风控拦截（升级后）**：goto 任何 zhipin 页（含搜索页）都会被立即跳回空白页或直接拒连（ERR_CONNECTION_CLOSED）；同 IP curl 正常可证是环境级标记，仅限脚本导航，人工操作不受影响。**接管模式是唯一可行方式**：用户手动开页，脚本只读/点击，永不 goto。
- **连续 goto 切换搜索页会触发升级**：曾从「页面弹回」升级到「连接拒绝」，冷却后降回。组合切换必须由用户手动导航，多次触发自然拉开间隔。
- **风控等级 L3（2026-11-17 实测）**：CDP 连接后约 5 秒内，手动打开的搜索页被 JS 强制重定向到城市首页 `/xian/?seoRefer=index`，接管模式失效；连接瞬间（t+0）卡片可读。**结论与禁令**：此重定向由页面 JS（location.replace）发起，请求层 route 拦截已实测无效（文档仍被销毁），location 对象不可 hook——**禁止对抗**（hook/route/init script 均无效且会加深风控印象），直接转手动模式。
- **恢复节奏**：冷却 2~3 天不连 CDP → 单次只读试水（连接后立即读卡片数，不点击；页面存活>30 秒 → 风控降级）→ 恢复接管模式 → 稳定数日再考虑恢复脚本导航。试水用临时探针，不新增 skill 文件。
- 页面 URL 含 `ka=bticket` → 要求人工重新验证，脚本停止并提示。
- 聊天页可能被整页踢回 `/web/geek/jobs`（风控标记状态）→ 脚本检测到即停，当天不再重试。
- Boss 反自动化 JS 调 `window.close()`：唯一标签被关 = Chrome 整体退出。脚本已内置占位标签 + init script 屏蔽（拦不住 location 跳转）。
- 动作间随机延时由 `BOSS_DELAY_MIN/MAX` 控制（默认 3~8 秒，当前 2~5）；上限默认 50/天（低于 Boss 官方 100，降低风控概率）。风控降级后建议将延时回拨到 3~8 以上。
- **手动模式（风控激活期唯一安全策略）**：AI 不连接 CDP、不运行任何 Playwright 脚本；向用户输出组合清单与搜索 URL，用户在**日常 Chrome**（非调试 profile）手动打开并点击投递。已投与否 Boss 页面自标「已沟通」，重复点击无副作用，无需维护记录。手动投递数不入 jsonl，下次接管时以页面按钮状态为准跳过已投。

### 输出格式（执行报告模板，AI 触发后按此汇报）

```
今日投递：N / 上限 M（新增 K）
已回复：R 条
未回复（答不了）：列出 HR 名 + 公司 + 消息摘要（来自 unmatched-YYYYMMDD.jsonl）
异常：bticket 验证 / 页面被踢 / 选择器失效（有则列出）
```

### 防幻觉约定

页面结构以 `references/selectors.md` 与脚本实际输出为准；选择器未验证的部分（聊天气泡/输入框精确结构）标注「未验证」。不确定就明确说明，不编造职位数据或风控行为。

## 输出精简约束（所有落盘产物与答复通用）

1. **只落盘有用的**：只把用户会直接使用的产物写到磁盘；过程稿、中间草稿、重复副本、无人引用的说明文件一律不落盘。
2. **中间产物隔离**：确需保留的中间产物收进 `.agents/out/YYYYMMDD/auto-browser-boss/` 子目录（非 git 托管产物目录），不与交付产物混放；交付目录顶层只出现用户要的文件。
3. **落盘前自问**：写文件前先问「用户会直接使用它吗」；不会就不写，改为文字说明。
4. **答复同理**：汇报只讲结论、路径、风险与待办，不复述中间过程与脚本日志。
5. **本 skill 针对性约束**：交付物只有投递/回复执行报告与 `.agents/out/YYYYMMDD/auto-browser-boss/` 下的运行数据；探索脚本、临时 dump 一律不落盘（放系统临时目录并说明清理方式）。

## 自我沉淀闭环（每次对话结束必检，最高优先级）

1. **回顾识别**：每次对话结束前，回顾本次对话是否出现值得沉淀的信号——新踩的坑与有效解法、被用户纠正的默认值/流程/输出习惯、选择器失效与修复、可复用的 FAQ 条目与脚本能力缺口
2. **有沉淀候选 → 主动询问用户**（一次只问一个）：「本次对话发现 X，是否沉淀进本 skill（修改 SKILL.md / references/ / scripts/）？」
3. **用户确认后**：遵循本 skill 自身产出规范小步修改对应文件（不重写整个 skill），并递增 frontmatter 的 `metadata.version`；用户拒绝则不强改
4. **无沉淀候选 → 不打扰用户**，正常结束
5. **判定标准**：只沉淀未来场景会复用的通用规律（如新选择器、新风控行为），一次性细节不沉淀

## 触发示例

- 「用 Boss直聘 自动投简历，投到今天的上限为止」→ 跑 boss_apply.py
- 「看看 Boss 上哪些 HR 回了，能答的自动回复」→ 确认聊天页已手动打开，跑 boss_reply.py
- 「先把投递条件改成本科就行、15-20K」→ 更新 `.env` 后跑投递
- 「这个 HR 问我到岗时间，我该怎么设置自动回复」→ 补充 faq.md 条目，不直接替用户发消息

## 不适用场景与限制

- 聊天气泡与输入框的精确 DOM 未完全验证（探索期间聊天页被风控踢出）；boss_reply.py 的发送段采用宽松匹配（contenteditable + 「发送」文本按钮），首次真实运行需校准并回填 selectors.md。
- Boss 页面为 Vue 动态渲染，`data-v-*` scoped 属性随版本变化；选择器失效时优先更新 selectors.md 与脚本 SEL 常量区。视觉模式不依赖 DOM，只依赖按钮外观（模板失配时重跑 --calibrate）。
- 视觉模式：多显示器、分辨率/DPI 变更需重校准；模板含 Boss 按钮截图，随 Boss 改版可能失效；MVP 不自动滚动翻页；无 OCR 不记录职位名。
- 面试邀约、简历附件发送、退群/拉黑处理不在本 skill 范围。
