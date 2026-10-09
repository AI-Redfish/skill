# 测试数据挖掘策略（05-test-data.md）

> status: draft | reviewed
> 用途：测试样本的**挖掘策略集**——业务数据是变化的，样本 ID/SN 一律不写死；
> 测试脚本执行时按下面的 SQL 从目标环境 DB 现查现用。预期值同理现查。
> 长整型 ID 一律按字符串处理（JS 精度坑）。

## 挖掘 SQL 台账

| 引用键（env.json fixtures） | 用途 | 挖掘 SQL / 筛选条件 | 示例快照（仅供人工参考） |
|---|---|---|---|
| multiSystemDevice | 属性扇出验证：找多系统设备 | `SELECT sn FROM t_device WHERE status=1 AND system_count>=2 LIMIT 1` | sn=8803xxx（2026-01 查询） |
| publishedDrawing | 图纸下发验证：找已发布图纸 | `SELECT id FROM t_drawing WHERE point_count>0 AND status='PUBLISHED' ORDER BY update_time DESC LIMIT 1` | id=1752xxx（2026-01 查询） |

<!-- 填写规则：
1. 只沉淀"怎么找到合格样本"的策略（SQL/筛选条件），不固化具体 ID/SN；
   示例快照仅供人工核对，运行时一律以 SQL 现查为准
2. 优先选"配置齐全"的样本条件（多系统扇出、有点位、有分组），一台顶十台
3. SQL 必须可重跑：排序/过滤条件稳定，环境重置后仍能挖到同类样本；
   挖不到时更新 SQL 并在 06-history 记录原因
4. 探针用法：lib.fixtures['multiSystemDevice'] 取条件 → lib.open_db() 现查
5. 本轮实际样本、输入与预期/实测快照按测试点编号写 runs/<run-id>/evidence/，
   报告记录选样环境/时间/策略和关键字段；凭据不记录、敏感数据脱敏。
   本轮快照只是证据，不可固化进脚本/fixtures 供下轮复用；未执行不编造样本 -->
