# 案例：BPS 绑定类接口报 DATA_ACCESS_FAILED（根因 insert 漏填 tenant_id）

> 内容：一条"通用兜底错误码 → 分层定位到具体 SQL 失败点"的排查路径，以及 BPS 项目 insert 租户字段约定。
> 何时读：接口返回 HTTP 200 但 `errorCode=DATA_ACCESS_FAILED`（或类似全局兜底错误）、且同级只读接口正常时读取本案例。
> 适用范围：BPS（basic-platform-service）系列前后端分离系统；来源：2026-11-06 计划任务点绑定摄像头（`/api/plan/taskPointMonitor/bind`）联调排障实测。

## 现象与陷阱

- 前端报错信息是兜底文案"无法访问系统信息，请稍后重试"，无堆栈、无细节。
- `DATA_ACCESS_FAILED` 只对应 Spring `DataAccessException`（`MyExceptionHandler.dataAccessExceptionHandle`）；
  `MyRuntimeException`（业务校验失败）走独立处理器、会返回具体业务文案。两者必须区分：
  - 返回业务文案（如"任务点不存在"）→ 校验逻辑在跑，查数据即可；
  - 返回 `DATA_ACCESS_FAILED` → SQL 层炸了（缺表/缺列/约束违反/方言问题），查日志堆栈或逐段排除。

## 分层定位法（只读手段逐段排除，每段一个判据）

1. **重放原请求**：拿用户给的 curl（转成 bash 转义）原样重放，拿到真实响应体——不猜错误。
2. **对照只读兄弟接口**：同一 Controller 内的只读接口（如 list/candidateList）逐个调用。
   某个只读接口通过 = 该接口覆盖的链路段（鉴权/Feign/某表 SELECT）健康；故障点收缩到写接口独有步骤。
3. **用只读接口判数据类型**：本例 `/view` 只查 `plan_task_point`（自建类型）→ 返回 NOT_FOUND 说明任务点是
   多源类型（空间/资产/风险点），提示去对应源表查存在性。
4. **环境与库对账**：用接口返回的真实数据（设备名、ID）反查用户给的库；查无此数据说明
   用户给的库与部署环境不匹配（本次就出现 147/144 报错库名口误），先纠正库再继续。
5. **库内取证**：目标写表 `SHOW CREATE TABLE` 看约束（NOT NULL 无默认值的列是重点）、
   `COUNT(*)` 看该操作是否从未成功过（0 行 = 写路径从未打通）。
6. **代码对账**：insert 前逐字段核对"代码赋值 ∪ 通用填充 ∪ DB 默认值"是否覆盖全部 NOT NULL 列。

## 根因与通用规则

- 根因：`bindDevices` 构建实体时未设 `tenantId`，而 plan 服务无 `MetaObjectHandler`/`TenantLineInnerInterceptor`
  自动填充；`fillCommonsForInsert` 只填 createUser/createTime/updateUser/updateTime。
  MyBatis-Plus 默认 NOT_NULL 策略下 null 字段不进 INSERT 列清单，MySQL 严格模式报
  "Field 'tenant_id' doesn't have a default value" → `DataIntegrityViolationException` → `DATA_ACCESS_FAILED`。
- **通用规则：BPS 各服务的 insert 实体，NOT NULL 业务列（tenant_id 等）必须显式赋值，
  不能指望全局自动填充**。项目惯例写法：`entity.setTenantId(TokenData.takeFromRequest().getTenantId())`
  （先例：`PlanExecuteTaskAssigneeServiceImpl`、`PlanExecuteTaskPointServiceImpl`）。
- 单测配套：服务内调用 `TokenData` 静态方法时用 `Mockito.mockStatic(TokenData.class)` 打桩
  （先例：`PlanExecuteTaskRecordPointServiceImplTest`）。
- 修复验证：单测断言 insert 捕获体的 tenantId 非空；实库联调需重新部署后重放原请求，检查目标表行数。

## 剩余限制

- 未经实库复测（修复后需重新编译部署 plan 服务）。
- 兜底错误码全集与各异常处理器映射关系仅核实了 `DATA_ACCESS_FAILED` / `MyRuntimeException` 两条分支。
