# 数据库变更（Flyway）（吸收 bps-flyway-migration）

> 权威来源：仓库 `CODING_STANDARDS.md` Flyway 章节 与 `.share/skills/bps-flyway-migration/SKILL.md`。本文件为编码时速查。

## 1. 文件命名（sequence 递增，非秒数递增）

```
V{YYYY.MM.DD.HH.MM.SS}_{product_version}.{sequence}__{db}_{ops_type}.sql
```

示例：`V2026.09.04.00.00.00_6.0.7.3.1__basic_platform_ops_modify.sql`

分配规则：

1. 先扫描目标 SQL 目录中**当前产品版本**已有迁移文件（含本地待提交），不要按当前日期生成前缀。
2. 复用该版本已有的时间前缀，取最大序号 +1（`.9` 后为 `.10`，按数值比较）。
3. 同一迁移的 MySQL / KingBase 对应文件使用相同版本前缀和序号。
4. 合入前重新检查目标分支同版本文件，处理并行开发序号冲突；不得重命名已部署历史迁移。

## 2. 存放路径

| 服务 | 数据库 | 目录 | Schema |
|------|--------|------|--------|
| gateway | MySQL | `application/gateway/src/main/resources/db/mysql/` | `basic_platform_ops` |
| gateway | KingBase | `application/gateway/src/main/resources/db/kingbase/` | `basic_platform_ops` |
| tenant-admin | MySQL | `application-tenant/tenant-admin/src/main/resources/db/mysql/` | `basic_platform_mgr` |
| tenant-admin | KingBase | `application-tenant/tenant-admin/src/main/resources/db/kingbase/` | `basic_platform_mgr` |

`zz-resource/database-init/` 仅本地初始化参考，不受 Flyway 管理，勿放迁移文件。

## 3. 五种幂等模板（每个文件可重复执行，结果一致）

1. **建表**：`CREATE TABLE IF NOT EXISTS ... ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='...'`
2. **加字段**：通用存储过程 `add_column_if_not_exists`（查 information_schema 后 PREPARE EXECUTE），同文件可多次 CALL。
3. **加主键**：通用存储过程 `SafeAddPrimaryKey`。
4. **初始化/更新数据**：`REPLACE INTO`（按主键/唯一索引判存在）。
5. **存储过程/函数**：`DROP PROCEDURE IF EXISTS` + `CREATE PROCEDURE` + `DELIMITER $$`。

## 4. SQL 语法规范

- 列定义顺序：`类型 → CHARACTER SET → COLLATE → DEFAULT → COMMENT`，不可颠倒。
- `USE` 大写并反引号包裹库名：`` USE `basic_platform_ops`; ``。
- 跨库兼容（会被架构检查扫描）：禁 `IFNULL/NVL`（用 `COALESCE`）、禁 `IF()`（用 `CASE WHEN`）、禁 `GROUP_CONCAT`（Java 层聚合）、子查询禁 `LIMIT offset,count`（PageHelper）。

## 5. 严格禁止

- `DROP TABLE`（除非单独审批清理废弃表）、`DROP COLUMN`（废弃字段保留，业务层屏蔽）。
- 迁移文件操作所属数据源之外的 schema。
- 修改已部署到测试/生产环境的 SQL 文件内容。
- 直接向 `dev`/`master`/`release/*` push。

## 6. 调试流程

双端同时生成对齐的两份文件 → 本地启动 gateway/tenant-admin 验证自动执行（可删 `flyway_schema_history` 对应记录重跑，仅限开发环境）→ MR 合入时复查同版本序号冲突。
