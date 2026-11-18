# 多租户数据初始化 SQL 编写与实测（mgr/ops 双库）

## 内容与何时读
为 BPS 编写字典或业务数据初始化增量 SQL（涉及 `basic_platform_mgr` 与 `basic_platform_ops` 双库）时读本文。涵盖 mgr 租户字典模板机制、ops 在营租户 expand 写法、每租户唯一 ID 策略、Kingbase 保留字坑与双端实测方法。来源：2026-11 设备类型新增「移动设备」（MDEV）任务，139 MySQL + 127 Kingbase 验证库实测。

## mgr 租户字典模板机制
- `basic_platform_mgr.sys_tenant_dict_key` / `sys_tenant_dict_value` 是平台级模板表：无 `tenant_id` 列、`sys_tenant_dict_value.dict_value_id` 单列主键、无 `source` 列、`deleted_flag` NOT NULL 且无默认值（INSERT 必须显式给 0）。
- mgr 库没有 ops 式 `sys_dict_value` 表；在 mgr 查 `sys_dict_value` 会报 `Table doesn't exist`，勿混。
- 新租户创建时由平台把 mgr 模板分发到 ops。给字典 key 新增值时：mgr 模板 + ops 在营租户分发两侧都要补，只补一侧会导致新租户有值、存量租户没有（或相反）。

## ops 在营租户 expand 写法
```sql
INSERT INTO basic_platform_ops.<表> (...)
SELECT ..., tenant.tenant_id, ...
FROM basic_platform_ops.sys_tenant tenant
WHERE tenant.deleted_flag = 0
  AND NOT EXISTS (   -- 按 tenant + 业务编码 + deleted_flag=0 判重
      SELECT 1 FROM basic_platform_ops.<表> e
      WHERE e.tenant_id = tenant.tenant_id AND e.<code列> = '<编码>' AND e.deleted_flag = 0)
```
- 幂等双层：`NOT EXISTS`（语义判重）+ `ON DUPLICATE KEY UPDATE`（MySQL）/ `ON CONFLICT (...) DO UPDATE`（Kingbase）。
- 先例：仓库 `6.0.7.3.15` ops data 脚本（seed 租户 UNION ALL + 同模式）。

## 每租户唯一 ID 策略
- 单列主键表（如 `monitor_device_type.device_type_id`）每个租户必须唯一：用 `CONCAT('20', tenant_id)` 派生，不能全租户共用固定 ID。
- 复合主键表（如 `sys_dict_value` 主键 `(dict_value_id, tenant_id)`）同一 `dict_value_id` 可跨租户共存。
- 镜像契约：`sys_dict_value.dict_value_id = monitor_device_type.device_type_id`，两侧用同一派生 ID。

## Kingbase 踩坑
- `level` 是保留字：建表列定义、INSERT 列清单、`ON CONFLICT DO UPDATE` 中都必须写 `"level"`（带双引号）。归档 dump 与历史 data 脚本一致带引号。
- 报错特征：`syntax error at or near "level"`，不指明原因；遇到 near <列名> 类报错先查保留字。
- 标识符大小写不敏感（实测 `'abc'='ABC'` 相等），schema/表名无需担心大小写。
- 单列主键 `ON CONFLICT (dict_value_id)`；复合主键 `ON CONFLICT (dict_value_id, tenant_id)`。
- MCP `kingbase_query` 响应文本含中文时直接 `JSON.parse` 会抛 `SyntaxError`（如 `Unexpected token '\u5de5'`），先判断是否以「工具执行异常」开头，或直接按文本处理。

## 双端实测方法
- MySQL（如 139 环境）：同连接内 `START TRANSACTION` → 执行脚本语句 → `SELECT` 验证行数与内容 → `ROLLBACK` → 复查计数归零。DDL 外的数据语句可完整回滚。
- Kingbase 验证库无业务表时：`CREATE SCHEMA` + 按目标表结构建最小表（列名加引号处理保留字）→ 种子租户 → 执行脚本 INSERT → 验证 → 幂等复跑（应 0 行）→ `DROP SCHEMA ... CASCADE` 清理 → `pg_namespace` 复查无残留。
- MCP `kingbase_query` 的 DDL 单次调用后即持久生效（autocommit）；支持单次调用多语句，但首语句失败后的行为语义不明，验证脚本建议逐条执行。
- 幂等验收标准：首跑插入 N 行，复跑 0 行，清理后无残留。
