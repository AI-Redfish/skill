# 功能索引（02-feature-map.md）

> status: draft | reviewed（人审后改 reviewed）
> 用途：测试模式②影响分析的查表入口。行粒度=功能域；每个功能域至少一篇链路文档。

| 功能域 | 入口（API / MQ topic / 定时任务） | 涉及模块（代码路径） | 链路文档 | 备注 |
|---|---|---|---|---|
| 示例：monitor-iot 属性上报 | MQ: sinomis_iot_property | application/**/monitor/** | [03-links/iot-property-report.md](03-links/iot-property-report.md) | |

<!-- 填写规则：
1. 入口必须具体到可触发（URL、topic 名、cron），不要写"相关接口"
2. 涉及模块用 glob 路径前缀，方便 diff 文件映射
3. 追不动的写"未知"，禁止猜测编造
4. 新增功能域时同步补 03-links/ 文档 -->
