# 字典表时间字段预检与修复

字典表数据脚本中 `create_time` / `update_time` 必须取数据库运行时时间
（`CURRENT_TIMESTAMP` / `NOW()` 等），不允许写死固定时间，否则字典数据的
创建/更新时间会随脚本写死，无法体现真实插入时间。本文档是该规则的完整
操作手册：预检 → 定位修复 → 验证闭环。规则与脚本引擎无关，已在 MySQL 与
Kingbase 真实归档数据上验证；其他关系型库沿用同一规则（`CURRENT_TIMESTAMP`
为标准 SQL，若目标引擎时间字面量写法特殊，先扩展 is_literal_time 判定并与
预检器对齐）。

## 字典表清单

清单维护在仓库 `scripts/ci/dict-tables.txt`（每行一个表名，`#` 注释，支持 schema.table）：

- basic_platform_ops：`sys_dict_key`、`sys_dict_value`
- basic_platform_mgr：`sys_tenant_dict_key`、`sys_tenant_dict_value`
- basic_platform_ops：`zz_tenant_global_dict`、`zz_tenant_global_dict_item`
- basic_platform_mgr：`zz_global_dict`、`zz_global_dict_item`

规则只约束这些表的 `INSERT` / `REPLACE` / `UPDATE` 数据语句；其他表（如菜单、
模板）的时间字段不在此列，允许保留历史固定时间。

## 预检命令（CI 门禁 = scripts/ci/check-dict-timestamp.sh）

```bash
bash scripts/ci/check-dict-timestamp.sh                  # diff 模式：只查本次改动（MR/本地增量）
bash scripts/ci/check-dict-timestamp.sh all              # 全量扫描（存量摸底用）
bash scripts/ci/check-dict-timestamp.sh paths <file>...  # 只查指定文件
bash scripts/ci/check-dict-timestamp.sh files-from <清单文件>   # 每行一个文件（CI 用）
bash scripts/ci/check-dict-timestamp.sh --self-test      # 内置用例自检
```

- 退出码：0=通过，1=存在违规，2=用法/配置错误。
- `DICT_CHECK_MAX_SHOW=500` 可调大展示条数；完整命中清单建议落盘分析。
- 每条违规输出：`文件:行号`、命中的表.列、值、定位上下文（`VALUES 第 N 列` /
  `SELECT 字段第 N 列` / `SET 赋值`）、源码片段。

### Windows Git Bash 注意

`rg --files` 输出反斜杠路径会被脚本的 `mysql/`、`kingbase/` 前缀过滤全部丢弃，
导致"检查通过"的假阳性。必须转换为正斜杠后走 `files-from`：

```bash
rg --files -g '*.sql' | tr '\\' '/' > /tmp/list.txt
bash scripts/ci/check-dict-timestamp.sh files-from /tmp/list.txt
```

MSYS 的 `/tmp` 与 Node/部分工具解析的 `/tmp` 不一致；跨工具交换文件时使用
仓库内相对路径或明确的 `D:/...` 路径。

## 违规的四种形态

1. `INSERT/REPLACE ... (列清单) VALUES (元组)`：元组中 create_time/update_time
   位置的带引号日期（如 `'2026-10-09 12:00:00'`）或纯数字（如 `20261014`）。
2. `INSERT ... (列清单) SELECT ...`：SELECT 字段列表对应列位置的字面量
   （含 UNION 多分支，每个分支都要检查）。
3. `UPDATE ... SET create_time='...', update_time='...'`（含 MySQL 多表 UPDATE、
   Kingbase `UPDATE ... SET ... FROM ... WHERE`）。
4. `INSERT ... ON DUPLICATE KEY UPDATE update_time='...'`。

范围外（检查器与修复脚本均不处理，需人工改写）：未显式列出字段清单的
`INSERT INTO t VALUES (...)`，以及 MySQL 专属的 `INSERT ... SET` 语法——
两者无法按列位置定位。

合法值（不会被判违规）：`CURRENT_TIMESTAMP`、`NOW()`、`SYSDATE`、`NULL`。
判定细节与 `scripts/ci/dict-timestamp-check.awk` 的 `is_literal_time` 一致。

### 豁免注释

确要保留历史时间的行，在该行或其上一行加注释即可豁免：

```sql
INSERT INTO sys_dict_key (dict_key_id, create_time, update_time) -- dict-time-check: ignore 保留历史字典创建时间
VALUES ('1', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
```

## 定位修复（scripts/fix_dict_timestamp.py）

```bash
# dry-run（默认）：只报告命中位置与值，退出码 1 = 存在待修复项
uv run <skill_dir>/scripts/fix_dict_timestamp.py <file>...
# 应用修复：写回文件；退出码 0 = 成功
uv run <skill_dir>/scripts/fix_dict_timestamp.py --apply <file>...
# 自定义字典表清单
uv run <skill_dir>/scripts/fix_dict_timestamp.py --tables-file scripts/ci/dict-tables.txt <file>...
```

设计要点（为什么不能"整行盲替换字面量"）：

1. **按列位置替换**：只在显式列清单中 create_time/update_time 对应的元组/列表
   位置替换，非时间列的相同字面量不受影响；未显式列出字段清单的语句跳过
   （无法定位，需人工改写）。
2. **语句边界**：所有扫描以 `;` 为界，绝不越过语句边界（越界会把后续语句的
   内容重复处理/误替换）。
3. **赋值右值终止词必须包含 `from`**：Kingbase/PG 的
   `UPDATE t SET c='lit' FROM (...) x WHERE ...` 中，若右值扫描不含 `from`
   就会吞掉整个 FROM 子句，替换时把子句整块删除（实战事故：16 行丢失）。
4. **引号感知**：表名/列名的反引号、双引号包裹必须按标识符 token 处理，
   不能用纯单词匹配，否则 MySQL 风格 `` INSERT INTO `db`.`tbl` `` 全部漏判。
5. **字节透明**：文件按 latin1 字节透明读写，替换前后 CRLF/LF 行尾、UTF-8
   中文、编码完全不变；内置硬断言：编辑区间不得包含换行符、替换前后总行数
   必须一致。
6. 与 awk 检查器判定对齐：运行时函数、`NULL` 不算违规；**纯数值只有不带
   引号才算时间字面量**（`20261014` 算，`'123'` 不算）；带引号日期子串匹配。

## 验证闭环（修复后必须全做）

1. **复跑预检**：`bash scripts/ci/check-dict-timestamp.sh paths <改动的文件>...`
   必须通过（0 违规）。
2. **逐 hunk 配对验证**：`git diff -U0` 的每个 hunk 中删除行数必须等于新增
   行数；每对 `-/ +` 行把删除行中的固定时间字面量替换为 `CURRENT_TIMESTAMP`
   后必须与新增行完全相等。若某 hunk 行数不对称，通常是 git 最小化 diff 的
   平移表示，必须人工确认被"多删"的行原样存在于新文件中。
3. **行尾与内容守卫**：`file <f>` 确认 CRLF/LF 与改动前一致；diff 统计应为
   对称的 `N insertions(+), N deletions(-)`；出现不对称时优先怀疑误删。
4. **人工抽查**：`git diff` 目视抽查每类形态至少一处（VALUES/SELECT/SET/
   ON DUPLICATE/UPDATE..FROM）。

### 已知陷阱

- `git show HEAD:file` 取出的是 autocrlf 规范化后的 LF blob，与 CRLF 工作区
  逐字节比对必然报差；跨版本比对要先按原行尾风格重建（或用 `git diff`）。
- `git checkout -- <file>` 会按 autocrlf 把工作区文件重写为 CRLF；对原本是
  LF 的文件属于额外改动，恢复时需转回 LF。
- 测试脚本时先用 dry-run 确认命中数，再 `--apply`；修复后立即复跑预检，
  不要连续叠加多步不可逆操作。
