# skill平台

**skill.sh**

https://agentskill.sh/



**Smithery**

https://smithery.ai/skills



**Awesome-skill集合**

https://github.com/heilcheng/awesome-agent-skills/blob/main/README.zh-CN.md#%E5%85%BC%E5%AE%B9%E7%9A%84%E4%BB%A3%E7%90%86





# frontend-design

https://github.com/anthropics/skills/frontend-design

前端页面开发skill.

、

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





















