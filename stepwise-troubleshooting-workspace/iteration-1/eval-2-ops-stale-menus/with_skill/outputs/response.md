你的需求：判定"管理端已移除菜单但运营端仍显示"是否代码问题，并给出排查路径。

【源码只读判定（非代码问题的依据）】管理端删除菜单的应用链路为：SysTenantMenuServiceImpl.remove 删除本表并发送 MQ 消息（命令 DELETE_TENANT_ROLE_TENANT），tenant-sync 服务消费后把各租户库 sys_menu.tenant_available 置为不可用——**同步机制在代码中存在**。因此"运营端没变化"更可能是：历史残留（同步生效前的旧数据）、当时 MQ 消费异常、或界面操作未点保存。结论方向：**配置或数据问题 / 待现场数据验证**，不是当前代码缺陷。

【第 1 步】先确认一个操作细节：移除菜单后是否点击了页面底部"保存"？前端"移除"仅暂存，保存才调用 batchDelete 接口。

【第 2 步】选一个管理端已移除、运营端仍显示的菜单，在运营端库执行孤儿盘点：

SELECT m.tenant_id, COUNT(*) AS orphan_cnt,
       SUM(m.tenant_custom = 1) AS tenant_custom_cnt
FROM <ops库>.sys_menu m
WHERE m.menu_id NOT IN (SELECT menu_id FROM <mgr库>.sys_tenant_menu)
GROUP BY m.tenant_id;

| 执行结果 | 结论 | 下一步 |
|---|---|---|
| orphan_cnt = 0 | 无残留，显示问题在前端或另一套库 | 核对连接与前端缓存 |
| orphan_cnt > 0 且 tenant_custom_cnt = 0 | 残留副本，可安全清理 | 出明细清单供确认后走四段式清理 |
| orphan_cnt > 0 且含 tenant_custom | 租户自建菜单混入 | 明细中单列，自建菜单不删 |

说明：若确认走 SQL 清理，属直接改库、绕过 MQ，**必须手工补齐对端清理并两端复核**；tenant_custom=1 的租户自建菜单不删除。
