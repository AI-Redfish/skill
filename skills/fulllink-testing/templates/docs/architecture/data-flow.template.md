# 全局数据流转（01-architecture/data-flow.md）

> status: draft | reviewed
> 用途：从全局视角描述核心实体（数据）在模块/仓库间的流转——"一条数据从哪来、
> 经过谁、落在哪"。测试模式数据对账断言的依据来源。

## 核心实体流转表

| 实体 | 产生（谁写入） | 流转路径 | 最终落点（表/队列/缓存） |
|---|---|---|---|
| 设备属性 | monitor-iot（MQTT 上报） | MQTT → monitor-iot → MQ property → monitor-forward | t_device_property；转发队列 |

## 关键数据流图

```text
<设备> ──MQTT──> [monitor-iot] ──property MQ──> [monitor-forward] ──HTTP──> <下游A>
                                 └──DB: t_device_property──> <报表/查询>
```

<!-- 填写规则：
1. 每条流必须写到可对账粒度：表名 / routeKey 格式 / 缓存键模式 / 队列名
2. 与 03-global-links/ 的分工：本文件是实体粒度的全景俯瞰；03 是链路粒度的端到端详解
3. 长整型 ID 一律按字符串记录 -->
