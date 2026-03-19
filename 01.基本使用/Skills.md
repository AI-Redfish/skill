



# 什么是Skills

Skill封装了指令、脚本及相关资源，用于为智能体提供可复用、面向特定场景的专业能力。

一个Skill可以被视为提供给智能体的一套 “专业能力说明书”（类似用户手册或操作指南）。

在执行任务时，智能体可以按需加载相应的技能，从而增强其对任务的理解与执行能力。



# 通过openskills使用skills

通过openskills，可以安装和使用Anthropic 官方的Skills。



## **前置条件**

需要node20+以上的版本，再运行下面的指令。

```
# 安装openskills
npm i -g openskills

# 验证安装是否成功
openskills --version
```



## 安装skills



**安装官方skills**

```
# 项目级安装
openskills install anthropics/skills

# 全局安装
openskills install anthropics/skills --global
```

当运行指令后，OpenSkills 就会将 Anthropic 官方 Skills 项目给克隆下来。默认全选，你也可以通过 Space 键自主选择自己想要安装的 Skills。



安装成功后，你就会在Cursor文件管理区看到 .claude/skills文件夹。



**安装非官方skills(可选)**

即任意 GitHub 仓库安装。

```
openskills install your-org/custom-skills
# 案例：
openskills install nextlevelbuilder/ui-ux-pro-max-skill
```



**本地安装**

openskills 同样支持本地路径安装 Skill（先讲Skill离线包下载下来解压到 .claude/skills）

然后执行：

```
openskills sync
```



## 创建AGENT.md

运行下面指令将会在项目根目录创建一个 AGENTS.md 文件

```
openskills sync
```

确认后按回车键，会将你选择的 Skills 写进 AGENTS.md 文档中。它将作为 Cursor接下来使用 Skills 的指导文件。





# 创建Skils-AI方式

<img src="SkillsResource\image-20260226115132264.png" alt="image-20260226115132264" style="zoom:50%;" />







# 调用skills

**隐式调用**‌

直接在聊天框中用自然语言描述任务，例如：“帮我设计一个登录页面的 UI”，Cursor 会自动匹配并调用 `frontend-design` 技能。

‌

**显式调用**‌

方式1(部分ide环境)：在聊天框中输入 `/`，会列出可用的技能命令，选择对应的技能即可触发。

方式2：请使用 “XXX” skill，帮我XXX。





# 对比MCP

如果确定的相同的功能skill和mcp都可以实现，则优先使用MCP。

MCP 反应更快，如果你的需求是调用某个具体工具或服务，优先用 MCP。Skill 更适合需要引导 Claude 执行复杂、多步骤工作流的场

景。











