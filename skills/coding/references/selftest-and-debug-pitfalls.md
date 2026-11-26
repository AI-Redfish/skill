# 自测与联调避坑清单（selftest-and-debug-pitfalls）

**内容 + 何时读**：BPS 项目接口自测、本地起服务、微服务栈启动、HTTP 复现、联调排错前读本清单，避免重复踩同一批坑。适用范围：BPS 类 Java 多模块仓库（Spring Boot + MyBatis-Plus + 橙单框架）的本地自测与环境联调。来源：V6.0.9.2 通知模板/离线下载迭代自测实战（2026-11-25）；第 11 节来源：共享租赁优化本地联调实战（2026-11-26，upms/wms/contract/gateway 四服务注册 147 Nacos zly 空间全链路验证过程提炼）。

## 1. @MyRequestBody 参数必须按参数名包装请求体

- 框架 `MyRequestArgumentResolver` 按「Controller 参数名」从 body 取**同名 JSON 键**，无平铺 fallback。
- 平铺 body → dto=null → 旧代码 500 NPE（`getModelValidationError(null)` 静默通过校验，NPE 炸在 service 深处）；加了空防护的新代码报「请求体不能为空」。
- 正确格式：`{"alarmNotifyTemplateDto": {...}, "orderParam": {...}, "pageParam": {...}}`；list 类接口过滤键名带 `Filter` 后缀（如 `alarmNotifyTemplateDtoFilter`）。
- 自测一律用包装格式；见到「请求体不能为空」先检查是否平铺，再怀疑 token。

## 2. 实体列注解必须先对齐实际表列

- 写/改实体前先 `SHOW COLUMNS` 核对。@TableId/@TableField 列名与实际列错位 → MyBatis-Plus 按注解拼列 → insert/update 报 Unknown column 或字段错位。
- 实例：`alarm_notify_template_admin_rel` 实际列是 `template_admin_rel_id`/`notify_template_id`，实体却写成 `rel_id`/`template_id`。

## 3. DTO 主键 @NotBlank 必须限定分组

- 主键字段 `@NotBlank` 不带 groups → 新增场景也强制要求 ID → 根本无法新增。
- 正确写法：`@NotBlank(groups = {UpdateGroup.class})`（参照 `AlarmRecordDto`）。
- 自测新增接口报「xxId 不能为空」时先查这个。

## 4. insert 链不自动填充 tenant_id

- `MyModelUtil.fillCommonsForInsert` 只填 createUserId/createTime/updateUserId/updateTime；BaseService 的 tenantIdField 填充只在 **update 路径**。
- 表 `tenant_id` NOT NULL 无默认值 → insert 直接 DataIntegrityViolation「Field 'tenant_id' doesn't have a default value」。
- 项目惯例：service 的 saveNew/批量插入里手动 `xxx.setTenantId(TokenData.takeFromRequest().getTenantId())`（参照 `AlarmProcessOperationRecordServiceImpl`）。
- 排错时从 147 容器日志抓 `DataIntegrityViolationException` 能直接定位缺失列。

## 5. Windows 本地 fat jar 构建：先杀进程再打包，打包后验证嵌套 jar

- java 进程占用 jar 时 `mvn package` **静默产出旧包**（无任何报错！）——最阴险的坑。
- 标准流程：`netstat -ano | grep :port` 找 PID → `taskkill //F //PID` → `rm target/*.jar` → `mvn package` → **解包验证**：`unzip -j 服务.jar 'BOOT-INF/lib/模块.jar'` 再解嵌套 jar grep 新类特征（如新方法名/新常量）。
- reactor `package` 不 install 模块：改了 common-* 依赖模块必须先 `mvn -pl 该模块 -am install` 再 package 服务，否则服务包里是旧版依赖。
- 本机 Maven 仓库是 `D:\develop\maven\repo`（非 ~/.m2）。

## 6. Windows 本地起服务：UTF-8 + 完整 Nacos 参数缺一不可

- snakeyaml 按 GBK 读默认配置会炸：必须 `-Dfile.encoding=UTF-8`。
- Nacos 五参数要给全：config/discovery 的 server-addr + namespace + group（namespace 用 UUID）。
- 现成模板：worktree 下 `.agents/out/alarm-service-restart/start-alarm.ps1`（Start-Process + RedirectStandardOutput 落日志）。

## 7. 本地实例会注册到共享 Nacos——验证完必须停

- 本地起的服务注册到共享 Nacos（如 147）后，网关可能把线上流量负载均衡到本机开发实例——干扰用户/测试环境。
- 验证结束立即 taskkill；Nacos 自动摘除。
- 需要临时抓 SQL 时用带 `--logging.level.<dao包>=DEBUG` 的启动脚本，抓完换回普通脚本。

## 8. HTTP 复现细节（Git Bash / Windows）

- curl 中文 body 在 Git Bash 会转 GBK：**写 UTF-8 文件 + `--data-binary @file`**；`--data-raw` 内联中文必坏。
- 登录：`POST /admin/upms/login/doLogin`，body `{loginName, password: encodeURIComponent(RSA_PKCS1_b64(密码)), tenantCode}`；RSA 密钥对在 `ApplicationConstant.java`；**返回的 tokenData 是纯 UUID 字符串**（不是 JSON 对象），直接当 Authorization 头用。
- token 有效期短（分钟级），过期报 `UNAUTHORIZED_LOGIN`——重新登录即可，不要排查别的。
- 服务可能多数据源（如 alarm 有 admin/common/business 三库）：DB 直查的库与接口实际读写的库可能不同，排错先确认数据源路由再对比数据。
- 网关不剥路径前缀：Controller @RequestMapping 自带完整前缀（如 `/api/plan/dictionary`），直连服务时也要带前缀。

## 9. 框架行为假象——不是 bug，别改码

- `MyPageUtil.makeResponseData(list)` 无分页调用时 **totalCount 固定 0**，真实数据在 dataList——被 totalCount=0 误导会白排查一轮。
- 数据权限拦截器（common-datafilter 的 `MybatisDataFilterInterceptor`）按用户数据权限组织范围给 `*OrgId` 列（如 manage_org_id）拼条件：**权限外组织新增的数据本人 list/view 都不可见**（getById 也被拼条件），是设计行为。跨权限账号自测时表现为「插入成功但查不到」。
- 报「字典编码不存在」先查库（ops `sys_dict_key` / mgr `sys_tenant_dict_key`）再断言接口问题：菜单 URL 参数（如 `formIntegratedInspectionPlan`）是页面标识不是字典编码，真实字典可能是另一个（如 `formPlanManage`）。

## 10. 147 环境排错路径

- 147 = Docker Swarm + CI 镜像管线（`sinomis-ecr-registry...basic-platform/*:1.0.dev-v6-0-9-2.*`）：本地改码对 147 无效，必须提交推送触发 CI 重建镜像。
- SSH 走 MCP 连接（147 conn）；容器日志 `docker logs <容器>`；DB/Redis 走 MCP 只读连接。
- 优先「本地起服务直连验证」（localhost:port），不动 147 容器——CI 镜像不可本地替换。
- 内网 GitLab（192.168.0.51:3000）**不要走代理**：repo 级 `remote.origin.proxy=7890` 会导致 502，推送时用 `git -c http.proxy= -c https.proxy= push` 置空覆盖；外网 GitHub 才需要代理。

## 11. 本地微服务栈启动（Nacos 注册模式）——默认边界与三条硬规则

**默认边界**：开发完成默认只跑单元测试，**不启动后端服务**；仅当用户明确要求「启动服务测试/联调」时才启动，并遵守以下三条硬规则：

1. **本地启动，不远程部署**：在本机跑 jar/vite，不构建镜像部署到 147 等远程机器（远程走 CI 管线，本地改码对远程容器无效）。
2. **必须走 Nacos 注册**：项目有 Nacos 注册逻辑就必须以注册模式启动，禁止用 `--spring.cloud.nacos.discovery.enabled=false` 等非注册方式绕过——网关与下游服务的 `lb://` 路由依赖注册发现，绕过注册会让依赖服务解析不到实例（网关 503/路由失败）。
3. **启动测试所需的全部服务，不遗漏**：按调用链盘点（前端 → 网关 → 本期改动服务 → 被它调用/依赖的其他服务），逐个启动并逐一确认已注册；漏起服务表现为网关 404/503 或 `lb://` 解析失败。

**显式参数覆盖 bootstrap.yml**：jar 内 bootstrap.yml 可能指向错误环境（实测：默认指向 144:8848 的旧 namespace，服务静默注册到错误空间），必须用命令行参数显式指定（命令行优先级最高）：

```bash
java -Dfile.encoding=UTF-8 -jar <服务>.jar \
  --spring.cloud.nacos.discovery.server-addr=<host>:8848 \
  --spring.cloud.nacos.discovery.namespace=<namespaceId-UUID> \
  --spring.cloud.nacos.discovery.group=<group> \
  --spring.cloud.nacos.discovery.ip=<本机IP> \
  --spring.cloud.nacos.discovery.username=<user> \
  --spring.cloud.nacos.discovery.password=<pwd> \
  --spring.cloud.nacos.config.enabled=false \
  --spring.config.additional-location="file:<配置1>,file:<配置2>,file:<最后一个=最高优先级>"
```

- `config.enabled=false` 禁拉配置中心；功能配置用**目标空间配置快照**：从 Nacos 管理端拉取 yaml（如 `upms-dev.yaml`）存本地，additional-location 加载，替代连配置中心。
- **additional-location 后面的文件优先级更高**：多个服务共用一份配置列表时，共享配置里的 `server.port` 会覆盖当前服务端口（实测：gateway 因列表含 `contract-dev.yaml` 被抢占成 9011）。修复：把目标服务的 `server.port` 写进列表最后一个文件顶部，稳定覆盖。
- **端口冲突**：先启动的服务可能占住另一个服务的端口；`netstat -ano | grep :<port>` 找 PID 杀掉让目标服务绑定，再重启被杀服务。每次启动前先确认目标端口空闲。
- **v1 API 查实例必须带 groupName**：`/nacos/v1/ns/instance/list?serviceName=x&namespaceId=y&groupName=<group>`——不带 groupName 默认查 DEFAULT_GROUP，会误判「未注册」（实测踩过：zly 空间四服务注册成功但查询结果全空，加 groupName 后全部命中）。
- **namespace 假象**：nacos client 日志 `initializer namespace from ... attribute : null` 是 nacos-client 内部属性日志，不代表 namespace 参数没生效；注册是否成功以实例查询结果为准。
- **最小服务栈判定**：只起本期改动涉及的服务 + 网关 + 前端；未启动的服务由网关静态路由指向已部署环境（或其已注册实例）承接，数据用真实库。启动前向用户确认服务清单与端口规划。
- **验证结束立即停服务**（见第 7 条）：临时实例 taskkill 后约 30 秒自动从 Nacos 摘除，不干扰共享环境。
- **前端联调**：vite 代理指向本地网关（如 `http://127.0.0.1:8082`），E2E 走本地全链路；登录链路经网关 `lb://upms` 路由到本地实例。
