# 全链路消息测试实战要点（MQ 模拟上游驱动 + 中间件预置）

> 来源：2026-11-11 BPS 电梯监测需求本地全链路实测（monitor/alarm 双服务 + MySQL/Redis/RabbitMQ/TDEngine）。
> 何时读：测试模式执行④对账阶段，需要用 MQ 消息模拟上游服务（规则引擎/IoT 平台）驱动消费方验证业务链路、或需要在 Redis 预置测试上下文时。

## 1. 消息驱动消费的三步法

1. **报文考古**：从消费方代码（`@RabbitListener` / 监听容器注册 / 消息体反序列化类）反推队列名、
   交换机与消息体结构；报文顶层字段以反序列化目标类为准（如 `LotEventMqMessage` 顶层字段 +
   `data.beaconList` 子结构；规则场景消息 `fireRecordId/triggerContext.objectId/actionsConfig.items[].alarm`）。
2. **定向消费**：共享队列存在多实例消费竞态时，消息会被随机路由到其他实例。可靠做法是临时把
   消费方配置的队列名改为私有名（改 nacos 配置或命令行参数 `--<prefix>.queue.<key>=<私有名>`，
   注意 Spring Cloud bootstrap 默认覆盖命令行参数，需加 `--spring.cloud.config.override-system-properties=false`），
   使被测本地实例成为唯一消费者；测完恢复原配置并删除私有队列。
3. **发布与断言**：pika（Python）直连发布（`exchange=""` + routing_key=队列名即直达）；
   断言用**落库副作用**（DB 查询）而非日志——日志可能缓冲或级别过滤。每条消息用唯一业务幂等键
   （如 `fireRecordId`），既验证幂等又便于按键清理。

## 2. Redis 测试预置：先弄清客户端 codec

服务端可能用 Redisson（默认 JsonCodec/MarshallingCodec）而非裸字符串读写同一 key：

- **判别方法**：GET 一个生产路径写入的同类 key，看值是否带外层引号/转义（JsonCodec 特征）
  或二进制乱码（MarshallingCodec）。raw redis-cli 写入的"干净 JSON"在 JsonCodec 服务端读取时
  会被解析成对象导致 `(String) get` 转型失败被静默吞掉 → 返回 null。
- **预写公式**（JsonCodec）：把目标字符串再做一层 JSON 字符串编码后存入，
  即 `redis_value = json.dumps(target_json_str, ensure_ascii=False)`。
- 预置后用与被测代码**相同的读取路径**验证一次（或先发一条消息观察副作用），再进入正式用例。

## 3. 消费侧前置依赖的考古清单

| 依赖点 | 常见实现 | 测试前检查 |
|---|---|---|
| 事件租户解析 | 按 SN 查绑定关系表（如 `monitor_object_iot.rel_sn_code`）取租户，结果缓存 Redis | 测试设备先插绑定行（注意建表非空约束列），删解析缓存 key（可能是 `"UNRESOLVED"`） |
| 数据源/驱动 | 本地启动需特定数据库驱动与地址（如 TDEngine TAOS-RS 而非 WS） | 启动失败看 `Failed to prepare xxx` 类 bean 异常，按 driver/url 修正 |
| 编码 | Windows 本地 JVM 默认 GBK，nacos UTF-8 配置解析会 MalformedInputException | 启动加 `-Dfile.encoding=UTF-8` |
| 配置覆盖 | Spring Cloud bootstrap 默认覆盖命令行参数 | 本地覆盖配置加 `--spring.cloud.config.override-system-properties=false` |
| 外部引擎/第三方服务 | 按 `sys_tenant`（或同类租户配置表 + Redis 缓存）取服务地址 | 地址未配置时消费侧走失败分支：断言失败状态与降级行为；需验证成功路径时预置缓存模拟或配置真实地址 |

## 4. 失败路径的模拟验证（无真实第三方时的替代）

外部依赖（定位引擎/规则引擎/风控）不可用时，不硬造环境，改验证**消费侧降级契约**：

1. 预置中间态（如 Redis 上下文 `PENDING/FAILED/DONE`）驱动各分支断言（状态码、字段、缓存副作用、锁释放）；
2. 成功路径用"预置成功结果 + 直接调用下游落库入口"两段验证（消费侧读取逻辑与落库逻辑分开证实）；
3. 报告中标注：真实第三方成功路径未覆盖，需在配置了真实地址的环境补测。

## 5. 测试数据保留与清理

- 有界面回归价值的数据（报警行、设备、绑定）保留并在交付中列明，供前端/产品在界面核对；
- 清理脚本按业务幂等键（fireRecordId/SN）圈定范围，先 SELECT 后 DELETE，不裸删。
