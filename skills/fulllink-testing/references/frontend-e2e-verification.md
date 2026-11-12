# 前端界面验证与联调（E2E 后给用户可点链接 + 界面可见数据造数）

> 来源：2026-11-12 BPS 电梯监测需求实测（报警详情定位三态、电梯监测信息 12 项、定位引擎 mock、属性最新值缓存造数）。
> 何时读：测试模式收尾阶段——需要给用户/前端可点击的验证链接、为界面展示造测试数据、mock 第三方服务（定位引擎/IoT 平台），或排查"接口有数据但页面为空/名称不对"类问题时。

## 1. 交付模式：链接 + 测试数据 + 期望表

界面验证的交付物不是口头描述，而是三件套：

1. **可直接点击的链接**（带路由参数直达目标状态，如 `#/alarmDetail?id=<alarmId>`、`#/page?deviceId=<id>`）；
2. **每条链接对应一份测试数据**（DB 可查证，字段值给出期望表）；
3. **期望结果表**（状态文案、坐标、按钮显隐逐项列明），并注明验证前提（登录入口、硬刷新）。

入口链路要一次讲清并实测过：前端 dev（vite，用 `.env.development.local` 覆盖 proxy target——gitignore 内不提交）→ 本地 gateway → 本地业务服务 → 共享中间件。gateway 真实端口以**实际监听**为准（实测 8082，配置假设 18082 不成立）；登录走 upms（`/admin/upms/login/doLogin`），sso 缺配置不影响账号密码登录。

**自测免问账号**：用户登录后 token 存 Redis（sa-token `Authorization:login:token:{uuid}`），可直接 `KEYS` 取有效 token 调接口核对数据。注意：非用户本人账号可能触发 `NoDataPermException`（数据权限按账号配置），诊断时先排除该干扰——它常出现在 `SysSpaceInfoMapper` 等带数据权限拦截的查询里，表现为局部降级（接口 success=true 但值为空）。

## 2. 界面数据造数：三条路径与键名实证

界面展示值可能来自 DB、服务端缓存或第三方平台，造数前先用 MONITOR 实证读取路径：

- **Redis MONITOR 实证法（必做）**：`MONITOR` 后触发一次页面/接口调用，观察服务实际读写哪个键。仅 grep 代码会踩坑——同类缓存存在多个相似前缀（实测 `IotLatestValueStore` 写 `monitor:iot:socket:property:*`，而查询读取的是 `monitor:iot:latest:{sn}`），写错前缀则页面永远为空。
- **属性最新值缓存**（BPS 电梯监测信息数据源）：key `monitor:iot:latest:{sn}`；**StringCodec 原生字符串 hash**（区别于 Redisson JsonCodec 的双编码！）；field=property 标识，value=`dataTime|receiveTime|jsonValue`（如 `1731396000000|1731396000000|1.75`，字符串值 JSON 带引号），`__p`=productId（缺失时走本地表兜底查询，可能触发数据权限异常）。
- **参数绑定行决定接口返回哪些项**（如 `monitor_object_iot` + `monitor_device_type_iot`：绑定行缺失的 property 接口直接不返回，页面显示 `-` 的根因可能是绑定行而不是值）。
- **位置/楼层类 ID 必须真实**：定位引擎返回的 `floorCode`、报警 `alarm_location` 等语义是 `sys_space_info.space_info_id`，造数写编造编码（如 "305"）会导致关联失败页面空白。

## 3. 第三方服务 mock（定位引擎实例）

真实验证成功路径而不搭真实引擎：本地起最小 HTTP mock，把租户配置指过去。

1. **契约考古**：从 Feign 接口注解读路径与响应结构。定位引擎实例：
   `POST {baseUri}/api/iot/v6/beacon/location/getPositionByBeacon`，请求 `{tenantId, campusId, deviceSN, timestamp, beaconList:[{sn,rssi}]}`，响应 `{"code":200,"msg":"ok","data":{"deviceSN","timestamp"(ISO offset 如 2026-11-12T16:35:00+08:00，用 OffsetDateTime.parse 解析),"floorCode","x","y","z"}}`（x/y/z 为字符串）。
2. **配置切换**：改 `sys_tenant.location_engine_service_url`（ops 与 mgr 两库口径不同，按读取方所在库改）→ **必须删 Redis 缓存 `TENANT_IOT_CONFIG:{tenantId}`**，记录原值测完回滚。
3. **两个验证位**：mock 日志确认收到真实引擎请求（证明消费链路通）+ 落库字段核对（证明结果消费正确）。

## 4. 展示名兜底与前端布局

- 物模型（jetlinks/IoT 平台）没有新属性时，`propertyName` 退化成英文标识。最小修复：后端组装处加**本地参数别名兜底**（DB `rel_meta_alias_name`），前端不动。
- 前端布局类改动（栅格列数、顺序）属 CSS 一行改动，vite dev 热更新即时生效；交付时提醒用户**硬刷新**。

## 5. MQ 发布被静默丢弃（管理页坑）

经 Exchange + routing key 在管理页发布，routing key 多一个空格/换行即被**静默丢弃**（无报错、无堆积）。可靠做法：管理页 **Queues → 目标队列 → Publish message**（直达，不需要 routing key）。诊断"消息没被消费"时先查队列 `msgs/consumers`：队列空且有消费者 = 消息没进队列（发布侧问题），而非消费侧。

## 6. 报警定位展示契约（BPS 8073 实测口径）

| locate_status | 页面 | 附带 |
|---|---|---|
| 1 已定位 | 坐标（解析 locateCoordinate JSON：floorCode/x/y/z）+ 定位时间 + 「查看历史轨迹」入口 | source_event_id=jetlinks messageId |
| 2 定位失败 | 「定位失败」+ `-` + 无入口，**报警位置（alarm_location）不回退安装位置，留 NULL**（用户裁决） | 引擎异常/超时/上下文 FAILED |
| NULL 未提供定位 | `-` + 无入口 | 事件无 beaconList 且设备从未定位 |

验证三态各造一条数据（引擎 mock 开关切换 + 清定位上下文缓存），交付三条链接。

## 7. 收尾清单模式

测试结束停止服务时区分两类：

- **本会话启动的**（前端 dev、gateway、业务服务、mock、临时配置覆盖）：直接停/回滚；
- **环境原有的**（如 upms、其他常驻实例）：保留并说明，不擅自停。

数据清理（DB 行/Redis 键/TDEngine 表/私有队列）属删除操作：列清单待用户确认后执行，造数时统一用可识别标记（id 前缀、描述关键字）便于精准清理。
