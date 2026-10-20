# 理解闭环问答记录 — Round 2（需求变更）

## 用户变更需求（逐字）
「修改skill名称和skill内容，这个skill不止是给mysql和kingbase使用的，后续还可能给其他关系型数据库使用。」

## 十要素对照（增量）

| 要素 | 结论 |
|---|---|
| 真实目标 | skill 从"MySQL/Kingbase 双引擎专用"泛化为"关系型数据库通用 SQL 迁移技能"，当前以 MySQL/Kingbase 为已落地引擎，结构上支持扩展新引擎 |
| 关键约束 | 沿用 skill-creator-plus 全部门禁；既有内容不丢，仅重新组织表述 |
| 成功标准 | 重命名后通过机器清单 + AI 双评审 + 测试门，重新出报告与打包 |
| 禁止事项 | 不得丢失 MySQL/Kingbase 的已验证细节（幂等模板/兼容清单/字典时间治理） |
| 可接受偏差 | 新引擎的具体兼容清单暂为空（无实际需求驱动），提供扩展指引即可 |

## 需求复述（一句话）
把 skill 泛化为关系型数据库通用的 SQL 迁移技能并改名，MySQL/Kingbase 降级为"已落地引擎实例"，同时保留全部已验证内容与扩展指引。

## 关键假设
1. 新名称：`relational-db-sql-migration`（kebab-case，见名知义；目录同步改名）。
2. MySQL/Kingbase 的 reference 文件保留原名（引擎专属内容），SKILL.md 以"已落地引擎 + 扩展指引"框架组织，新增引擎时按模式补充 `references/<engine>-compatibility.md` 与幂等模板。
3. 字典表时间字段治理天然引擎无关（`CURRENT_TIMESTAMP` 为标准 SQL），仅微调文档表述；脚本不变。
4. 测试与报告以新一轮（Round 2）证据为准，Round 1 历史保留在 workspace。
