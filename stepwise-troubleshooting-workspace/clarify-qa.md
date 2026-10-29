# 需求澄清记录（stepwise-troubleshooting）

| # | 问题 | 回答 | 结论 |
|---|---|---|---|
| 1 | skill 范围定位：通用分步排查方法论（含 BPS 菜单案例作 references 示例）还是 BPS 菜单专项？ | A. 通用分步排查方法论 | 正文只放通用方法，案例脱敏后进 references/ |
| 2 | skill 名称？ | A. stepwise-troubleshooting | 目录 D:\develop\GitNote\AI-Redfish\skill\skills\stepwise-troubleshooting |
| 3 | 是否把清理 SQL 生成做成脚本？ | B. 不加脚本 | 纯流程型 skill，无 scripts/ |
| 4 | （用户补充）运行前行为 | 提醒用户提供前后端地址、分支号码等信息 | 第 0 步：环境信息收集（仓库/工作区、分支/版本、数据库地址等） |

## 关键假设（用户已确认）
1. 方法论骨架：现象澄清 → 只读核对源码判定是否代码问题 → 一次一步只读查询 → 结果判断对照表 → 预检/备份/修改/复核 → 缓存自愈核查 → 沉淀检查
2. BPS 菜单三端排查案例脱敏后写入 references/，SKILL.md 正文只放通用方法
3. 纯流程型 skill，无脚本；中文为主
4. 内嵌双闭环规则与输出精简约束章节
