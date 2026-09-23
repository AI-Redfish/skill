# 测试降级说明（iteration-1）

用户确认：禅道在链路中仅作为 bug 问题描述来源，当前无可用于 e2e 的测试禅道环境，
不提供 ZENTAO_* 凭据（testing-guide §2「用户拒绝提供 → 降级，不阻塞」）。

## 已验证（离线脚本级，全部通过）
- 单测 59/59（test_bugfix_sync / test_dingtalk_listen / test_analysis_first）
- eval-1 分析先行流转 6/6：骨架含流程要求提示 → 未补全检出 yes → 补全后 no → 缺失 missing
- eval-2 配置缺失理解闭环触发点 + 无头提示词契约 4/4（config-status 退出码 2）
- eval-3 触发模拟 8/8（4 正 4 负近邻，人工模拟：环境无 claude CLI，官方 run_eval 不可用）

## 未验证（依赖真实环境，报告中标注）
- 禅道 API 连通性（fetch_bug_full / prepare 的拉取部分）
- AI 行为层面：真实会话中「先补全 analysis.md 再改代码」的执行纪律
  （脚本侧已通过 NEXT 提示、骨架提示、ANALYSIS_INCOMPLETE 校验、无头提示词、
  verify_fix analysis_complete 五重约束支撑，行为验证需真实使用中观察）
- 钉钉 dws 监听链路（与本次改动无直接关联，未改动其核心逻辑）
