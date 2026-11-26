# 自测与联调避坑清单（selftest-and-debug-pitfalls）

**内容 + 何时读**：BPS 项目接口自测、本地起服务、微服务栈启动、HTTP 复现、联调排错前读本清单，避免重复踩同一批坑。适用范围：BPS 类 Java 多模块仓库（Spring Boot + MyBatis-Plus + 橙单框架）的本地自测与环境联调。来源：V6.0.9.2 通知模板/离线下载迭代自测实战（2026-11-25）；第 11 节来源：共享租赁优化本地联调实战（2026-11-26，upms/wms/contract/gateway 四服务注册 147 Nacos zly 空间全链路验证过程提炼）；第 12 节来源：V6.0.9.2 主动报警前后端联调实战（2026-11-26，gateway/upms/alarm 三服务并行启动 + 多网卡注册 IP/端口占用/缺列对齐/混路由四类坑现场复盘）。

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
- **服务清单判定（分场景）**：纯后端自测可用最小栈（只起改动服务+网关）；**前后端联调默认清单 = gateway（前端入口）+ upms（登录基础服务）+ 本期改动服务**，三者缺一联调不成立（实测教训：只起改动服务被用户打回，要求补 gateway+upms）。启动前向用户确认清单与端口规划。完整启动 SOP 见第 12 节。
- **验证结束立即停服务**（见第 7 条）：临时实例 taskkill 后约 30 秒自动从 Nacos 摘除，不干扰共享环境。
- **前端联调**：vite 代理指向本地网关（如 `http://127.0.0.1:8082`），E2E 走本地全链路；登录链路经网关 `lb://upms` 路由到本地实例。

## 12. 本地联调全链路启动 SOP——固定流程，避免每次重启耗时（2026-11-26 主动报警联调实战提炼）

### 12.1 服务清单与 jar 时效

- 联调默认清单 = **gateway + upms + 本期改动服务**（同第 11 节口径）；端口与注册信息在 Nacos 配置中心下发（bootstrap.yml 无 port），从各服务日志 `Tomcat started on port X` 获取。本环境基线：gateway 8082 / upms 9000 / alarm 11004。
- **仅本期改动的模块需重新构建**：`mvn -pl <模块> -am package -DskipTests -Dmaven.gitcommitid.skip=true`（gitcommitid 插件不 skip 会在无 git 信息环境报错）。gateway/upms 未改动时旧 jar 直接用——启动前 `ls -la target/*.jar` 核对构建时间晚于最后一次相关代码改动即可。
- 构建前先杀占用旧 jar 的 java 进程（见第 5 节锁包坑）。

### 12.2 并行启动（总耗时 = 最慢服务 ≈ 2.5 分钟，而非串行累加）

1. **启动前预检**：一次查全部目标端口 `powershell "Get-NetTCPConnection -LocalPort 8082,9000,11004 -State Listen"`，有占用先清理（见 12.4），避免启动到 100 秒才报 PortInUse。
2. 每服务一个启动脚本（模板见第 6 节 + `.agents/out/<service>-restart/start-<service>.ps1`），**并行**执行全部脚本（Start-Process 立即返回不阻塞）。
3. **等待策略**：`sleep 90` 后逐个 grep 就绪关键词，未就绪再补 `sleep 60` 重查。禁止单条长 sleep（>120s）阻塞等待——命令会被超时 abort，且 abort 后进程仍会拉起（见 12.4）。
4. 各服务启动耗时基线：alarm ≈103–113s、upms ≈159s；gateway 打完 sa-token banner 后可能不再输出就绪行，以端口探测为准（见 12.3）。

### 12.3 就绪判定（三层，逐层收紧）

- **日志关键词**：`Tomcat started on port` + `Started XxxApplication` + `nacos registry ... register finished` 三者齐 = 就绪；注册行同时核对实例 IP（见 12.5）。
- **端口探测**：`curl http://localhost:<port>/` 返回 HTTP 404 = 进程活着（根路径无映射是正常现象，别当失败）。
- **端到端路由**：curl 网关业务路径（无 token 预期 `UNAUTHORIZED_LOGIN`），同时确认**本地服务日志出现同一时刻的请求记录**——这一步同时验证网关路由与实例命中。

### 12.4 端口占用（PortInUseException）因果链

- 高频起因：上一次被 abort 的启动命令**仍然拉起了进程**（Start-Process 异步，命令 abort 不杀进程），残留实例占住端口。
- 排障顺序：`Get-NetTCPConnection -LocalPort <port> -State Listen` 拿 PID → `Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"` 确认 CommandLine 是目标 jar → `Stop-Process -Force` → 重启。
- **噪音陷阱**：PortInUse 失败后 Spring 仍继续初始化，后续还会炸出别的异常（如 Unknown column 刷屏）——先解决端口根因、重启成功后再逐个看剩余报错，别被启动失败现场的后续日志带偏。

### 12.5 多网卡注册 IP（联调请求全超时的元凶）

- 本机有 VPN/虚拟网卡时（Tailscale 100.64.0.0/10 CGNAT 段等），Spring Cloud **可能自动选中它**注册 Nacos——远端网关路由不到该 IP，经网关的联调请求全部超时。
- 启动参数**必须显式** `--spring.cloud.nacos.discovery.ip=<以太网IP>`；用 `Get-NetIPAddress -AddressFamily IPv4` 查，排除 `127.*`、`169.254.*`、`100.64–127.*`（CGNAT）、Docker 网桥（`172.17.*` 等）网段。
- 启动日志核对：`registering service <name> with instance Instance{ip=<期望的局域网IP>...}`。

### 12.6 本地新代码 vs 共享库缺列

- 本地分支实体新增列（`@TableField`）而共享库（如 147）未执行对应迁移 → 该表**所有 MyBatis-Plus 全列查询失败**（列表页、定时任务全挂），日志周期性刷 `Unknown column 'x' in 'field list'`。
- 对齐方法：从实体类提取全部 `@TableField(value=...)` 列名 ↔ 查 `information_schema.COLUMNS` 实际列，差集即缺列；列定义从 SQL 归档仓库对应迁移脚本取原文，幂等 ALTER 补齐（可空列无风险；唯一索引对全 NULL 历史数据不冲突）。
- 补列后观察调度日志恢复（错误计数不再增长 + 出现正常任务日志）。
- 良性 ERROR 别误判：启动日志 `For security constraints with URL pattern [/*] only the HTTP methods...` 每次启动都有，无碍。

### 12.7 混路由：本地实例与远端旧实例并存

- 本地实例注册共享 Nacos 后，网关负载均衡**随机分流**本地新代码实例与远端旧代码实例 → 同一接口行为时灵时不灵（联调最大干扰源）。
- 识别命中实例：① 不同版本错误文案差异（如新代码「主动报警位置不能为空」vs 旧代码「警情类型不能为空」）；② 本地服务日志有无该请求记录。
- 处置：用户确认后缩容远端容器（`docker service scale <service>=0`）；未改动服务（upms/gateway）代码一致，混路由无影响，无需处理。

### 12.8 服务直连免登录（仅限本地自测）

- 绕过网关直连服务端口时，请求加 header `DONT_AUTH: true` 可跳过 sa-token 校验（`ApplicationConstant.HTTP_HEADER_DONT_AUTH`，common-core）；**网关层照样拦截**，经网关的请求必须真 token。
- 请求体按第 1 节包装格式；本地验证无 token 拦截属预期，别当路由故障。
