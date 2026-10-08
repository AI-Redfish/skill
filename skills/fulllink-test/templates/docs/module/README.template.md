# <模块名>（02-modules/<模块名>/README.md）

> status: draft | reviewed
> 用途：模块知识目录入口——该模块的需求摘要 + 文档索引 + 探针索引。
> 模块目录名与 assets/probes/<模块名>/ 对齐；小模块可把 feature/link/tech 合并进本文件。

## 模块定位

- **一句话**：<这个模块解决什么业务问题>
- **业务边界**：<管什么、不管什么；与相邻模块的职责分界>
- **相关仓库/代码**：repos/<仓库>/<路径 glob>

## 文档索引

| 文档 | 内容 |
|---|---|
| [feature.md](feature.md) | 功能说明（需求视角：功能点 / 触发方式 / 预期行为） |
| [link.md](link.md) | 链路说明（模块内走向 + 与其他模块的交互） |
| [tech.md](tech.md) | 技术文档（数据模型 / MQ 与接口契约 / 关键配置） |

## 已沉淀探针（assets/probes/<模块名>/）

| 探针 | 验证内容 | 运行方式 |
|---|---|---|
| check_fanout.py | 扇出应到 N 条实到 N 条 | uv run assets/probes/<模块名>/check_fanout.py |

## 已知坑（详见 docs/06-history.md）

- <例：tenantId 超过 JS 安全整数必须按字符串处理>
