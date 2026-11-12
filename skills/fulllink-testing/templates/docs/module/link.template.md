# <模块名> 链路说明（link.md）

> status: draft | reviewed
> 用途：模块视角的链路——模块内调用走向 + 与其他模块/仓库的进出交互。
> 模块内细节看本文件；跨模块端到端看 03-global-links/。

## 模块内链路

```text
入口：<HTTP API / MQ topic / 定时任务>
  → 服务/类：<处理链上的关键类与方法>
  → 中间件交互：<读写的交换机/队列/topic/缓存键/表>
  → 副作用：<DB 表与字段变化 / 出口消息 / 缓存变更 / WebSocket 推送>
  → 可观测点：<日志关键字 / 指标名 / 管理口查询方式>
```

## 与其他模块的交互（模块间链路关系）

| 方向 | 对端模块 | 载体（API / MQ topic / DB 表 / WebSocket） | 契约说明 | 全局链路文档 |
|---|---|---|---|---|
| 出 | monitor-forward | MQ: sinomis_iot_property | routeKey=<sn>，扇出到设备所属系统 | [iot-property-report](../../03-global-links/iot-property-report.md) |
| 入 | device-mgr | DB: t_device（只读） | 读取设备档案与系统归属 | — |

<!-- 填写规则：
1. "副作用"必须具体到表名 / routeKey 格式 / 缓存键模式——这是对账断言的依据
2. 交互表覆盖本模块全部进出依赖（含跨仓库）；跨模块端到端场景另建 03-global-links/ 文档
3. 代码考古追不动的环节标"未知"，测后回填 -->
