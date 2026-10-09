# 质量门禁与 Diff 自检（吸收 bps-ci-quality-gates + bps-review + 会话实测）

## 1. 本地预检命令

```bash
# 快速预检（dev 门禁）：全仓编译 + 6 项架构规则
bash scripts/review/local-review.sh --fast

# 严格预检（release/main 门禁）：+ Checkstyle + SpotBugs
bash scripts/review/local-review.sh --strict

# 增量架构检查（仅扫描变更文件；可指定基线）
bash scripts/ci/check-architecture.sh --diff
ARCH_GATE_BASE_REF=origin/release bash scripts/ci/check-architecture.sh --diff
```

修复门禁时的自检顺序：先定位 CI 输出的具体规则和文件行，不扩大重构范围 → 按下表修复 → 改完先跑 `--diff`，发布前跑全量。

## 2. 12 条核心禁令速查（★ = check-architecture.sh 自动扫描，CI 直接挂）

| # | 禁止 | 正确做法 | 扫描 |
|---|------|---------|:----:|
| 1 | `BeanUtil.copyProperties()` | `MyModelUtil.copyTo(source, Target.class)` | ★ |
| 2 | Controller 直接依赖 DAO/Mapper/`LambdaQueryWrapper`/`QueryWrapper`/`UpdateWrapper`/`baseMapper` | 通过 Service 间接访问 | ★ |
| 3 | `@Transactional` catch 后吞异常 | 重抛异常或显式 `setRollbackOnly()` | ★ |
| 4 | Mapper 接口写 `@Select/@Insert/@Update/@Delete` | 复杂 SQL 放 `*Mapper.xml` | ★ |
| 5 | XML 用 `IFNULL/IF(...)/GROUP_CONCAT/NVL` | `COALESCE` / `CASE WHEN` / Java 聚合 | ★ |
| 6 | Controller 写业务逻辑 | 只做 校验→转换→调 Service→封装 ResponseResult | review |
| 7 | CRUD 端点用 `@RequestBody` | `@MyRequestBody`（RPC 端点才用 `@RequestBody`；view GET 用 `@RequestParam`） | review |
| 8 | Mapper 返回 `Map<String, Object>` | 返回明确 DO/Model/VO | review |
| 9 | 低层 `common/*` 依赖 `application/*` | 只向下依赖；遗留依赖登记 `scripts/ci/layer-dep-whitelist.txt`（限时技术债+治理方向，季度清零） | ★ |
| 10 | 循环逐行查库 | 批量 API（inList）+ 内存组装 | review |
| 11 | 行内全限定类名 | import | Checkstyle |
| 12 | 空 placeholder 实现/测试 | 补齐实际逻辑或 `UnsupportedOperationException` 附因 | review |

## 3. Review 额外对照（CI 扫不到的平台约定）

- 注解顺序：Controller 类 `@Tag → @Slf4j → @RestController → @RequestMapping`；方法 `@SaCheckPermission → @OperationLog → @Operation → @PostMapping`；Service 实现 `@Slf4j → @Service("xxxService")`。
- 包命名：DTO `com.sinomis.{module}api.dto`、VO `.vo`、Feign `.client`、Model `common.{module}.model`、Mapper `.dao`、XML `.dao.mapper`、Service `.service`/`.impl`、Controller `{module}service.controller`。
- Javadoc：Controller/Service/ServiceImpl/Model/DTO/VO/Mapper 类级别必须有（描述+`@author`+`@date`）；所有端点 `@Operation(summary="中文")`；private 辅助方法需 Javadoc。
- 循环依赖专项（MR 人工必查）：禁新增 `service -> service` 编译期依赖、`AServiceImpl <-> BServiceImpl` 双向依赖、`XxxServiceImpl` 自注入、`Helper/Util -> Service` 反向依赖；`@Lazy`/`allow-circular-references` 只能作为过渡。治理优先级：P0 真实多 Bean 环 > P1 双向 Service > P2 @Lazy 打断环 > P3 自注入。重构手法：Facade / Orchestrator / 单写入口关系服务。

## 4. Diff 自检（Surgical Changes，吸收 Karpathy 准则 + bps-review 原则)

| 风险 | 自检问题 |
| --- | --- |
| 无关重构 | 是否改了需求外的命名、格式、目录结构 |
| 隐式行为变化 | 是否改变了老接口、老状态、老数据查询范围（例：给台账列表加状态过滤属于隐式收窄数据范围） |
| 过度抽象 | 是否新增了当前只有一个调用方的复杂框架 |
| 调试残留 | 是否留下日志、临时开关、演示数据、placeholder |
| 脏工作区 | 是否混入用户或生成工具已有改动 |

Review 原则（来自 bps-review，自查与互查通用）：只审查本次变更引入的问题；少猜测多给触发场景（什么输入/状态/并发下触发）；按严重度排序（安全/正确性 > 生产故障/契约破坏 > 性能退化 > 测试缺口/可维护性）；输出指向具体文件和行、可执行。

安全 diff 搜索（命中逐条确认，不一定是问题）：

```bash
rg -n "@SaIgnore|@SaCheckPermission|TokenData|tenantId|PasswordEncoder|secret|password|验证码|身份证" <changed-files>
rg -n "\$\{|ORDER BY \$|System\.out|printStackTrace|TODO|FIXME" <changed-files>
```

## 5. MR 提交人自检清单

- [ ] 分支策略正确（feature/bugfix/hotfix），目标分支正确
- [ ] 已跑 `local-review.sh --fast`（或至少增量架构检查）
- [ ] Controller 无业务逻辑、无直接 DAO/Mapper/Wrapper
- [ ] 无 `BeanUtil.copyProperties`；`@Transactional` catch 未吞异常
- [ ] 无重复 `@Autowired`/重复 bean 注入；Mapper 无 SQL 注解；SQL 无方言函数
- [ ] 无新增 `service -> service`、双向注入、自注入、`Helper/Util -> Service`
- [ ] Javadoc + `@Operation` 完整
- [ ] SQL 变更已走 Flyway 双端
