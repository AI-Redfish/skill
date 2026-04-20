# skill平台

**skill.sh**

https://agentskill.sh/



**Smithery**

https://smithery.ai/skills



**Awesome-skill集合**

https://github.com/heilcheng/awesome-agent-skills/blob/main/README.zh-CN.md#%E5%85%BC%E5%AE%B9%E7%9A%84%E4%BB%A3%E7%90%86





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
xcopy /E /I .claude\samples\ui-ux-pro-max "你的项目路径\.claude\skills\ui-ux-pro-max\"

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



# find-skills

按关键词搜索现成 的skill。



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





# Product-Manager-Skills

产品经理skill。

分析需求，输出prd.

https://github.com/deanpeters/Product-Manager-Skills



























