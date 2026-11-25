# 测试与验证（会话实战沉淀 + 吸收 bps-pretest-e2e 要点）

## 1. 验证为实 + 用户 Markdown 用例全量回归（强制）

### 1.1 基础验证原则

- 只声称真实执行过的验证；构建/测试/架构检查命令与结果如实记录。
- 改动后匹配验证：`mvn -o -pl <模块> -am test -Dtest=<TestName1,TestName2> -Dsurefire.failIfNoSpecifiedTests=false`。
- 验证失败逐个修复；禁止跳过测试、放宽断言、删除用例来"让测试通过"。

### 1.2 用例目录准入门禁

- 每个 coding 开发任务开始前，必须向用户取得其提供的**测试用例目录路径**；目录内用例文件为 Markdown（`.md`）。即使已有单元测试/CI，也不能替代这套验收用例。
- 路径未提供、不可访问、目录没有 `.md` 文件、或用例依赖/步骤/预期不清，必须暂停编码并一次询问缺失信息；不得自行假设路径、从别处挑用例、或编造用例冒充用户验收集。
- 用户明确确认“本次没有/不适用”时，记录确认内容与原因，可不跑用户用例；除此情况不允许绕过门禁。路径可在当前项目持续复用，但需确认仍对应当前需求/版本，不能默认沿用过期目录。
- 开跑前递归枚举目录内所有 `.md` 文件，记录相对路径、用例标题/编号；全量指该目录中所有与当前系统/功能相关的用例，而不是仅选本次改动关联的用例。发现明显无关的用例也要记录为“不适用+理由”，不能静默略过。

### 1.3 用例执行与缺陷归因

- 忠实按 Markdown 中的前置条件、步骤、数据、预期结果执行；未写清的部分先问用户或在执行记录中标“无法判定”，不可臆造预期。
- 执行顺序：确认测试环境/数据/账号/权限 → 记录初始状态 → 按用例执行 → 保存可复核证据（命令/日志/截图/响应/记录标识，避免记录 token、密码、密钥等敏感值）。有副作用的用例先确认授权、测试数据隔离与清理方式；禁止未经确认在生产环境造数/删数/发消息。
- 每个用例单独记录状态：`PASS`、`FAIL-本次改动`、`FAIL-既有问题`、`BLOCKED`、`N/A（理由）`，并附实际结果和证据位置。仅 `PASS` 算通过；BLOCKED/N/A 不得计入通过数。
- 失败必须先做因果归因，不能因为失败出现在本次开发后就直接判为本次引入。依据改动 diff、基线/复现对比、日志/请求响应和调用链，记录判断理由；证据不足时标“归因未定”，不能擅自归为既有问题。
- **归因为本次改动导致**：修复实现（不得改弱/删掉用户用例），重跑失败用例，并在修复后重新跑该 Markdown 目录全量回归，直到本次引入的失败清零且可执行用例通过。
- **归因为既有且与本次改动无关**：不扩大范围擅自修改；保留复现步骤、预期/实际、证据、影响与建议，最终单独汇总给用户。若既有失败可能受本次改动影响或证据不足，先继续调查，未判清前报告“未决”，不能结案为既有问题。
- 环境/权限/数据缺失导致无法执行：标 BLOCKED，说明解除条件；不得伪造结果。全量完成指所有枚举用例均有结果（PASS / 有依据的既有 FAIL / 明确 N/A / BLOCKED），不允许遗漏未登记文件；有 BLOCKED 或归因未定时明确交付受限，不得称“全部测试通过”。

### 1.4 全量回归报告

每次开发完成后，至少汇总：

| 项目 | 数量/结果 |
|---|---|
| 用例目录 | 用户提供的实际路径 |
| Markdown 文件 | 枚举总数；N/A 文件及理由 |
| 用例 | PASS / 本次改动失败并修复 / 既有问题 / BLOCKED / 归因未定 |
| 证据 | 执行记录或 `.agents/out/coding/` 报告路径 |
| 结论 | 本次改动导致的失败是否清零；既有问题和未执行项 |

可将详细逐例记录放在 `<仓库>/.agents/out/coding/test-reports/<需求短名>-regression.md`（本地非 Git 产物）；报告记录日期/代码版本、用例源路径、执行环境、每例结果/证据、失败归因与修复重跑轮次。汇报中区分“本次改动回归通过”与“整套用例全部通过”，不得混为一谈。

## 2. 单测实战坑（会话实测，按现象查表）

| 现象 | 原因与处理 |
|---|---|
| `can not find lambda cache for this entity [X]` | 纯单测无 MP 启动流程；`@BeforeEach` 中 `TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), X.class)` 逐实体初始化（新增跨域实体查询时同步补充） |
| 测试报告显示通过但时间戳早于改动 | 报告过期：模块未真正执行或并发构建覆盖；`stat` 核对时间戳，串行重跑 |
| 两个 Maven 进程写同一 target/log | 并发构建互相覆盖日志，掩盖真实结果；等待结束串行执行 |
| `mvn -pl` 构建了错误模块集 | 用 sed 拼改命令易踩分隔符坑（`/` 分隔符撞上路径）；改完 `grep` 确认实际命令，必要时整文件重写 |
| 新测试文件不在 `git status` | 仓库 `.gitignore` 忽略 `**/src/test/**`；按既有格式加白名单（`!path/to/XxxTest.java`）并 `git check-ignore` 复查；**改名后必须复查白名单** |
| 单测出现 `InvalidUseOfMatchersException` | 前一个 stub 因 NPE 中断导致 matcher 悬挂；先修 NPE 根因 |
| mock 严格校验失败（NoInteractionsWanted） | verify 范围与实现职责一致；还原方法职责后，同步删除针对旧行为的过时用例与失效 stub |

## 3. SQL 解析级测试（Mapper XML 变更必配）

用 MyBatis `Configuration` 实际解析 XML 并断言生成 SQL：

```java
Configuration configuration = new Configuration();
new XMLMapperBuilder(input, configuration, resource, configuration.getSqlFragments()).parse();
BoundSql sql = configuration.getMappedStatement(NAMESPACE + "queryId", false).getBoundSql(params);
sql.getSql()                  // 断言动态片段、排除条件、删除标记
sql.getParameterMappings()    // 断言参数绑定（foreach 参数名为 __frch_item_0 形式，用 contains 匹配）
```

注意：`getSql()` 中 `#{}` 已替换为 `?`，参数断言走 `getParameterMappings()`；只加载被测语句所在 XML，避免断言其他模块 Mapper 的外部 include（用 `getMappedStatement(id, false)`）。

## 4. 接口/接口上下文（联调与 E2E 要点，吸收 bps-pretest-e2e）

影响权限过滤的请求头必须保留，缺失会导致权限口径不真实：

1. `Authorization`：登录 token。
2. `MenuId`：菜单数据权限按该值读取；缺失可能 `NoDataPermException`。
3. `operation-terminal` / `Operation-Terminal`：PC/移动/客户端入口，使用范围过滤据此归一。
4. `X-Campus-Id`：当前院区（多个逗号分隔）。
5. `MY_ORIGINAL_REQUEST_URL` / `CurrentRouter`：菜单与 URL 匹配、路由上下文。

只带 token 的请求只能算诊断证据，不能声明权限相关测试通过。

## 5. 多模块本地构建与界面联调交付（2026-11-12 电梯监测实测）

**单模块构建与测试**：

1. 单模块编译需带依赖：`mvn package -pl <module> -am`；仅 `-pl` 不带 `-am` 会因依赖模块未 install 而报 `NoClassDefFound`/找不到符号。
2. 依赖模块的既有失败测试不阻塞主线：`mvn install -pl <目标模块> -am -DskipTests` 装库后，对目标模块单独 `surefire:test -Dtest=<测试类>`。
3. 可执行 jar 是 `*-boot.jar`（普通 jar 无主清单属性）；运行中的服务会锁定 jar（repackage 报 `Unable to rename`），先停服务再打包；打包后核对文件时间戳/内容（repackage 可能静默未更新，用 `unzip -p ... | grep <新方法名>` 验证新代码真的进包了）。
4. 日志级别命令行参数可能被 nacos 覆盖或 logger 名不匹配，DEBUG 不打日志不代表方法没执行；改用 Redis MONITOR / 抓包实证调用链路。

**界面联调交付**（给用户可点链接 + 界面可见数据）：

1. 链路：前端 vite dev（`.env.development.local` 覆盖 proxy target，gitignore 内不提交）→ 本地 gateway → 本地业务服务 → 共享中间件；gateway 真实端口以实际监听为准（配置假设可能不成立）。
2. 自测 token 从 Redis sa-token 键（`Authorization:login:token:{uuid}`）提取；非本人账号可能触发 `NoDataPermException`（如 `SysSpaceInfoMapper` 数据权限拦截，局部降级 success=true 但值为空），诊断前先排除。
3. 界面造数键名/值格式必须 Redis MONITOR 实证，细节见 fulllink-testing skill 的 `references/frontend-e2e-verification.md`。

## 6. 断言分级与数据红线

- L0（HTTP 200/页面可打开）不算通过；断言必须到字段/行数/业务结果。
- 测试输入与预期值运行时从目标环境现查，禁止写死 ID/SN；长整型 ID 按字符串处理。
- 造数/发消息类写操作自带清理逻辑，或在报告登记清理项；测试数据带可识别标记。
- 测试期间业务仓库只读：发现缺陷记录而不修代码；执行前后对比仓库状态。
- token/密码/密钥不进日志、报告、缓存与仓库。
