你的需求：排查空调监测系统在租户菜单下缺少"分组管理"和"视频监控"两个菜单的原因，并判定是否为代码问题。

【第 0 步：环境信息收集】排查前请提供（可一次补齐）：
1. 后端仓库/工作区地址 + 分支或版本号（你提到 6.0.8.1，请确认现场部署的构建与该分支一致）；
2. 前端仓库/工作区地址 + 分支；
3. 数据库类型（MySQL/KingBase）、地址、管理端库名与运营端库名；
4. Redis/MQ 是否可查看（涉及同步链路时用）。

【初步判定（基于源码链路，待现场数据验证）】菜单链路是：监测系统配置(use_pages_content) → 自动生成管理端菜单树(menu_root_id) → 租户分配(sys_tenant_menu_rel) → MQ 同步到运营端。代码中生成逻辑对"分组管理/视频监控"无特殊排除（MonitorSystemServiceImpl.syncMenusAndMobileEntries），初步倾向**配置或数据问题**（如双同名目录、页面绑定未保存），但需现场数据确认，暂不下最终结论。

【第 1 步】请在管理端库执行这条只读查询并把结果发我：

SELECT monitor_system_id, system_code, system_name,
       use_pages_content, menu_root_id, deleted_flag
FROM monitor_system
WHERE system_code = '<系统编码>';

| 执行结果 | 结论 | 下一步 |
|---|---|---|
| 无记录 | 系统未建或编码不对 | 核对编码 |
| use_pages_content 缺这两个页面的 ID | 配置未保存成功 | 查保存请求 |
| 配置正常且含两个页面 | 配置 OK | 下一步查菜单树是否生成 |
