# BPS 安全专项：全量静态审查规则

何时读：用户要求全量安全审查、Redis/MySQL/MQ 使用核查或索引缺失核对时。流程框架、总则与报告格式见 SKILL.md，本文只含专项规则。

适用对象：basic-platform-service（BPS，Java 多模块 + Redis/MySQL/RocketMQ/MinIO），基线 release 分支。
配套脚本：`check-missing-indexes.py`、`check-sql-patterns.py`、`check-transaction-failures.py` 在 BPS 工作区根目录 `scripts/`（Python 3.9+ 纯标准库；非本 skill 目录）。

## 前置条件（开工前核对）

1. 工作区干净（`git status --porcelain` 无输出），有未提交内容先按用户确认处理。
2. 切到用户指定分支并拉最新（通常 release）。报告必须注明基线 commit。
3. 确认两个外部仓库存在：SQL 归档 `D:/develop/project/basic-platform-service-sql`、前端 `D:/develop/project/wukong`。缺失时向用户要路径，不猜测。
4. 大仓库扫描（几千个文件）设置 bash timeout ≥ 180s；grep 排除 `target/`、`test` 目录与测试文件。

每个方向按「筛选 → 应报告 → 不应报告」执行。筛选命令命中的模式只是线索，必须读上下文人工甄别再下结论（见 SKILL.md 总则）。

## 方向 1：Redis

**筛选命令**：
- `grep -rl "RedisTemplate|StringRedisTemplate|Redisson"`（约 200+ 文件，只深查命中的模式）。
- 高危模式定位：`\.keys\(`、`flushdb|flushall`、`opsForValue().set(` 两参调用、先 `set` 后 `expire`。

**应报告**：
- 生产代码调用 `.keys(`（KEYS 阻塞命令）。
- `flushdb` / `flushall` 调用。
- `opsForValue().set(` 两参调用（永久 key，需逐个确认 key 是否有限集合）。
- 先 `set` 后 `expire` 非原子写（崩溃窗口内产生永久 key）。
- 凭据硬编码三类分级：真实凭据默认值（高）、设备出厂默认密码（中，需确认初始化策略）。

**不应报告**：
- 环境变量名常量（如 `PASSWORD_ENV = "REDIS_PASSWORD"`）——无风险。
- key 数量固定有限的注册表类永久 key——风险低。
- `opsForHash().multiGet`——是批量读不是全量读。

## 方向 2：MySQL / 事务 / SQL

**筛选命令**：
- `@Transactional` 统计：总数 + 无 `rollbackFor` 数量（`grep "@Transactional$"` 或 `-A1` 无 rollbackFor 的）。
- Mapper XML：只在 `*Mapper*.xml` 里搜 `${}`（全仓搜会命中 pom 的 `${xx.version}` 干扰）。
- 事务内远程调用：`@Transactional` 方法体内 grep Feign/MQ 发送。

**应报告**：
- 无 `rollbackFor` 的 `@Transactional` 占比 >5% 时列入低风险（默认只回滚 RuntimeException）。
- Mapper XML `${}` 三类分级：
  - 条件值 `${}` 直拼：高危。
  - IN 值直拼 `'${item}'` 且来源为前端输入：中高危。
  - 列名拼接（`${orderBy}`/`${inFilterColumn}`）且 Java 侧未经 `MyModelUtil.mapToColumnName`/`MyOrderParam.buildOrderBy` 映射：中高。
- IN 值直拼且调用方为前端输入直达：中高危。
- `@Transactional` 方法体内出现 Feign 调用 / MQ 发送（拉长事务）。

**不应报告**：
- 列名拼接但 Java 侧经 `MyModelUtil.mapToColumnName`/`MyOrderParam.buildOrderBy` 映射——框架防护（未匹配列抛异常）。
- IN 值来自内部集合（数据权限部门 ID 等）——低风险。
- Mapper XML 动态参数名（orderby/infiltercolumn/infiltervalues/item）不是真实列名，用表列定义校验后再判。
- pom/logback 中的 `${}`（version 占位干扰，见方向 10）。
- 类名含 `Client` 的本地服务（如 OAuth Client 管理）不是 Feign——看 import 判断。

## 方向 3：索引核对

**筛选命令**：
```bash
python scripts/check-missing-indexes.py --min-refs 3
# 参数：--sql-repo、--backend、--libs、--min-refs
```
脚本原理：解析归档 `mysql/<lib>/*.sql` 的 CREATE TABLE 内联索引（含 PRIMARY KEY）与 CREATE INDEX/ALTER ADD INDEX，对比后端 Mapper XML WHERE 条件列。

**输出分两组**：「确定疑似」（列在表定义中且无任何索引含它）与「待人工确认」（JOIN 归属不明）。

**应报告**：
- 「确定疑似」组经人工复核成立的项。
- 建表语句漏 PRIMARY KEY 的表（如 comments 表）——表设计问题，比缺索引严重，单独列报。

**不应报告（脚本静态局限，人工复核规则）**：
- 主键/唯一键列报出的 → 查归档确认后排除（表定义可能跨多个脚本）。
- `deleted_flag`、`status` 等低选择性列 → 不建议单独加索引，建议并入高频列组合。
- 疑似项查 Java 调用频率与真实数据量，最终 EXPLAIN 验证后再走 Flyway 双端幂等流程（见 relational-db-sql-migration skill）。

## 方向 4：前后端接口抽查

**筛选命令**：
- 前端 URL：`packages-web/api` 与 `apps/*/api` 的 .ts 中字符串字面量。
- 后端：controller 目录 `@.*Mapping` 注解。

**已知限制**：后端大量使用 `@RequestMapping(URL常量)` 无法静态解析，全量对照必然产生 1000+ 假 mismatch，**不可据此下结论**，只做三类抽查：
1. 挑底层依赖 KEYS 扫描等高危实现的接口（接口层无缓存/节流为风险）。
2. `listAll` 类全量返回接口、前端循环逐条调用（N+1）模式。
3. 上传下载链路：`getOriginalFilename` 落盘、Content-Disposition 编码、扩展名白名单。

**应报告**：
- 三类抽查点确认的风险。
- 网关鉴权链路：`application/gateway/.../filter/AuthenticationPreFilter` 的白名单与无条件放行逻辑（如 `/v3/api-docs`），代码层放行 + Nacos 未关 springdoc = 生产 API 结构泄漏。**报告须标注「待确认」而非定论**，因 Nacos 配置本地不可见。

## 方向 5：MQ / 中间件

**筛选命令**：
- `grep -rl "@RocketMQMessageListener"`。
- RabbitMQ 面：`RabbitTemplate|@RabbitListener`；`convertAndSend` 计数。

**应报告（RocketMQ 逐个消费者核对四要素）**：
1. `consumeMode`：ORDERLY 未设 `maxReconsumeTimes` = 脏数据阻塞分区。
2. `consumerGroup` 命名：应用名粒度过宽 = 同组订阅关系冲突风险。
3. `messageModel`：BROADCASTING 失败即丢。
4. 消费幂等：监听器无去重/唯一约束，且发送端无事务消息时幂等责任在消费端。

**不应报告**：无。正面样本也记录（如重试字段表设计、环境变量注入密码），报告中体现平衡。

## 方向 6：自主扩展角度（每次都过一遍）

| 角度 | 应报告信号 |
|------|---------|
| 硬编码凭据 | 源码默认值含真实密码/内网 IP；设备出厂密码；`.env` 值入代码 |
| 日志敏感信息 | log 打印 password/token/idCard 明文（打 userId/tenantId 属正常，不应报告） |
| 文件上传下载 | 无扩展名白名单；路径拼接用户输入；Content-Disposition 未编码 |
| SQL 注入 | 见方向 2 |
| XSS | 富文本展示无 escape；网关无全局过滤器时风险可控（JSON API + 前端框架转义） |
| 越权 | Controller 用前端传 userId 直查而不取 `TokenData.current()` |
| 反序列化 | ObjectInputStream/XStream；fastjson 1.x 检查版本（1.2.83 为 1.x 末版，已停维，建议 fastjson2） |
| 依赖停维 | pom 关键组件版本；`pom.xml` 已有版本上界防回退机制则记录为正面 |
| 多租户隔离 | 抽查高频 Mapper 是否带 tenant_id 条件 |
| 监控端点 | Actuator/Druid 暴露配置在 Nacos，本地不可见 → 列入未覆盖项，提示用户自查 |

## 方向 7：并发与事务失效

**筛选命令**：
- 类级 `static` 非 final 的 Map/List/Set 字段正则（排除方法内局部与常量字典）。
- `Executors.newFixedThreadPool|newCachedThreadPool`。
- `DocumentBuilderFactory|SAXParserFactory|XMLInputFactory|SAXReader`。
- `GroovyShell|GroovyClassLoader|SpelExpressionParser + StandardEvaluationContext`。
- `Runtime.exec|ProcessBuilder`、`autoTypeSupport|addAccept`。
- `@Scheduled` 方法总数与入口无锁数。
- 事务失效：`python scripts/check-transaction-failures.py --repo`（方法级解析：提取方法块 + @Transactional 状态）。

**应报告**：
- `public static` 可变集合（低风险）。
- 线程池无界队列（`newFixedThreadPool`/`newCachedThreadPool`，洪峰 OOM）。
- XXE：逐处确认未禁 DTD/外部实体的实例；重点查**解析用户上传文件内容**的场景（xlsx 本质 zip，内部 XML 攻击者可控）。
- 动态代码执行：Groovy 零调用方也列报（预留 RCE 能力）；SpEL 需确认表达式来自注解常量还是用户输入（用户输入才高危）。
- 事务失效两类：非 public 事务方法（Spring 代理只对 public 生效，注解静默忽略）；非事务方法内自调用事务方法（绕过代理）。高发模式：`protected/private @Transactional` + 循环单条写入（批量推送/通知处理场景）。
- `@Scheduled` 多实例部署且入口无锁（定级标注条件性：多实例才成立）。

**不应报告（事务失效误报教训，脚本已内置，人工复核时同样适用）**：
- 正则排除控制流关键字（if/for/while/switch/catch 被误识别为方法名）。
- 排除 `@TransactionalEventListener` 等事件注解。
- 排除事务方法间互调（彼此在事务中不失效）。粗正则误报 878 处，精确解析后 29 处。
- XXE 已正确配置的（仓内正确写法可照搬：`IS_SUPPORTING_EXTERNAL_ENTITIES=false` + `SUPPORT_DTD=false`）。

## 方向 8：WebSocket 鉴权链路

**应报告**：
- 公开通道与认证通道共用 handler 且无 userId 兜底。
- `setAllowedOriginPatterns` 通配（CSWSH 面）。
- token 走 URL 参数（进日志/历史）。

**不应报告**：
- 握手拦截器无条件 `return true` 但 handler 层（`afterConnectionEstablished`）有 userId 兜底拒绝——双层结构需逐层确认，上层兜底则握手层放行不算漏洞。

## 方向 9：SQL 深度与配置

**筛选命令**：
- `python scripts/check-sql-patterns.py --repo`（statement 级解析，输出四类清单）。
- `PaginationInnerInterceptor.setMaxLimit` 与 `MyPageParam.DEFAULT_MAX_SIZE` 定位。
- `isRequestRateLimited|isVerificationLocked` 定位。
- config-data/nacos 样例目录、pom profiles 中的凭据模式。
- spring-boot/spring-cloud/mysql-connector/netty 版本。

**应报告**：
- LIMIT 无 ORDER BY 的列表场景（byId 场景无害，列表场景结果不稳定）。
- 前导 % LIKE（全局搜索，索引失效已知代价）。
- SELECT *（关注 longtext 大字段表）。
- 分页上限未设（`setMaxLimit(-1)` 或超大的 DEFAULT_MAX_SIZE；部分模块自定义上限属正面）。
- 登录防爆破未覆盖登录/验证码/租户查询。
- 上传/解压防护缺失：Zip 条目数与解压总量无上限；无文件头 magic number 校验；Excel 导出公式注入未转义（前导单引号）。
- dev 配置入库：config-data/nacos 样例目录弱凭据（admin/admin123456、123456 类）；生产沿用则升级。
- 构建配置凭据：pom profiles 中的 Nacos/中间件密码与生产 IP/namespace——凭据明文入库与生产拓扑泄漏都算高险候选。
- 主框架版本停维/过旧。

## 方向 10：误报甄别总规则（三轮验证）

1. `${}` 全仓搜索先排除 pom/logback（pom version 占位干扰）。
2. Mapper 动态参数名（orderby/infiltercolumn/infiltervalues/item）不是真实列名，用表列定义校验。
3. 主键列必须单独提取 PRIMARY KEY 比对，否则主键误报缺索引。
4. 类名含 Client 的本地服务（OAuth Client）不是 Feign，看 import 判断。
5. 脚本自动结论必须抽查 3-5 项到归档/源码原文人工复核后才写入报告。

## 复查模式（基线未变的重新审查）

触发：用户要求「重新审查 / 出修复版报告」且基线 commit 与既有报告一致时：
1. 不重跑全量扫描。
2. 对高风险与关键发现逐点 grep 复核原位置（含 SQL 归档建表块尾部确认主键）。
3. 其余项沿用既有结论，报告「复核说明」标注实际复核范围。
4. 修复版文件名 `security-review-<YYYY-MM-DD>-r2.md/.html`。

## 已知边界

- 纯静态审查：不能替代渗透测试、运行时 Redis `--bigkeys`/`INFO memory` 实测、生产 EXPLAIN。
- 前后端全量接口对照受路径常量限制不可行，只做抽查。
- Nacos 配置中心实际生效值不在本仓库，相关结论一律标「待确认」。
