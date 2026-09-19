# Skill 学习笔记总索引

> 整理自：[runoob Skills 教程](https://www.runoob.com/skills/skills-tutorial.html)（39 篇全量笔记）+ 原有笔记整合
> 笔记位于 `doc/` 目录；`skills/` 为自定义 skill 目录，不参与本笔记体系。

## 📚 目录导航

### [01.基础概念](doc/01.基础概念/) — 是什么、怎么运作
| 笔记 | 内容 |
|---|---|
| [Skills简介](doc/01.基础概念/01.Skills简介.md) | 什么是 Skills、智能体三能力、解决什么问题、**Skills vs MCP**、调用方式 |
| [工作原理与触发机制](doc/01.基础概念/02.工作原理与触发机制.md) | 渐进式披露三阶段、触发判断、description 触发策略、冲突处理 |

### [02.安装与使用](doc/02.安装与使用/) — 快速上手
| 笔记 | 内容 |
|---|---|
| [安装与使用现有Skills](doc/02.安装与使用/01.安装与使用现有Skills.md) | 官方市场、openskills、npx skills、各工具 Skill 目录、资源链接 |
| [第一个Skill](doc/02.安装与使用/02.第一个Skill.md) | Claude Code 实战：创建目录 → 编写 SKILL.md → 测试 |
| [VSCode中使用Skills](doc/02.安装与使用/03.VSCode中使用Skills.md) | VS Code + Copilot 掷骰子示例、发现/激活/执行过程、问题排查 |

### [03.编写Skill](doc/03.编写Skill/) — 核心编写知识
| 笔记 | 内容 |
|---|---|
| [Skill基本结构](doc/03.编写Skill/01.Skill基本结构.md) | 文件夹 + SKILL.md、frontmatter 字段、命名规范 |
| [Skill目录结构](doc/03.编写Skill/02.Skill目录结构.md) | scripts/examples/resources/tests 各目录职责、metadata.json |
| [SKILL.md文件详解](doc/03.编写Skill/03.SKILL.md文件详解.md) | 全部元数据字段详解、指令区域写法、500行/5000token 限制 |
| [描述编写与触发优化](doc/03.编写Skill/04.描述编写与触发优化.md) | description 四要素、长度控制、常见问题修正、run_loop 自动优化 |
| [参数传递与输入输出](doc/03.编写Skill/05.参数传递与输入输出.md) | 隐式参数传递、输入四要素、输出三维度、JSON 约定 |
| [脚本扩展](doc/03.编写Skill/06.脚本扩展.md) | 一次性命令（uvx/npx/go run）、PEP 723 自包含脚本、Agent 友好脚本设计 |
| [多步骤与上下文管理](doc/03.编写Skill/07.多步骤与上下文管理.md) | 步骤设计原则、依赖检查、状态存储、参数优先级、上下文优化 |
| [错误处理与容错](doc/03.编写Skill/08.错误处理与容错.md) | 三层次错误处理、异常体系、依赖自动安装、错误信息三要素 |
| [skill-creator](doc/03.编写Skill/09.skill-creator.md) | 用 Skill 创建 Skill 的元技能、需求询问流程、开发循环 |

### [04.工程化](doc/04.工程化/) — 生产级质量
| 笔记 | 内容 |
|---|---|
| [工具链集成](doc/04.工程化/01.工具链集成.md) | subprocess 封装、工具可用性检查、pandoc 转 PDF 完整示例 |
| [外部API集成](doc/04.工程化/02.外部API集成.md) | requests 封装、密钥管理、限速处理、结果缓存 |
| [依赖管理](doc/04.工程化/03.依赖管理.md) | requirements.txt、自动安装、版本冲突策略 |
| [版本管理](doc/04.工程化/04.版本管理.md) | 语义化版本、Git 提交规范、CHANGELOG、迁移指南、回退 |
| [单元测试](doc/04.工程化/05.单元测试.md) | pytest 脚本测试、触发端到端测试、覆盖范围 |
| [调试与日志](doc/04.工程化/06.调试与日志.md) | 三类问题排查、print/logging/JSON 日志、耗时追踪、速查表 |
| [权限与安全](doc/04.工程化/07.权限与安全.md) | 最小权限、路径穿越防护、密钥存储、命令注入防护 |
| [性能优化](doc/04.工程化/08.性能优化.md) | 分块读取、文件指纹缓存、并行处理、核查清单 |
| [异步与并发](doc/04.工程化/09.异步与并发.md) | asyncio/aiohttp 并发请求、超时控制、何时用异步 |
| [监控与可观测性](doc/04.工程化/10.监控与可观测性.md) | 日志/指标/Trace 三维度、结构化日志、执行追踪 |
| [组合与编排](doc/04.工程化/11.组合与编排.md) | 顺序/并行编排、编排脚本、避免循环依赖 |
| [设计模式](doc/04.工程化/12.设计模式.md) | 单一职责、防御性检查、渐进式输出、幂等、Fail Fast 等 7 大模式 |

### [05.发布与生态](doc/05.发布与生态/)
| 笔记 | 内容 |
|---|---|
| [发布与生态搭建](doc/05.发布与生态/01.发布与生态搭建.md) | 发布检查清单、.skill 打包、分发渠道、GitHub Releases、统一仓库、CI 自动打包、Skill 注册表、团队分发清单 |

### [06.方法论](doc/06.方法论/) — 设计思想（原有笔记，已保留）
| 笔记 | 内容 |
|---|---|
| [skill方法论](doc/06.方法论/skill方法论.md) | Skill 定义四问、设计六原则、标准结构七要素、海量 Skill 分层加载（L1/L2/L3）、常见失败原因、模板、检查清单 |

### [07.自进化设计](doc/07.自进化设计/) （原有笔记，已保留）
| 笔记 | 内容 |
|---|---|
| [自进化设计](doc/07.自进化设计/自进化设计.md) | skill 自进化演进、四种落地方式（执行反馈/轨迹蒸馏/压缩增强/强化学习）、企业级五阶段路线 |

### [08.常用skill](doc/08.常用skill/) — 生态与推荐
| 笔记 | 内容 |
|---|---|
| [Skill平台与检索](doc/08.常用skill/01.Skill平台与检索.md) | 五大 skill 平台、find-skills 搜索（三种触发场景+手动搜索） |
| [产品设计类](doc/08.常用skill/02.产品设计类.md) | Product-Manager-Skills（PM 五步法）、product-designer |
| [前端UI开发类](doc/08.常用skill/03.前端UI开发类.md) | frontend-design、ui-ux-pro-max-skill（BM25 设计库检索） |
| [官方与工具类](doc/08.常用skill/04.官方与工具类.md) | skill-creator、mcp-builder、playwright（不推荐原因） |
| [PPT制作类](doc/08.常用skill/05.PPT制作类.md) | Open-Slide（大纲→模板→生成）、html-slides、frontend-slides |
| [视频生成类](doc/08.常用skill/06.视频生成类.md) | HyperFrames（HTML→MP4）、Remotion（React 写视频） |
| [Superpowers](doc/08.常用skill/Superpowers.md) | 开发流程技能包：需求梳理→规划→TDD→交付，四阶段工作流 |
| [TasteSkill](doc/08.常用skill/TasteSkill.md) | 去"AI 味"设计技能包：三参数调风格、四类界面风格技能包 |

### [09.实战项目](doc/09.实战项目/) — 综合演练
| 笔记 | 内容 |
|---|---|
| [代码审查Skill](doc/09.实战项目/01.代码审查Skill.md) | 工具链集成 + 结构化报告（flake8/radon、A-F 评级） |
| [数据清洗分析Skill](doc/09.实战项目/02.数据清洗分析Skill.md) | pandas 流水线、IQR 异常检测、交互式确认流程 |
| [多Skill协作工作流](doc/09.实战项目/03.多Skill协作工作流.md) | 编排 Skill 设计原则、orchestrator 脚本、失败处理 |

## 🗂 学习路径建议

```
入门：01.基础概念 → 02.安装与使用（跑通第一个 Skill）
进阶：03.编写Skill（核心）→ 06.方法论（设计思想）
生产：04.工程化 → 05.发布与生态
扩展：07.自进化设计 → 08.常用skill → 09.实战项目
```

## 快速速查

- **Skill 最小结构**：文件夹 + SKILL.md（name + description 必填）
- **触发唯一依据**：description（正文不参与触发判断）
- **SKILL.md 建议**：≤500 行 / ≤5000 tokens，详细资料移到单独文件
- **Skills vs MCP**：功能相同优先 MCP；复杂多步工作流用 Skill

## ✅ Skill 质量检查清单（写完必查）

> 汇总自 [skill方法论](doc/06.方法论/skill方法论.md)、[设计模式](doc/04.工程化/12.设计模式.md)、[发布与生态搭建](doc/05.发布与生态/01.发布与生态搭建.md)

### 设计阶段

- [ ] 只解决一类问题，边界清晰（单一职责）
- [ ] name 能一眼看出用途，kebab-case，与目录名一致
- [ ] description 同时包含"做什么 + 什么时候用"，含触发关键词
- [ ] 写清适用场景与**不适用场景**（避免误触发/冲突）
- [ ] 输入要求明确：必填/可选/缺省行为，缺关键信息先追问
- [ ] 输出格式稳定（固定模板/章节结构）

### 实现阶段

- [ ] 执行步骤有序，每步是一个明确动作
- [ ] 有示例（贴近真实用户说法，Few-shot）
- [ ] 脚本自包含、无交互式提示、错误信息三要素（问题+原因+行动）
- [ ] 结构化 JSON 输出（status/data/error）
- [ ] 幂等：同输入同输出；破坏性操作要 --confirm
- [ ] Fail Fast：无法继续时立即停止并报告

### 发布阶段

- [ ] 触发测试通过率 ≥ 85%（含负向用例：不应触发的场景不触发）
- [ ] 依赖已声明（requirements.txt / compatibility）
- [ ] 无硬编码密钥；版本号与 CHANGELOG 已更新
- [ ] 调试代码已清除（print、检查点、TODO）
- [ ] 主要指令 ≤500 行 / ≤5000 tokens，详细资料已外置
