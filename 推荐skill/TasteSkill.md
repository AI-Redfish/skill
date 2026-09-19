# Taste Skill：去"AI 味"设计技能包

> 来源：[runoob Taste Skill](https://www.runoob.com/skills/taste-skill.html)
> GitHub：https://github.com/Leonxlnx/taste-skill（MIT）

## 一、解决什么问题："AI 味"界面

AI 生成界面的通病：大标题居中 + 副标题 + CTA 按钮，蓝白或深灰配色，卡片四等分，间距均匀——功能没问题，但一眼就是模板。

**根源**：AI 从训练数据提取模式，学到的是"怎么写不出错的界面"，而不是"怎么写出有设计感的界面"。每个决定都是最保险的那个。这个问题靠提示词（"高级感""设计感"）很难根本解决。

## 二、解决思路

把**布局变化、排版层次、动效规则、间距逻辑**这些具体设计决策写成 SKILL.md，让 AI 生成界面前先加载规则，按规则决策而非按训练数据最常见的模式。相当于给 AI 配一套设计偏好。

## 三、安装

```bash
# 安装全部技能包
npx skills add https://github.com/Leonxlnx/taste-skill

# 只安装默认主技能（推荐先装这个）
npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"
```

装好后照常描述需求即可，无需改提示词。

## 四、技能包分类

### 界面生成类（最常用）

| 技能包 | 风格特征 | 适用场景 |
|---|---|---|
| design-taste-frontend（默认，v2） | 自动推断设计语言，按布局变化/动效深度/信息密度三维度生成 | 大部分项目 |
| high-end-visual-design | 克制对比度、大量留白、高级字体、弹性动效 | 品牌感强的落地页、营销页 |
| minimalist-ui | 节制配色、清晰结构，接近 Notion/Linear 风格 | 内部工具、管理后台 |
| industrial-brutalist-ui | 瑞士字体、高对比度、硬朗版式、非常规布局 | 创意类项目 |

### 流程辅助类

| 技能包 | 解决的问题 |
|---|---|
| redesign-existing-projects | 改造现有项目：先审计再修改，而不是盲目改 |
| full-output-enforcement | AI 生成到一半停下、留 `// TODO` 的问题；强制输出完整代码 |

### 图片生成类（配合 ChatGPT Images 等出参考图）

imagegen-frontend-web（网页设计稿）、imagegen-frontend-mobile（移动端）、brandkit（品牌视觉板）。

## 五、三个可调参数（编辑 SKILL.md）

| 参数 | 控制什么 | 低值（1-3） | 高值（7-10） | 建议 |
|---|---|---|---|---|
| DESIGN_VARIANCE | 布局变化幅度 | 居中对称、规整 | 不对称、现代感 | 落地页调高，表单页低 |
| MOTION_INTENSITY | 动效深度 | 仅 hover | 滚动/磁性动效 | 动感强的页面往上推 |
| VISUAL_DENSITY | 信息密度 | 大留白 | 密集信息展示 | 内容页调低，数据后台调高 |

## 六、使用前须知

- **v2 还在迭代中**，需要稳定结果时安装 v1：`--skill "design-taste-frontend-v1"`
- 只影响**设计决策**，不解决代码 bug
- 效果依赖 AI 工具对 SKILL.md 的理解（Claude Code/Cursor 较忠实；ChatGPT 可直接贴 SKILL.md 到对话）
- **框架无关**：React、Vue、Svelte 均可用

## 七、快速上手建议

先装默认主技能，让 AI 重新生成一个你以前做过的页面，对比差别。改造现有项目用 redesign-existing-projects，先分析再动手，比"帮我改好看点"可控得多。

---

⬆️ [返回总索引](../../README.md)
