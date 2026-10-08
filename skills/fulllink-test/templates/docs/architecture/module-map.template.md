# 模块地图（01-architecture/module-map.md）

> status: draft | reviewed
> 用途：全局功能索引——测试模式②影响分析的查表入口。
> 行粒度=功能模块；每个模块在 02-modules/<模块名>/ 有知识目录（README/feature/link/tech）。
> 变更文件 →（本表）模块 → 模块知识目录 / 全局链路文档。

## 模块清单

| 模块 | 功能定位（一句话） | 所属仓库 | 代码路径（glob） | 知识目录 | 相关全局链路 |
|---|---|---|---|---|---|
| monitor-iot | 设备属性上报与扇出转发 | basic-platform-service | application/**/monitor/** | [02-modules/monitor-iot/](../02-modules/monitor-iot/README.md) | [iot-property-report](../03-global-links/iot-property-report.md) |
| order-web | 订单管理页面 | bps-web | src/views/order/** | [02-modules/order-web/](../02-modules/order-web/README.md) | [order-create](../03-global-links/order-create.md) |

## 模块依赖关系（全局视角）

```text
<模块A> ──HTTP / 属性引用──> <模块B>
<模块C> ──MQ: <topic>──────> <模块D>
```

<!-- 填写规则：
1. 模块是功能划分单位，可跨仓库（前端页面模块 + 后端服务模块各成一行）；
   一个模块一个知识目录 02-modules/<模块名>/，目录名与 assets/probes/<模块名>/ 对齐
2. 代码路径写 <仓库名>:<glob>（仓库在 repos/ 下，仓库名即目录名），方便 diff 文件映射
3. 追不动的写"未知"，禁止猜测编造
4. 新增模块时同步：建 02-modules/<模块名>/ 知识目录 + 本表加行 + 视情况建全局链路文档 -->
