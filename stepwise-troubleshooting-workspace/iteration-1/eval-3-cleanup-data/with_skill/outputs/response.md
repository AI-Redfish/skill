你的需求：清理不符合要求的监测系统及其管理端菜单与关联数据。

删除不可逆，先按四段式来，**预检结果给你确认后才执行删除**。

【第 1 段：预检（只读）】确认待删清单与影响面：

SELECT monitor_system_id, system_code, system_name, menu_root_id, mobile_entry_root_id
FROM monitor_system WHERE system_code NOT IN (<保留编码清单>) AND deleted_flag = 0;

SELECT
  (SELECT COUNT(*) FROM sys_tenant_menu_rel WHERE menu_id IN (<待删菜单ID>)) AS menu_rel_cnt,
  (SELECT COUNT(*) FROM sys_tenant_template_menu WHERE menu_id IN (<待删菜单ID>)) AS template_cnt;

请确认待删清单无误、关联计数知悉，回复确认后我给第 2 段。

【第 2 段：备份】（确认后执行，命名 bak_YYYYMMDD_<对象>）
CREATE TABLE bak_20261029_monitor_system AS SELECT * FROM monitor_system WHERE <条件>;
CREATE TABLE bak_20261029_sys_tenant_menu AS SELECT * FROM sys_tenant_menu WHERE <条件>;
每张备份表执行后核对行数。

【第 3 段：删除】（先关联后本体，每条单独执行、看行数）
1. DELETE 关联表（sys_tenant_menu_rel / sys_tenant_template_menu / sys_tenant_menu_tag_rel / sys_tenant_menu_mobile_relation / sys_tenant_menu_client_relation，JOIN 备份表）
2. DELETE 移动端入口及绑定
3. DELETE sys_tenant_menu 本体（JOIN 备份表，规避 MySQL 同表子查询限制）
4. UPDATE monitor_system SET deleted_flag = 1（逻辑删）

【第 4 段：复核】各关联计数归零 + 界面验证；跨端副本（运营端）需另行盘点清理。
回滚方式：从 bak_ 表 INSERT 回原表，monitor_system 将 deleted_flag 改回 0。
提醒：能走监测系统配置界面的删除优先走界面（应用层会同步清理并通知运营端）；直接改库后需按缓存章节核查。
