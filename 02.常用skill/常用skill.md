# skill平台

**skill.sh**

https://agentskill.sh/



**skills.sh**

https://skills.sh/



**skillsmp**

https://skillsmp.com/



**Smithery**

https://smithery.ai/skills



**Awesome-skill集合**

https://github.com/heilcheng/awesome-agent-skills/blob/main/README.zh-CN.md#%E5%85%BC%E5%AE%B9%E7%9A%84%E4%BB%A3%E7%90%86



# find-skills-必装

按关键词搜索现成 的skill。



**安装**

```
# 建议安装到当前项目
npx skills add https://github.com/vercel-labs/skills --skill find-skills
```



**使用**

**场景1：询问做某件事**

```
你：如何优化 Next.js 应用的性能？

Claude：
我来帮你搜索相关的技能...

[自动调用 find-skills]
[搜索 "nextjs performance" 相关技能]

找到以下技能：
1. vercel-labs/agent-skills@vercel-react-best-practices (5.2K 安装)
   - Vercel 工程团队的 React/Next.js 性能优化最佳实践

安装命令：
npx skills add vercel-labs/agent-skills@vercel-react-best-practices -g -y

想要我帮你安装吗？
```

**触发场景 2：询问是否有某个技能**

```
你：有没有帮助写单元测试的技能？

Claude：
[自动调用 find-skills，搜索 "testing" 相关技能]

找到了！推荐以下技能：
1. testing-library/claude-skill - React Testing Library 集成
2. jest-automation/skill - Jest 自动化测试生成
...
```

**触发场景 3：表达需要某种功能**

```
你：我想自动生成 API 文档

Claude：
[自动调用 find-skills，搜索 "api documentation" 相关技能]

为你找到了这些 API 文档生成技能...
```

**手动搜索**

```
# 在终端执行
npx skills find react              # 搜索 React 相关
npx skills find testing            # 搜索测试相关
npx skills find "api docs"         # 多词搜索用引号
npx skills find xiaohongshu        # 搜索小红书相关
```



# 产品设计

## Product-Manager-Skills

产品经理skill。

分析需求，输出prd.

https://github.com/deanpeters/Product-Manager-Skills



**快速上手**

下载仓库到本地，内容放到本地.claude目录下。



编写prd

```
use skill:prd-development
帮我写个prd，用于实现一个软件，查询指定日期从A城市到B城市购买12306火车票最佳购票方案。
```



**完整使用**

```
假设你的问题是：“注册完成率太低，我想搞清楚问题并决定做什么。”

你可以这样一步步来：

第一步：先定义问题

claude "Using skills/problem-statement/SKILL.md, help me frame the problem of low signup completion. Ask what evidence I have first."

第二步：决定怎么验证

claude "Using skills/pol-probe/SKILL.md, design a lightweight validation experiment for the hypothesis that users abandon signup because the form feels too long."

第三步：做优先级判断

claude "Using skills/prioritization-advisor/SKILL.md, help me choose how to prioritize fixes to the signup flow."

第四步：写用户故事

claude "Using skills/user-story/SKILL.md, write user stories for reducing friction in the signup form."

第五步：如果要正式推进，再写 PRD

claude "Using skills/prd-development/SKILL.md, create a PRD for improving signup completion."

这就是这套 PM Skills 最典型的用法：
先诊断，再验证，再决策，再产出文档。
```



## product-designer

```
use skill:product-designer
帮我设计一个 SaaS 首页的用户旅程和低保真线框图

用 product-designer skill 帮我设计一个移动端登录页

用 product-designer 帮我：
1. 分析这个页面的 UX 问题
2. 重新设计信息架构
3. 给出 wireframe
4. 定义颜色、字体、间距 token


用 product-designer 帮我设计一个 AI Agent 管理后台首页
```



它适合这些场景：

- 设计用户旅程图
- 画低保真 / 高保真页面方案
- 规划产品功能体验
- 做 UI/UX 评审
- 定义设计系统、组件规范、设计 token
- 制定可用性测试方案
- 生成产品设计原则和交互规范







# 前端UI开发

## frontend-design

https://github.com/anthropics/skills/frontend-design

前端页面开发skill.



## ui-ux-pro-max-skill

**工作流程**

当你在Claude Code中提出UI需求时，技能会自动执行以下流程：

1. **需求分析**：提取产品类型、风格关键词、行业领域
2. **智能检索**：使用BM25算法从设计数据库检索相关内容
3. **方案综合**：整合样式、颜色、字体、UX指南
4. **代码生成**：生成符合最佳实践的可运行代码



**环境要求**

- ✅ Python 3.x
- ✅ Claude Code CLI已安装



**手动安装**

```
# 1. 克隆或下载GitHub仓库
git clone https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git

# 2. 复制技能文件夹到你的项目
# Windows:
xcopy /E /I .claude\skills "你的项目路径\.claude\skills\"

# macOS/Linux:
cp -r .claude/samples/ui-ux-pro-max /path/to/your/project/.claude/skills/ui-ux-pro-max

# 安装后项目目录
你的项目/
├── .claude/
│   └── skills/
│       └── ui-ux-pro-max/
│           ├── SKILL.md          # 技能定义文件
│           ├── scripts/
│           │   ├── search.py     # 搜索脚本
│           │   └── core.py       # 核心搜索引擎
│           └── data/             # 设计数据库
│               ├── styles.csv    # UI风格
│               ├── colors.csv    # 配色方案
│               ├── typography.csv # 字体搭配
│               └── ux-guidelines.csv # UX指南

```



**使用**

```
帮我创建一个现代化的登录页面
```

如果AI开始询问产品类型、风格偏好等问题，或直接生成了带有专业配色和字体的代码，说明技能已成功激活。



# skill-creator

https://github.com/anthropics/skills/skill-creator

通过对话创建skill。



# mcp-builder

https://github.com/anthropics/skills/mcp-builder

通过对话，创建mcpServer。



# playwright-不推荐

https://agentskill.sh/@openai/playwright

浏览器自动化操作。



建议：

1，针对特定网站的操作，直接使用playwright会很慢。因为playwright仅知道浏览器基本操作。

但是网站里的内容（布局，按钮）每一个操作对应什么含义，都需要AI基于playwright一步步分析。因此会很慢。



因此，特定网站使用特定网站的skill和mcp，如"小红书MCP"封装了对小红书平台的相关操作。







# 视频生成





## hyperframes

HyperFrames 是一个把 HTML 渲染成 MP4 视频的skill 集合。


官网：

https://hyperframes.video/

GitHub：

https://github.com/heygen-com/hyperframes


**愿景**
大语言模型天然地"会"写 HTML，经过数十亿网页的训练，HTML、CSS、JavaScript 已经是它们最熟悉的语言。如果我们能让 AI 用它最擅长的语言——HTML——来描述一段视频，然后把渲染的脏活交给框架去做，会更顺畅。


环境要求：

- Node.js 22+
- FFmpeg

**实际使用场景**
内容自动化生产：电商平台的商品介绍视频、新闻资讯的可视化短片、数据报告的动态呈现——这些需要大批量、模板化生产的视频，可以完全交给 AI 智能体通过 HyperFrames 自动生成。

AI Agent 工作流：与 MCP（Model Context Protocol）集成后，HyperFrames 可以成为多智能体工作流的一个节点，接收上游的文案、数据，输出渲染好的视频文件。

开发者视频工具：对于有编程背景的内容创作者，HyperFrames 提供了比传统剪辑软件更精确、更可版本控制的视频创作方式。


**设计思路**

HyperFrames 的视频本质上是一个 HTML 文档：

- 根节点用 `data-width`、`data-height`、`data-duration` 定义画布尺寸和总时长
- 元素通常用 `data-start`、`data-duration` 控制出现时间
- 写完后通过 `preview` 预览，通过 `render` 输出 MP4

所以它非常适合 AI：LLM 天然擅长生成 HTML/CSS/JS，再交给 HyperFrames 做确定性渲染。

```
<div id="stage" data-composition-id="my-video" data-start="0" data-width="1920" data-height="1080">
  <!-- 第 0 秒开始播放，持续 5 秒 -->
  <video id="clip-1" data-start="0" data-duration="5" data-track="0"
    src="intro.mp4" muted playsinline></video>
  <!-- 第 2 秒出现，叠加 3 秒 -->
  <img id="overlay" data-start="2" data-duration="3" data-track="1" src="logo.png" />
  <!-- 背景音乐，音量 50% -->
  <audio id="bg-music" data-start="0" data-duration="9" data-track="2"
    data-volume="0.5" src="music.wav"></audio>
</div>
```



**手动项目**

如果你想手动起一个项目，也可以：

```
# 初始化项目
npx hyperframes init my-video
cd my-video

# 编写html

# 验证 HTML 语法和结构
npx hyperframes lint ./my-video

# 预览
npx hyperframes preview
# 生成视频mp4
npx hyperframes render

```

**项目结构**
```
my-video/
├── index.html          # 主视频工程文件
├── components/         # 组件目录（可选）
│   ├── bar-chart.html  # 柱状图组件
│   └── title-card.html # 标题卡组件
└── output/             # 渲染输出目录
```


**安装skill**
```
npx skills add heygen-com/hyperframes
```

安装后，AI 编码助手会自动获得框架的使用规范，包括：HTML 合成结构的正确写法、data- 属性的使用规则、时间轴注册方式、渲染约束（例如禁止使用随机数，所有动画必须是确定性的）等。

这意味着，你可以直接对 Claude Code 说："帮我做一个产品发布的宣传短视频，开头是 Logo 动画，然后展示三个核心功能，最后是 Call to Action"，AI 会真正理解框架的规则，生成可以直接渲染的代码。

**使用**
```
做一个 15 秒的产品介绍视频：
16:9，黑色背景，标题 0.5 秒淡入，
中间展示 3 个卖点，结尾出现官网和 CTA。
```

```
把 https://xxx.com 首页做成一个 20 秒宣传视频，
风格偏科技感，输出 1080x1920 竖屏。
```

```
给这个视频加一个 glitch-text 开场，
再用 /hyperframes-cli 完成预览和渲染。
```


**写提示词时最好补充的信息**

- 视频时长：例如 10 秒、20 秒、45 秒
- 画幅比例：16:9、9:16、1:1
- 场景结构：开场、主体、结尾分别做什么
- 视觉风格：科技感、极简、电影感、商务、赛博等
- 文字内容：标题、副标题、卖点、CTA
- 素材来源：图片、视频、Logo、配音、BGM 是否已提供
- 是否需要字幕、转场、配音、音频驱动效果

**视觉设计**
HyperFrames 不只是一个渲染引擎，它还内置了一套完整的视觉设计体系。

框架提供了 8 种命名视觉风格预设，包括：

- Swiss Pulse——瑞士风格，简洁几何
- Velvet Standard——奢华质感
- Data Drift——数据可视化风格
- Shadow Cut——高对比度暗黑风格
每种风格都包含颜色方案（精确到 hex 值）、字体搭配建议、GSAP 缓动签名，以及禁止使用的反模式清单。

这意味着，当你让 AI 生成一个"瑞士风格"的产品介绍视频时，它不需要从零发明审
美，而是直接调用框架预定义的设计规范。


**相关说明**

1，HyperFrames 的一个核心优势是“确定性渲染”：同样的 HTML 和参数，在不同机器、不同时间渲染，理论上可以得到一致输出。不要依赖 `Date.now()`、`setTimeout()` 这类真实时间驱动逻辑。这对 AI 自动改稿、CI 批量渲染、结果回归验证很有价值。

2，官方比较推荐 AI 先 `lint --json` / `inspect --json`，确认结构没问题后再 `render`。因为渲染最耗时，先静态检查更省成本。

3，如果你不想从零写效果，优先使用 `hyperframes add <block-name>` 引入官方现成 block，会比“让 AI 自己凭空发明一个特效”更稳定。



## Remotion

**原理**

用 React 代码来写视频。

- 网页渲染： 你写的 React 代码在浏览器里跑起来，展示出精美的动画。
- 截屏： Remotion 调动一个后台浏览器（比如 Puppeteer），以每秒 30 帧或 60 帧的速度，像“连拍”一样把这些画面全截下来。
- 合成： 最后利用强大的 FFmpeg 工具，把几千张截屏合成一个流畅的视频。



**安装**

```
 npx skills add remotion-dev/skills@remotion-best-practices
```



**使用**

```
use skill:remotion-best-practices
帮我创建一个 10 秒的 Remotion 产品介绍视频模板

use skill:remotion-best-practices
帮我用 Remotion 做一个 1920x1080、30fps、15 秒的品牌宣传视频，包含标题动画、三段卖点和结尾 CTA

use skill:remotion-best-practices
帮我把这个 React 组件改成适合 Remotion 渲染的视频组件

use skill:remotion-best-practices
帮我设计一个短视频模板，支持传入标题、字幕、图片和背景色

use skill:remotion-best-practices
在当前目录创建一个 Remotion 视频项目，做一个 10 秒登录页展示视频
```



# PPT制作

## Open-Slide-推荐

**安装**

```
https://open-slide.dev/
帮我安装上面这个平台对应的插件。
```

这个插件默认为项目级安装,如果需要需要保证当前项目安装过这个插件.



**生成大纲**

```
请基于 NVIDIA 最新官方财报资料，做一份 20 页以内的商业汇报 PPT。

资料来源优先级：
1. NVIDIA Q1 FY2027 财报新闻稿
2. NVIDIA FY2026 Annual Report
3. NVIDIA Q4 FY2026 Quarterly Presentation

任务：
先阅读资料，提炼 NVIDIA 最新业绩、增长驱动、业务结构、数据中心业务、毛利率、现金流和未来风险。

先不要生成 PPT，先给我一版 PPT 大纲：
每页包括：页标题、核心观点、建议图表、需要引用的数据来源。

要求：
1. 控制在 15-20 页。
2. 每页只讲一个核心观点。
3. 尽量多用图表，不要堆文字。
4. 风格：专业、科技感、适合商业汇报。
5. 所有数据必须来自官方资料，不要编造。
```

以上prompt的任务执行完毕后,会输出一个ppt结构化文档.

预览该文档,进行适当调整.



**生成在线PPT**

可以让AI直接基于输出的文档生成PPT,但是我个人更推荐让AI提供下OpenSlide的模板,选择对应模板后再生成ppt.

```
行 我们先不着急生成ppt，先给我一个openslide提供的风格模版的playground，我挑选一下适合的
```



**修改PPT**

AI生成完成PPT后,可以访问插件服务:http://127.0.0.1:5173

选择喜欢的模板(如果没有喜欢的让AI重新生成),进行在线修改.





## html-slides

html-slides 是一个用来生成 HTML 幻灯片 的技能。



**安装**

```
npx skills add claude-office-skills/skills@html-slides
```



**使用**

```
“做一个关于 AI Agent 的 10 页中文演示，风格简洁，黑色主题”
“生成一个前端性能优化分享，带代码高亮和 speaker notes”
“做一个产品发布会风格的 slides，带动画和数据页”
做一个 8 页中文 AI 介绍 slides，科技感深色主题。
```



你最好补充这几类信息，这样生成效果更准：

  - 主题内容：讲什么
  - 页数/结构：几页，是否要目录、总结、Q&A
  - 视觉风格：商务、科技感、极简、深色/浅色
  - 功能需求：代码高亮、备注、自动播放、渐进动画、背景图/视频
  - 语言：中文或英文

  常见可配项包括：

  - 主题：black、white、night、moon、solarized
  - 切换：slide、fade、zoom
  - 动画：fragment 分步显示
  - 备注：按 S 打开 speaker notes

  如果你愿意，我现在就可以直接帮你生成一份。













