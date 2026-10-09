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
