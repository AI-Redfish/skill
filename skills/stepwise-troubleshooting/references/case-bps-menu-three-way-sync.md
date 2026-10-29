# 实战案例：监测系统/菜单三端一致性排查（BPS 平台，已脱敏）

> 何时读：排查"监测系统配置的菜单与租户菜单管理不一致""管理端删了菜单运营端还显示""给租户分配菜单时缺少某些菜单"这类问题时读。
> 本文是 stepwise-troubleshooting 的实战案例，所有 IP、租户 ID、菜单 ID 均为占位符。

## 一、系统链路（数据流）

```text
[管理端 mgr 库]                                  [运营端 ops 库（每租户一套数据，tenant_id 区分）]
监测系统配置 monitor_system                       sys_menu（租户菜单副本，含 tenant_available）
  ├─ use_pages_content（绑定的页面ID，逗号分隔）    sys_role_menu（角色-菜单绑定）
  ├─ menu_root_id（自动生成的菜单目录根ID）        sys_data_perm_menu（数据权限-菜单绑定）
  └─ 保存时自动同步子菜单 ──┐                      sys_menu_mobile_relation / sys_menu_client_relation
                           ▼                      sys_preset_menu（预设菜单）
sys_tenant_menu（菜单树）── 租户分配 sys_tenant_menu_rel ── RocketMQ 消息 ──▶ tenant-sync 消费
（界面删除走应用层会发同步消息；直接改库不触发，需手工清理对端）
```

页面字典表：`monitor_system_page`（page_id / name / code / web_url / deleted_flag）。
生成规则：保存监测系统时，按 `use_pages_content` 里**未删除**的页面生成子菜单（路由=web_url+systemCode 参数），挂在 `menu_root_id` 下。

## 二、关键机制与陷阱

1. **自动同步只维护 `menu_root_id` 指向的目录**：`menu_root_id` 为空或指向的菜单不存在时，保存会**自动新建一个顶级目录**（名称=系统名，parent 为空）。手工建的同名目录（挂在场景树下）**不会**跟随更新——这是"双同名目录"陷阱，配置了但看不到，多半是看错了目录。
2. **界面删除 vs 直接改库**：界面删除菜单走应用层，会级联子菜单、清理标签/模板绑定，并发同步消息把运营端副本置为不可用；直接改库绕过这一切，**两端都要手工处理并复核**。
3. **管理端 `sys_tenant_menu` 没有逻辑删除字段**，删除即物理删除；`monitor_system.deleted_flag` 是逻辑删除。
4. **移动端入口是独立树**（`sys_tenant_mobile_entry` + `_rel`），删菜单不会删移动端入口，需单独处理。

## 三、排查 SQL 序列（占位符：`<系统编码>` `<根菜单ID>` `<租户ID>` `<库型>`）

按 stepwise 流程逐步执行，每步带结果判断对照表。

1. **配置查询**（管理端库）：

```sql
SELECT monitor_system_id, system_code, system_name,
       use_pages_content, menu_root_id, deleted_flag
FROM monitor_system
WHERE system_code = '<系统编码>';
```

| 结果 | 结论 | 下一步 |
|---|---|---|
| 无记录 | 系统没建/编码不对 | 核对编码 |
| `use_pages_content` 缺页面 | 配置未保存成功 | 查保存请求 |
| 正常 | 配置 OK | 查页面字典 |

2. **页面字典**：`SELECT page_id, name, web_url, deleted_flag FROM monitor_system_page WHERE page_id IN (<配置里的ID>);`——页面被删或 web_url 为空则菜单不会生成。

3. **菜单树**：`SELECT menu_id, menu_name, form_router_name, show_order FROM sys_tenant_menu WHERE parent_id = '<根菜单ID>' ORDER BY show_order;`——与上一步"未删除页面数"对比：少=缺菜单，多=有手工加的菜单。

4. **同名目录排查**：`SELECT menu_id, parent_id, menu_name FROM sys_tenant_menu WHERE menu_name = '<系统名>';`——多于 1 行即双目录陷阱，确认 `monitor_system.menu_root_id` 指向哪个，旧副本经用户确认后处理。

5. **绑定预检**（删除前必做）：分别 COUNT `sys_tenant_menu_rel`、`sys_tenant_template_menu`、`sys_tenant_menu_tag_rel` 中命中待删菜单的行数。

6. **ops 孤儿菜单盘点**（跨库，管理端连接执行）：

```sql
SELECT m.tenant_id, COUNT(*) AS orphan_cnt,
       SUM(m.tenant_custom = 1) AS tenant_custom_cnt
FROM <ops库>.sys_menu m
WHERE m.menu_id NOT IN (SELECT menu_id FROM <mgr库>.sys_tenant_menu)
GROUP BY m.tenant_id;
```

`tenant_custom=1` 的租户自建菜单**不删**。明细建议带递归全路径给产品确认（MySQL 8）：

```sql
WITH RECURSIVE menu_path AS (
  SELECT m.menu_id, m.menu_name, CAST(m.menu_name AS CHAR(2000)) AS full_path
  FROM <ops库>.sys_menu m
  WHERE m.tenant_id = <租户ID> AND (m.parent_id IS NULL OR m.parent_id = '')
  UNION ALL
  SELECT c.menu_id, c.menu_name, CONCAT(mp.full_path, ' / ', c.menu_name)
  FROM <ops库>.sys_menu c JOIN menu_path mp ON c.parent_id = mp.menu_id
  WHERE c.tenant_id = <租户ID>
)
SELECT mp.menu_id, mp.menu_name, mp.full_path, s.tenant_available
FROM menu_path mp
JOIN <ops库>.sys_menu s ON s.menu_id = mp.menu_id
WHERE s.tenant_id = <租户ID>
  AND mp.menu_id NOT IN (SELECT menu_id FROM <mgr库>.sys_tenant_menu)
ORDER BY mp.full_path;
```

## 四、清理四段式（案例实测结构）

- **预检**：client_root_id 是否为空、各关联表命中行数；
- **备份**：`bak_YYYYMMDD_monitor_system`、`bak_YYYYMMDD_sys_tenant_menu`、`bak_YYYYMMDD_sys_tenant_mobile_entry(+_rel)`、ops 侧 `bak_YYYYMMDD_ops_sys_menu`、`bak_YYYYMMDD_ops_sys_role_menu` 等；
- **修改**：先删关联（`_rel`/`_template_menu`/`_tag_rel`/`_menu_mobile_relation`/`_menu_client_relation`/`_preset_menu`），再删本体（菜单/入口），最后逻辑删 `monitor_system`（`deleted_flag=1`）；
- **复核**：每类计数归零 + 界面验证；ops 侧再跑一次孤儿盘点应为 0。

ops 侧引用 menu_id 的关联表清单（删菜单时逐一预检）：
`sys_role_menu`、`sys_data_perm_menu`、`sys_menu_mobile_relation`、`sys_menu_client_relation`、`sys_preset_menu`。

## 五、缓存要点（改库后必读）

| 缓存 | 位置 | 自愈机制 | 处理 |
|---|---|---|---|
| 权限类（USER_PERMISSION_CACHE 等） | 各服务 JVM（Caffeine） | TTL 600 秒 | 无需处理，或让用户重新登录 |
| 使用范围缓存（Redis 键 `USE_SCOPE:MENU_META/MOBILE_MAP/CLIENT_MAP/...`） | 仅管理端 tenant-admin 服务 | TTL 1 天 + 每 10 小时定时重建 + 启动全量预热 | **重启 tenant-admin** 即干净重建，不要手工删键 |
| 菜单树 | 无缓存，实时查库 | — | 界面刷新即可见 |

## 六、教训沉淀

1. "配置了但看不到"先查**是否有多份同名目录/数据**，再怀疑生成逻辑——本案例两轮都命中重复数据。
2. 界面上"移除/删除"类操作**保存前只是本地暂存**（前端 pendingChanges），必须点保存才落库——排查先确认操作真的提交了。
3. 排查期间现场可能有人并发操作界面：发现"查无此数据"先核实是否被别人删了，再继续。
4. 改库绕过 MQ 后，对端副本必须手工补齐并复核，且要在收尾提醒用户后续走界面操作验证同步链路是否健康。
