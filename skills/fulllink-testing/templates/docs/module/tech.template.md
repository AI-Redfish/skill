# <模块名> 技术文档（tech.md）

> status: draft | reviewed
> 用途：技术视角的模块文档——数据模型、对外契约、关键配置。
> 对账断言（表/字段/routeKey/缓存键）的技术依据；长整型 ID 一律按字符串记录。

## 数据模型

| 表/实体 | 关键字段 | 说明（谁写、谁读、生命周期） |
|---|---|---|
| t_device_property | id(bigint), sn, tenant_id, payload, create_time | monitor-iot 写；报表读；保留 90 天 |

## MQ / 消息契约

| 交换机/队列/topic | 方向 | 消息格式（关键字段） | routeKey 规则 |
|---|---|---|---|
| sinomis_iot_property（exchange） | 出 | {messageId, sn, tenantId, payload, ts} | routeKey=<sn> |

## 接口契约

| API | 方法 | 入参/出参要点 | 调用方 |
|---|---|---|---|
| /api/device/{sn}/property/latest | GET | 出参：最新属性 + 时间戳 | bps-web |

## 缓存

| 键模式 | 值 | TTL | 失效场景 |
|---|---|---|---|

## 关键配置

| 配置项 | 默认值 | 来源（Nacos dataId / application.yml） | 影响 |
|---|---|---|---|
