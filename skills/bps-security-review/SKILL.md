---
name: bps-security-review
description: 对 basic-platform-service（BPS，Java 多模块 + Redis/MySQL/RocketMQ/MinIO）执行静态安全隐患审查：Redis 滥用（KEYS 命令/永久 key/凭据硬编码）、MySQL 事务与 SQL 注入面、索引核对（对照 basic-platform-service-sql 归档）、前后端接口抽查（对照 wukong 前端仓库）、MQ 中间件（RocketMQ/RabbitMQ）及自主扩展角度（上传下载、日志泄漏、依赖停维、越权抽查），产出双格式（Markdown + HTML）审查报告到 .agents/reports/。当用户要求"检查项目安全隐患""安全审查""代码安全扫描""审查 Redis/MySQL/MQ 使用是否不当""核对索引是否缺失"时使用。不适用于：运行时渗透测试（无运行环境探测）、依赖漏洞 CVE 全量比对（需联网 OSV/NVD）、修复代码本身（审查通过后由用户另行安排修复）。
compatibility: 依赖 scripts/check-missing-indexes.py（Python 3.9+ 纯标准库）；索引核对需本地存在 D:/develop/project/basic-platform-service-sql 归档仓库；接口抽查需前端仓库 D:/develop/project/wukong。适用于 BPS 主仓库 release 或 dev 分支基线。
metadata:
  author: AI-Redfish
  version: "1.1.0"
  source: 2026-11-02 安全审查会话沉淀（基线 release@1d2cf4e513，已验证可复现）
---

# BPS 项目安全隐患静态审查

本文是 BPS 项目的安全审查操作流程。何时读：用户要求安全隐患审查、Redis/MySQL/MQ 使用核查或索引缺失核对时。

## 前置条件（开工前核对）

1. 工作区干净（`git status --porcelain` 无输出），有未提交内容先按用户确认处理。
2. 切到用户指定分支并拉最新（通常 release）。报告必须注明基线 commit。
3. 确认两个外部仓库存在：SQL 归档 `D:/develop/project/basic-platform-service-sql`、前端 `D:/develop/project/wukong`。缺失时向用户要路径，不猜测。
4. 大仓库扫描（几千个文件）设置 bash timeout ≥ 180s；grep 排除 `target/`、`test` 目录与测试文件。

## 审查方向与操作要点

按以下 6 个方向顺序执行。命令模式是起点，命中后必须读上下文人工甄别再下结论。

### 1. Redis

- 扫描面：`grep -rl "RedisTemplate|StringRedisTemplate|Redisson"`（约 200+ 文件，只深查命中的模式）。
- 高危模式：`\.keys\(` 生产代码调用（KEYS 阻塞命令）；`flushdb|flushall`；`opsForValue().set(` 两参调用（永久 key，需逐个确认 key 是否有限集合）；先 `set` 后 `expire` 非原子写。
- 凭据扫描：`-iE "(password|secret)\s*=\s*\""`，命中后区分三种：真实凭据默认值（高）、环境变量名常量（无风险）、设备出厂默认密码（中，需确认初始化策略）。
- 误报甄别：key 数量固定有限的注册表类永久 key 风险低；`opsForHash().multiGet` 是批量读不是全量读。

### 2. MySQL / 事务 / SQL

- `@Transactional` 统计：总数 + 无 `rollbackFor` 数量（`grep "@Transactional$" 或 -A1` 无 rollbackFor 的）。默认只回滚 RuntimeException，量 >5% 时列入低风险。
- Mapper XML `${}`：只在 `*Mapper*.xml` 里搜（全仓搜会命中 pom 的 `${xx.version}` 干扰）。三类甄别：
  - 列名拼接（`${orderBy}`/`${inFilterColumn}`）：查 Java 侧是否经 `MyModelUtil.mapToColumnName`/`MyOrderParam.buildOrderBy` 映射，有则已被框架防护（未匹配列抛异常）。
  - IN 值直拼 `'${item}'`：查调用方来源，内部集合（数据权限部门 ID 等）为低风险，前端输入直达为中高危。
  - 条件值 `${}` 直拼：高危。
- 事务内远程调用：`@Transactional` 方法体内出现 Feign/MQ 发送需列出（拉长事务）。粗扫常见误报：类名含 `Client` 的本地服务（如 OAuth Client 管理）不是 Feign，须看 import。

### 3. 索引核对

- 用 `python scripts/check-missing-indexes.py --min-refs 3`（参数：`--sql-repo`、`--backend`、`--libs`、`--min-refs`）。
- 脚本原理：解析归档 `mysql/<lib>/*.sql` 的 CREATE TABLE 内联索引（含 PRIMARY KEY）与 CREATE INDEX/ALTER ADD INDEX，对比后端 Mapper XML WHERE 条件列。
- 输出分两组：「确定疑似」（列在表定义中且无任何索引含它）与「待人工确认」（JOIN 归属不明）。
- 人工复核规则（脚本静态局限）：
  - 主键/唯一键列报出的 → 查归档确认后排除（表定义可能跨多个脚本）。
  - `deleted_flag`、`status` 等低选择性列 → 不建议单独加索引，建议并入高频列组合。
  - 疑似项查 Java 调用频率与真实数据量，最终 EXPLAIN 验证后再走 Flyway 双端幂等流程（见 relational-db-sql-migration skill）。
- 特别注意：建表语句可能漏 PRIMARY KEY（如 comments 表），这是表设计问题，比缺索引严重，单独列报。

### 4. 前后端接口抽查

- 提取前端 URL：`packages-web/api` 与 `apps/*/api` 的 .ts 中字符串字面量；后端：controller 目录 `@.*Mapping` 注解。
- 已知限制：后端大量使用 `@RequestMapping(URL常量)` 无法静态解析，全量对照必然产生 1000+ 假 mismatch，**不可据此下结论**，只做抽查：
  - 挑底层依赖 KEYS 扫描等高危实现的接口（接口层无缓存/节流为风险）。
  - `listAll` 类全量返回接口、前端循环逐条调用（N+1）模式。
  - 上传下载链路：`getOriginalFilename` 落盘、Content-Disposition 编码、扩展名白名单。
- 网关鉴权链路必查：`application/gateway/.../filter/AuthenticationPreFilter` 的白名单与无条件放行逻辑（如 `/v3/api-docs`），代码层放行 + Nacos 未关 springdoc = 生产 API 结构泄漏；报告须标注「待确认」而非定论，因 Nacos 配置本地不可见。

### 5. MQ / 中间件

- 统计消费者：`grep -rl "@RocketMQMessageListener"`；逐个核对四要素：`consumeMode`（ORDERLY 未设 `maxReconsumeTimes` = 脏数据阻塞分区）、`consumerGroup` 命名（应用名粒度过宽 = 同组订阅关系冲突风险）、`messageModel`（BROADCASTING 失败即丢）、消费幂等（抽查监听器是否有去重/唯一约束，发送端无事务消息时幂等责任在消费端）。
- RabbitMQ 面：`RabbitTemplate|@RabbitListener`；`convertAndSend` 计数。
- 正面样本也记录（如重试字段表设计、环境变量注入密码），报告中体现平衡。

### 6. 自主扩展角度（每次都过一遍）

| 角度 | 命中信号 |
|------|---------|
| 硬编码凭据 | 源码默认值含真实密码/内网 IP；设备出厂密码；`.env` 值入代码 |
| 日志敏感信息 | log 打印 password/token/idCard 明文（打 userId/tenantId 属正常） |
| 文件上传下载 | 无扩展名白名单；路径拼接用户输入；Content-Disposition 未编码 |
| SQL 注入 | 见方向 2 |
| XSS | 富文本展示无 escape；网关无全局过滤器时风险可控（JSON API + 前端框架转义） |
| 越权 | Controller 用前端传 userId 直查而不取 `TokenData.current()` |
| 反序列化 | ObjectInputStream/XStream；fastjson 1.x 检查版本（1.2.83 为 1.x 末版，已停维，建议 fastjson2） |
| 依赖停维 | pom 关键组件版本；`pom.xml` 已有版本上界防回退机制则记录为正面 |
| 多租户隔离 | 抽查高频 Mapper 是否带 tenant_id 条件 |
| 监控端点 | Actuator/Druid 暴露配置在 Nacos，本地不可见 → 列入未覆盖项，提示用户自查 |

## 第二、三轮增量审查方向（v1.1 补充）

以下角度均已在真实审查中验证，按批执行时并入扫描清单。

### 7. 并发与事务失效

- **静态可变集合**：正则匹配类级 `static` 非 final 的 Map/List/Set 字段（排除方法内局部与常量字典）。`public static` 可变集合记低风险。
- **线程池无界队列**：`Executors.newFixedThreadPool/newCachedThreadPool`（队列/线程无界，洪峰 OOM）。
- **XXE 逐处甄别**：搜 `DocumentBuilderFactory|SAXParserFactory|XMLInputFactory|SAXReader`，逐个确认是否禁 DTD/外部实体；重点查**解析用户上传文件内容**的场景（xlsx 本质 zip，内部 XML 攻击者可控）。仓内正确写法可照搬：`IS_SUPPORTING_EXTERNAL_ENTITIES=false` + `SUPPORT_DTD=false`。
- **动态代码执行面**：`GroovyShell|GroovyClassLoader|SpelExpressionParser + StandardEvaluationContext`；Groovy 零调用方也列报（预留 RCE 能力）；SpEL 需确认表达式来自注解常量还是用户输入。
- **命令注入/autoType**：`Runtime.exec|ProcessBuilder`、`autoTypeSupport|addAccept`。
- **事务失效精确检测**：直接复跑 `python scripts/check-transaction-failures.py`（参数 `--repo`）。方法级解析（提取方法块 + @Transactional 状态），报告两类：非 public 事务方法（Spring 代理只对 public 生效，注解静默忽略）；非事务方法内自调用事务方法（绕过代理）。
  - **误报教训**：正则必须排除控制流关键字（if/for/while/switch/catch 被误识别为方法名）、排除 `@TransactionalEventListener` 等事件注解、排除事务方法间互调（彼此在事务中不失效）。粗正则误报 878 处，精确解析后 29 处。
  - 高发模式：`protected/private @Transactional` + 循环单条写入（批量推送/通知处理场景）。
- **@Scheduled 分布式锁**：统计 `@Scheduled` 方法总数与入口无锁数；多实例部署才成立，定级标注条件性。

### 8. WebSocket 鉴权链路

- 双层结构甄别：握手拦截器无条件 `return true` 不代表漏洞——确认 handler 层（`afterConnectionEstablished`）是否 userId 兜底拒绝。
- 检查点：公开通道与认证通道是否共用 handler；`setAllowedOriginPatterns` 是否通配（CSWSH 面）；token 是否走 URL 参数（进日志/历史）。

### 9. SQL 深度与配置

- **SQL 写法统计**（statement 级解析）：直接复跑 `python scripts/check-sql-patterns.py`（参数 `--repo`），输出 LIMIT 无 ORDER BY / 深分页 / SELECT * / 前导 LIKE 四类清单。LIMIT 无 ORDER BY（byId 场景无害，列表场景结果不稳定）；前导 % LIKE（全局搜索，索引失效已知代价）；SELECT *（关注 longtext 大字段表）。
- **分页上限**：`PaginationInnerInterceptor.setMaxLimit` 是否设 -1；`MyPageParam.DEFAULT_MAX_SIZE` 值；部分模块自定义上限属正面。
- **登录防爆破**：`isRequestRateLimited`/`isVerificationLocked` 是否覆盖登录/验证码/租户查询。
- **上传/解压防护确认点**：Zip 条目数与解压总量上限；文件头 magic number 校验；Excel 导出公式注入转义（前导单引号）。
- **dev 配置入库**：config-data/nacos 样例目录弱凭据（admin/admin123456、123456 类）；生产沿用则升级。
- **构建配置凭据**：pom profiles 中的 Nacos/中间件密码与生产 IP/namespace——凭据明文入库与生产拓扑泄漏都算高险候选。
- **主框架版本**：spring-boot/spring-cloud/mysql-connector/netty 新鲜度。

### 10. 误报甄别总规则（三轮验证）

1. `${}` 全仓搜索先排除 pom/logback（pom version 占位干扰）。
2. Mapper 动态参数名（orderby/infiltercolumn/infiltervalues/item）不是真实列名，用表列定义校验。
3. 主键列必须单独提取 PRIMARY KEY 比对，否则主键误报缺索引。
4. 类名含 Client 的本地服务（OAuth Client）不是 Feign，看 import 判断。
5. 脚本自动结论必须抽查 3-5 项到归档/源码原文人工复核后才写入报告。

## 报告输出规范

- 位置：`.agents/reports/security-review-<YYYY-MM-DD>.md` 与同名 `.html`，内容一致（用户已确认此约定）；同日复查产出新文件加 `-r2`/`-rN` 后缀，不覆盖既有报告。
- 结构：元信息（基线 commit、方式）→ 风险总览表（编号 H/M/L + 位置精确到文件:行）→ 分方向详述（每项：证据代码、影响、建议）→ 正面样本 → 修复优先级（立即/短期/中期）→ 覆盖范围与未覆盖项。
- 分级标准：高=可远程利用或凭据泄漏；中=性能劣化/防御缺失/停维组件；低=规范偏差/触发条件苛刻。
- 未覆盖项必须如实列（Nacos 实际配置、运行时实测、全量契约比对等），不确定性明说，不编造。
- HTML 自包含样式（内联 CSS），风险标签用色块（高红/中黄/低蓝/正面绿）。

### 复查与修复交付模式（v1.3 补充）

- 触发：用户要求「重新审查 / 出修复版报告」且基线 commit 与既有报告一致时，不重跑全量扫描；对高风险与关键发现逐点 grep 复核原位置（含 SQL 归档建表块尾部确认主键），其余项沿用既有结论，并在报告「复核说明」标注实际复核范围。
- 修复交付格式（用户已确认）：每个审查点独立小节，固定三段标签 `**问题原因**` / `**影响**` / `**修复建议**`，保留一行一项的风险总览表，文件名 `security-review-<YYYY-MM-DD>-r2.md/.html`。
- 脚本位置：`check-missing-indexes.py`、`check-sql-patterns.py`、`check-transaction-failures.py` 在工作区根目录 `scripts/`（非本 skill 目录）。
- 交付拆分：密码轮换、Nacos 配置、EXPLAIN 实测、部署实例数确认等运维动作单列「需运维配合」清单，不混入代码修复项。

## 验证与交付

1. 脚本结论抽查 3-5 项到 SQL 归档原文核对（主键、现有索引），确认无误报后才写入报告。
2. 报告写完后复跑脚本确认可复现。
3. 交付只列变更文件、核心发现摘要、未覆盖项与风险，不粘贴报告全文。

## 已知边界

- 纯静态审查：不能替代渗透测试、运行时 Redis `--bigkeys`/`INFO memory` 实测、生产 EXPLAIN。
- 前后端全量接口对照受路径常量限制不可行，只做抽查。
- Nacos 配置中心实际生效值不在本仓库，相关结论一律标「待确认」。
