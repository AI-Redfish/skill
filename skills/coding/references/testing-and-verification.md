# 测试与验证（会话实战沉淀 + 吸收 bps-pretest-e2e 要点）

## 1. 验证为实（原则）

- 只声称真实执行过的验证；构建/测试/架构检查命令与结果如实记录。
- 改动后匹配验证：`mvn -o -pl <模块> -am test -Dtest=<TestName1,TestName2> -Dsurefire.failIfNoSpecifiedTests=false`。
- 验证失败逐个修复；禁止跳过测试、放宽断言、删除用例来"让测试通过"。

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

## 5. 断言分级与数据红线

- L0（HTTP 200/页面可打开）不算通过；断言必须到字段/行数/业务结果。
- 测试输入与预期值运行时从目标环境现查，禁止写死 ID/SN；长整型 ID 按字符串处理。
- 造数/发消息类写操作自带清理逻辑，或在报告登记清理项；测试数据带可识别标记。
- 测试期间业务仓库只读：发现缺陷记录而不修代码；执行前后对比仓库状态。
- token/密码/密钥不进日志、报告、缓存与仓库。
