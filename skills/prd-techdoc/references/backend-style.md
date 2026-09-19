# 后端风格参考

> 说明：以下路径是**风格锚点示例**，仅用于理解该仓库的 Controller/Service/Flyway/字典风格；若调用方提供了真实后端项目路径，一律以真实项目为准（真实项目未提供时，模块/Controller 归属在“待确认与需求冲突”段标注为建议稿）。

本 skill 生成的接口、SQL、实体关系说明必须尽量贴近以下现有代码风格，而不是套用通用模板。ER 图输出时，至少要体现实体名称和核心字段。

## 1. Controller 风格

参考：
- `D:/develop/project/basic-platform-service/application/monitor/monitor-service/src/main/java/com/sinomis/monitorservice/controller/MonitorSpaceDeviceController.java`
- `D:/develop/project/basic-platform-service/application/monitor/monitor-service/src/main/java/com/sinomis/monitorservice/controller/app/MonitorAssetDeviceAppController.java`
- `D:/develop/project/basic-platform-service/application/upms/upms-service/src/main/java/com/sinomis/upmsservice/controller/SysGroupController.java`

观察到的稳定模式：
- 类级路由使用 `@RequestMapping`
- 常见路径语义：`/list`、`/add`、`/update`、`/delete`、`/view`
- `list/add/update/delete` 多为 `POST`
- `view`、简单查询、多数轻量字典查询更偏向 `GET`
- 复杂组合入参会使用多个 `@MyRequestBody` 参数，而不是强行收敛成一个通用 DTO
- 返回类型通常是 `ResponseResult<T>`

文档输出时，接口清单要尽量沿用这套命名和 HTTP Method 风格。
额外要求：
- 不输出前端函数名
- 请求参数、响应参数使用表格，至少包含字段名、类型、字段含义、字典编码（如有）

## 2. Service / Domain 分层

参考：
- `D:/develop/project/basic-platform-service/common/domain/common-monitor/src/main/java/com/sinomis/common/monitor/service/MonitorAssetDeviceService.java`
- `D:/develop/project/basic-platform-service/common/domain/common-monitor/src/main/java/com/sinomis/common/monitor/service/impl/MonitorAssetDeviceServiceImpl.java`
- `D:/develop/project/basic-platform-service/common/domain/common-upms/src/main/java/com/sinomis/common/upms/service/impl/SysGroupServiceImpl.java`

观察到的稳定模式：
- Controller 保持轻量
- 业务逻辑主要沉在 `common/domain/*/service/impl`
- 文档里的数据流转图应体现 `Controller -> Domain Service -> Mapper -> DB`
- 不要把业务逻辑直接描述成“Controller 直接落库”

## 3. Flyway SQL 风格

参考目录：
- `D:/develop/project/basic-platform-service/application/gateway/src/main/resources/db/mysql/`
- `D:/develop/project/basic-platform-service/application-tenant/tenant-admin/src/main/resources/db/mysql/`

观察到的稳定模式：
- 使用 Flyway 增量脚本，不改已存在历史脚本
- 文件名形如：
  - `V2026.03.27.16.20.00_6.0.00.00__basic_platform_ops_create.sql`
  - `V2026.03.27.15.30.00_6.0.00.00__basic_platform_mgr_create.sql`
- 只输出 MySQL 核心 DDL / DML 片段，不讨论其他数据库方言
- 新增表只保留主键，不输出额外索引定义；潜在索引需求进入查询场景和影响后归入待确认项
- 存量变更注明幂等/可重复执行、历史回填和回滚注意项写入简短 SQL 注释
- SQL 章节不写 SQL 与固定边界段之外的解释说明

## 4. 字典命名风格

参考：
- `status` -> `statusDictMap`
- `userStatus` -> `userStatusDictMap`
- `deviceDefaultDisplay` -> `deviceDefaultDisplayDictMap`
- `templateCode` -> `templateCodeDictMap`

稳定模式：
- 字段名本体保留业务字段，如 `status`
- id 到名称映射对象使用 `字段名 + DictMap`，如 `statusDictMap`
- 多值场景可能出现 `DictMapList`

接口清单中的字典映射字段必须沿用此模式，不要创造新后缀；“增量字典”章节不列 DictMap，按实体字段、字典类型与枚举项输出。

## 5. 输出时要避免

- 不要写泛化 REST 资源路由风格，如全量 `/groups/{id}`、`PATCH`、`PUT`，除非现有代码中已经明确大量采用
- 不要假设所有接口都必须单 DTO 入参
- 不要给出与现有 Flyway 命名不一致的 SQL 文件名
- 不要使用与仓库风格不符的字典字段命名
