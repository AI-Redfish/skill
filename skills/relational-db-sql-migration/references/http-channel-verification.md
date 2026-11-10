# HTTP 通道实测回滚（本机无 mysql/ksql CLI 时）

> 内容：经 AgentR 开发工具 HTTP query 接口完成「SQL 实测回滚闭环」的操作路径与记录格式。
> 何时读：SQL 语法实测前发现本机无 `mysql`/`ksql` 客户端时。
> 适用范围：本机运行 AgentR 开发工具（nginx 网关，默认 `http://localhost:8319`）的环境。来源：2026-11-10 实测验证。

**接口**

- 列出已保存连接：`GET /api/node/dev-tools/mysql/connections`、`GET /api/node/dev-tools/kingbase/connections`；按连接名称取 `connectionId`，不写死。密码只存在于接口返回与工具配置中，不落盘、不入日志。
- 连通性：`POST /api/node/dev-tools/{mysql|kingbase}/test`，body `{"connectionId"}`。
- 执行 SQL：`POST /api/node/dev-tools/{mysql|kingbase}/query`，body `{"connectionId","database","sql","maxRows"}`。无参数多语句脚本一次提交即可：MySQL 服务端按 `DELIMITER` 指令分句（可整文件直提）；Kingbase 无参数走 simple query，原生支持多语句。

**MySQL：沙箱库方案（DDL 适用）**

1. 占用检查：`SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE '%\\_\\_sqlcheck'`，已占用则换名并说明。
2. 建沙箱并克隆结构：`CREATE DATABASE <db>__sqlcheck; CREATE TABLE <db>__sqlcheck.<table> LIKE <db>.<table>;`（`LIKE` 复制含注释的完整列结构，覆盖「字段已存在」分支）。
3. 以 `database=<db>__sqlcheck` 整文件执行迁移（文件内不得含 `USE` 切库语句，防止改到真实库）。
4. 核验 `information_schema.COLUMNS`（类型/可空/注释），整文件重跑一遍验证幂等后再次核验。
5. `DROP DATABASE <db>__sqlcheck;`，复查 `information_schema.SCHEMATA` 计数归零。

**Kingbase：事务回滚 + 影子 schema 方案**

1. 整文件验证：一次 query 提交 `BEGIN;\n<文件全文>\nROLLBACK;`；目标表在当前 search_path 缺失时文件 CALL 走 no-op，仅验证函数创建与执行链路。
2. ALTER 路径补测：同一事务内 `CREATE SCHEMA sqlcheck_tmp` → 建影子表并写入与生产一致的注释 → 手动调用迁移内的辅助函数（`'<schema>','<table>','<col>',<type>`）→ SELECT 核验 → `ROLLBACK`。
3. 列长度核验坑：Kingbase 的 `information_schema.columns.character_maximum_length` 对 varchar 可能显示 `-1`，不代表未生效；以 `pg_attribute.atttypmod`（`varchar(n)` 为 `n+4`）或 `format_type(atttypid, atttypmod)` 实证（显示 `character varying(n char)`）。
4. 回滚核验：`pg_proc` 中辅助函数计数、`pg_namespace` 中影子 schema 计数均应为 0；`ALTER COLUMN ... TYPE varchar(n)` 扩容保留注释、默认值与可空性。

**实测记录格式（汇报模板）**

| 项 | 记录内容 |
| :-- | :-- |
| 执行环境 | 连接名 + 引擎/服务端版本（不含凭据） |
| 执行轮次 | 首跑、二跑幂等各自结果与语句条数 |
| 核验结果 | 列类型实证（atttypmod/format_type）、注释与可空性 |
| 回滚方式 | 事务回滚 / 沙箱删除 / 快照恢复 |
| 回滚核验 | 残留对象计数 = 0 的实证查询与输出 |

任一环节失败即停止交付：语法报错按首个报错行修复后重建沙箱/新开事务重跑；回滚核验不一致必须如实报告并恢复，不得隐瞒。
