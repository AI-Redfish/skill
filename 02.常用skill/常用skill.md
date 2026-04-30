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



# html-slides

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











