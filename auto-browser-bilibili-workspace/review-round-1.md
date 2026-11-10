# AI 双评审意见 — auto-browser-bilibili（round 1，机器检查迭代至 round 3）

评审对象：`skills/auto-browser-bilibili`（SKILL.md + references/bili-playbook.md +
scripts×3 + evals/evals.json）
评审依据：review-guide.md 清单 A（设计）/ B（实现）/ C（置信判据）

## Round 历史

| 轮次 | 动作 | 结果 |
| --- | --- | --- |
| 1 | 初版机器检查：exit=0，1 warn（缺 evals/） | 发现双闭环章节过简、缺输出精简约束 |
| 2 | 补双闭环/自我沉淀闭环/evals 后：exit=1 | error: loop_output_review 模板不完整、output_minimalism 缺章节；4 warn |
| 3 | 按标准模板整段补齐 + 输出规范 + 防幻觉 + 触发示例/不适用场景：exit=0 | 0 error 0 warn，全过 |
| 附带修复 | bili_clip.py URL 校验提前到 ensure_session 之前（负向 URL 不再先启动浏览器） | py_compile 通过 |

## 清单 A：设计评审

- 双闭环内嵌：✅ 标准模板整段（一次一问/十要素/双 95%/最终输出要求）
- 自我沉淀闭环：✅ 信号清单 + 询问 + 小步修改递增版本
- 单一职责：✅ 单平台单篇沉淀，边界清晰
- 触发准确：✅ description 含 WHEN/WHEN NOT 与口语说法；与 redbook 按平台划分无冲突；
  旧 bilibili-video-transcript 已删除，无相邻冲突
- 负向场景：✅ "边界与不适用场景" 小节 + evals 负向用例（批量/元数据问答/非 B 站链接）
- 渐进式披露：✅ SKILL.md 流程精简，细节在 references/bili-playbook.md（文件真实存在）
- 输入输出契约：✅ 参数/默认值/JSON 结构/退出码 0/2 均记载
- 五段式/指令/格式/示例/防幻觉：✅ 输出规范含模板与排他约束、不确定标注条款

## 清单 B：实现评审

- 正确性：py_compile + node --check（内嵌 JS）+ --help 冒烟通过；提取/下载/合并
  流程人工推演一致（与 AgentPhoto 同构逻辑）
- 边界：slugify 空标题兜底/截断/非法字符；http→https；直链时效多候选重试；序号文件系统实查
- 容错：错误三要素（问题+原因+行动）；ffmpeg 缺失降级保留分离流；不吞异常
- Agent 友好：JSON stdout / 日志 stderr / 退出码语义记载于 SKILL.md；无交互输入
- 幂等安全：同天同标题序号递增不覆盖；合并仅在输出文件存在后删分离流
- 注入隔离：SKILL.md 声明页面数据按数据对待
- 密钥卫生：无硬编码凭据；登录态在 skill 内 profiles/chrome
- uv 规范：playwright PEP 723；_common/browser_session 纯标准库

## 清单 C：置信度自评

- 判据1 机器检查：通过（round 3 exit=0，0 error 0 warn）
- 判据2 P0/P1：无。P2 遗留 3 项（记录于下）
- 判据3 负向验证：bad-args / bad-url（已提前校验不启动浏览器）/ 非规划域名 / 批量请求
  推演通过；bad-args、bad-url、--merge no-streams 在测试门实跑
- 判据4 错误路径：no-streams / blocked / video=null / no-ffmpeg 均有 JSON 错误结构与 hint
- 判据5 边界抽查：slugify 空/超长/特殊字符；序号递增；http 直链升级——推演通过
- 判据6 需求对照：用户三项决定（暂缓实测/沉淀/走门禁）逐条落实
- 判据7 fresh eyes：SKILL.md 通读，引用的 playbook/evals 均真实存在，无歧义步骤

## P2 遗留（不阻塞评审，测试报告需标注）

1. 端到端抓取未实测（用户决定暂缓）：真实页面提取、下载、合并行为未验证
2. ffmpeg 合并路径未实测（属端到端范围）
3. playbook 中的画质映射/API 参数基于 AgentPhoto 2026-11 实战，平台变更需按排查路径核对

置信度自评：95%
