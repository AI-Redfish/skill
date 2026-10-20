# relational-db-sql-migration

为 basic-platform-service-sql 归档仓库（`<engine>/<database>/` 多引擎 Flyway 目录）服务的 SQL 技能，面向**所有关系型数据库**；当前已落地引擎为 **MySQL 与 Kingbase**，其他关系型库（PostgreSQL、OpenGauss 等）按「扩展新引擎」指引接入。

1. **跨引擎迁移**：按幂等模板（新增/修改字段、新增索引）生成各引擎可重复执行的迁移；源引擎专属语法到目标引擎的完整转换清单（已落地：MySQL → Kingbase，含 `REPLACE INTO`、反引号、`DELIMITER`、反斜杠转义、`level` 关键字等）。
2. **字典表时间字段治理**：字典表（`sys_dict_*`、`zz_*global_dict*` 共 8 张）数据脚本的 `create_time`/`update_time` 必须为运行时时间；提供预检（复用仓库 `scripts/ci/check-dict-timestamp.sh`）、定位修复（`scripts/fix_dict_timestamp.py`，按列位置替换、语句边界有界、行尾字节透明）与验证闭环（预检复跑 + 逐 hunk 配对 + 行尾守卫）。

## 目录

```
SKILL.md                                    # 主流程（先读，含扩展新引擎指引）
references/functions.md                     # 幂等辅助函数模板（按引擎分节）
references/kingbase-compatibility.md        # MySQL → Kingbase 兼容转换清单（已落地）
references/dict-timestamp-precheck.md       # 字典表时间字段：预检/修复/验证手册
scripts/fix_dict_timestamp.py               # 字典表固定时间字面量定位修复（Python 3.9+ 标准库，引擎无关）
tests/test_fix_dict_timestamp.py            # 脚本单测（uv run tests/test_fix_dict_timestamp.py）
evals/evals.json                            # 端到端触发用例
```

## 扩展新引擎

按 SKILL.md「扩展新引擎」章节：新增 `references/<engine>-compatibility.md` 兼容清单 → 必要时在 functions.md 追加该引擎幂等模板 → 更新已落地引擎列表 → 走完整验证闭环。

## 来源

- 既有 skill：`basic-platform-service-sql/skills/mysql-kingbase-sql-migration`（迁移与兼容规则全量保留）。
- 实战沉淀：136 个 `6.0.8.1` 归档脚本中 12 个文件 228 处字典表固定时间的定位修复
  （含 Kingbase `UPDATE ... SET ... FROM` 误删 FROM 子句、反引号表名漏判、
  语句边界越界、autocrlf 行尾保持等实战坑，全部固化为脚本防护与测试用例）。
