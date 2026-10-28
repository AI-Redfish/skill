# MyBatis-Plus 使用与 CRUD 生成约束（吸收 bps-crud-code-generator + 会话 Mapper 最小化经验）

## 1. Mapper 最小化决策（会话实战，优先级从高到低）

1. **单表/同表查询**：MP 内置 `selectList/selectOne/selectCount` + `LambdaQueryWrapper`；行锁加 `.last("FOR UPDATE")`（先在库内 `git grep 'last("FOR UPDATE")'` 查先例，energy 模块有）。
2. **跨域单表查询**：复用目标域**既有** Mapper 的 MP 内置查询（如 `SysAssertInfoMapper`、`AssetArchiveMapper`、`AssetDeviceTagMapper`）；注入前确认目标 Mapper 无干扰类级注解（`@EnableCampusDataPerm`/`@DisableTenantFilter` 的 include/exclude 列表）。
3. **跨域 Lambda 单测**：纯单测无 MP 启动流程，需 `TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), X.class)` 逐实体初始化 lambda 缓存，否则报 `can not find lambda cache`。
4. **多表 JOIN/EXISTS/NOT EXISTS/聚合**：MP 无法等价表达时才新增 XML；能拆成"单表分页扫描 + 逐页内存过滤"的优先拆（性能与可测性更好）。
5. **被替代即删除**：自定义方法被 MP 替代后，接口方法、XML statement、辅助片段（`<sql id>`）、`@TableField(exist=false)` 字段、相关测试全部同步清理，`git grep` 确认零残留。

## 2. 常用工具 API 速查（直接套用，不要临时发明等价写法）

```java
// 对象转换（禁 BeanUtil.copyProperties）
XxxYyy model = MyModelUtil.copyTo(dto, XxxYyy.class);
XxxYyyVo vo = MyModelUtil.copyTo(model, XxxYyyVo.class);
MyModelUtil.fillCommonsForInsert(model);                  // createUserId/createTime/updateUserId/updateTime
MyModelUtil.fillCommonsForUpdate(model, originalModel);

// 主键生成
@Autowired private IdGeneratorWrapper idGenerator;
String id = idGenerator.nextStringId();

// 分页（Controller）
PageMethod.startPage(pageParam.getPageNum(), pageParam.getPageSize());
List<XxxYyy> list = service.getXxxYyyList(filter, orderBy);
return ResponseResult.success(MyPageUtil.makeResponseData(list));

// 用户上下文
TokenData tokenData = TokenData.takeFromRequest();
Long tenantId = tokenData.getTenantId();

// DTO 校验（false=新增，true=更新）
String err = MyCommonUtil.getModelValidationError(dto, false);
if (err != null) return ResponseResult.error(ErrorCodeEnum.DATA_VALIDATED_FAILED, err);

// 模糊搜索防通配符注入（Model 内 override）
public void setSearchString(String searchString) {
    this.searchString = MyCommonUtil.replaceSqlWildcard(searchString);
}
```

`@MyRequestBody` vs `@RequestBody`：CRUD 端点（add/update/delete/deleteBatch/list/export）用 `@MyRequestBody`；RPC 端点（listBy/listByIds/countBy/notExist/saveNewOrUpdate）用 `@RequestBody`；view(GET) 用 `@RequestParam`/`@PathVariable`。

## 3. CRUD 全套生成（细节按 `<仓库>/.share/skills/bps-crud-code-generator/SKILL.md` 模板 1-10）

生成前必须确认：实体名、中文名、模块名、表名、主键列、路径前缀（plan 用 `api` 其余 `admin`）、字段列表（名称/类型/列名/jdbcType/必填/描述）、是否 Feign。

输出顺序：DTO → VO → Model → Mapper 接口 → Mapper XML → Service 接口 → Service 实现 → Controller → Feign（可选）→ 建表 SQL（MySQL + KingBase 双份）。

生成后必须执行架构合规检查（`check-architecture.sh --diff`）。

## 4. 实战注意事项（会话踩坑）

- 单测 mock MP 查询时，`when(mapper.selectList(any()))` 的验证范围要与实现一致：还原/重构成 MP 查询后，旧的"验证某自定义方法被调用"断言必须同步重写。
- 验证 wrapper 行为可用 `configuration.getMappedStatement(id, false).getBoundSql(params)` 做 SQL 解析级断言：动态 `<if>` 是否生效、`<foreach>` 参数名（`__frch_xxx_0` 形式，用 contains 匹配）、枚举 OGNL 常量是否正确渲染。
- 删除实体字段/方法后，全仓 `git grep` 确认引用清零（含测试与文档）。

## 5. 新增/变更字段全链路清单（历史踩坑：XML 自定义查询漏字段）

新增/修改表字段时，**先盘后改、逐项打勾**。全链路大量环节是"静默丢字段"：`MyModelUtil.copyTo` 按同名拷贝、XML 不校验列名、MP 内置查询按实体映射——漏改任何一层编译都不报错，只能靠清单逐项核对 + `git grep` 复查，禁止凭记忆改完即止。

### 5.1 动手前先盘点（形成文件清单）

```bash
git grep -l <EntityName> -- '*.java'      # 实体被哪些类引用（DTO/VO/Service/XML 等）
git grep -l <table_name>   -- '*.xml'     # 哪些 Mapper XML 涉及该表
git grep -l <table_name>   -- '*.sql'     # 既有迁移/初始化脚本
```

列出涉及文件清单后再动手；改完用清单反向核对 `git diff --stat`，无计划外文件。

### 5.2 逐层核对清单（按序执行，每项显式判断，禁止跳项）

| 层 | 要点 |
|---|---|
| Flyway | 双端幂等加列（`add_column_if_not_exists`，MySQL+KingBase 同版本前缀同序号）；存量数据回填口径先向用户确认 |
| Entity/Model | 加字段 + `@TableField("列名")`（驼峰与列名不一致时必须）+ Javadoc 注释 |
| DTO | 新增/更新 DTO 加字段 + 校验注解；`getModelValidationError` 的必填口径同步 |
| VO | 需要返回前端才加；**加了实体字段但 VO 漏加 = 返回值静默丢字段，无任何报错** |
| Mapper 接口 | MP 内置查询通常零改动；自定义方法签名/返回 DTO/`@Param` 逐一核对 |
| Mapper XML | **最易遗漏层，逐 statement 判断**，见 5.3 |
| Service | 转换逻辑（同名自动拷贝，**字段名不同必须手动补映射**）；查询过滤参数透传；导出/组装/同步逻辑 |
| Controller | `@MyRequestBody` 新参数；导出表头/列；接口文档与请求示例 |
| 测试 | SQL 解析级断言补新字段断言；受影响单测的 stub/期望值同步 |
| 文档 | 接口文档、交接文档同步字段说明 |

### 5.3 Mapper XML 逐 statement 判断（核心动作）

打开该表相关的**每一个** XML，对每个 statement/片段问一遍"新字段要不要进这里"，结论只有两种：**补上** 或 **跳过并在交付总结写明理由**（列"已核对跳过"清单），禁止无判断默认跳过：

| XML 位置 | 判断口径 |
|---|---|
| `resultMap` | 列→属性映射；返回实体/DO 的查询必补，漏补 = 查询结果静默丢值 |
| `<sql id>` 基础列片段 | 被多处 include 的列清单，通常必补 |
| select 显式列清单 / JOIN 别名列 | 普通查询通常必补；统计/EXISTS 类按业务判断 |
| insert（列清单 + values） | 可写列必补，漏补 = 新增时静默丢数据且无报错 |
| update set 片段 / 动态 `<if>` | 可更新列按业务判断必补 |
| where 动态条件 `<if>` | 该字段是否要支持查询过滤，按需求判断 |
| 聚合/子查询/EXISTS | 多数不需要；跳过时记录理由 |

### 5.4 改完后复查（两项都过才算完成）

```bash
git grep -n <newFieldName>    -- '*.java' '*.xml'   # 命中文件数与 5.1 清单一致
git grep -n <new_column_name> -- '*.xml' '*.sql'   # XML 与双端 Flyway SQL 均覆盖
```

复查不一致时回到 5.2 清单找漏项；确认每个未命中文件是"判断为不需要"而非遗漏。
