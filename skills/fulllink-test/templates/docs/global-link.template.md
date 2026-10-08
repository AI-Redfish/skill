# 全局链路：<链路名>（03-global-links/<链路名>.md）

> status: draft | reviewed | deprecated
> 用途：跨模块/跨仓库的端到端链路——从触发源到最终副作用，途经的每个模块与契约。
> 涉及模块：<模块A>、<模块B> | 最后核实：<日期>（基于 commit <hash>）

## 端到端走向

```text
<触发源：页面 / API / 设备 / 定时>
  → [模块A@<仓库1>]：<处理要点>
  → (载体：MQ topic / HTTP url / WebSocket)
  → [模块B@<仓库2>]：<处理要点>
  → 副作用：<最终 DB 变化 / 出口消息 / 推送 / 页面刷新>
  → 可观测点：<各环节日志关键字 / 指标 / 管理口查询方式>
```

## 逐环节副作用（对账断言依据）

| 环节 | 模块@仓库 | 副作用（表 / routeKey / 缓存键 / 推送） | 断言要点 |
|---|---|---|---|
| 1 | monitor-iot@basic-platform-service | t_device_property 新增行 | 改后行数 +1，payload 逐字段一致 |

## 已沉淀探针

| 探针（assets/probes/<模块>/） | 验证内容 | 运行方式 |
|---|---|---|

## 已知坑（详见 docs/06-history.md）

- <例：MQTT retained 消息：订阅先收旧保留消息，断言要带时间窗/去重>

<!-- 填写规则：
1. 每条端到端链路一篇，文件名用英文 kebab-case；单模块内部链路写在 02-modules/<模块>/link.md
2. 副作用必须具体到可断言粒度（表名/字段/routeKey/键模式/应到条数）
3. 链路变更（重构/新增环节）时更新本篇并追加 06-history.md 记录 -->
