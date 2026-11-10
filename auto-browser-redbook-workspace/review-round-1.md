# AI 双评审意见 — auto-browser-redbook（round 1，机器检查迭代至 round 4）

评审对象：`skills/auto-browser-redbook`（SKILL.md + references/redbook-playbook.md +
scripts×3 + evals/evals.json）
评审依据：review-guide.md 清单 A（设计）/ B（实现）/ C（置信判据）

## Round 历史

| 轮次 | 动作 | 结果 |
| --- | --- | --- |
| 1 | 初版机器检查：exit=0，1 warn（缺 evals/） | 发现双闭环章节过简、缺输出精简约束 |
| 2 | 补双闭环/自我沉淀闭环/evals 后：exit=1 | error: loop_output_review 模板不完整、output_minimalism 缺章节；4 warn |
| 3 | 按标准模板整段补齐：exit=0 | 0 error 0 warn |
| 4 | AI 评审发现对称缺陷：redbook_clip.py URL 域名校验仍在 ensure_session 之后（与 bilibili 修复前相同，负向 URL 会先启动浏览器），修复后重跑：exit=0 | 0 error 0 warn，全过 |

## 清单 A：设计评审

- 双闭环内嵌：✅ 标准模板整段（一次一问/十要素/双 95%/最终输出要求）
- 自我沉淀闭环：✅ 信号清单 + 询问 + 小步修改递增版本
- 单一职责：✅ 单平台单篇沉淀
- 触发准确：✅ WHEN/WHEN NOT 覆盖带 token 链接与 --tab 口语说法；与 bilibili 按平台划分无冲突
- 负向场景：✅ 不适用场景小节 + evals 负向用例（批量/裸链接/评论抓取）
- 渐进式披露：✅ 细节在 references/redbook-playbook.md（真实存在）
- 输入输出契约：✅ --url/--tab/--list 三入口互斥；JSON/退出码记载
- 五段式/指令/格式/示例/防幻觉：✅ 输出规范含模板与排他约束、不确定标注条款

## 清单 B：实现评审

- 正确性：py_compile + node --check（约 150 行内嵌提取 JS）+ --help 冒烟通过；
  水合等待/wrongNote/多代视频流兼容逻辑与 AgentPhoto background.js 同构
- 边界：slugify 兜底；https 升级；直链多候选；序号实查；wait_ready 已简化为
  ready && hasDesc（去冗余条件）
- 容错：blocked/wrongNote/notScoped/videoDiag 均有专门错误与行动提示；dump-video.json 诊断落盘
- Agent 友好：JSON stdout / stderr 日志 / 退出码；--list 供标签页发现；多匹配不擅自二选一
- 幂等安全：序号递增不覆盖；登录态在 skill 内 profiles/chrome
- 注入隔离：SKILL.md 声明页面数据按数据对待
- 密钥卫生：无硬编码凭据；不写死任何笔记 ID/Token（xsec_token 由用户运行时提供）
- uv 规范：playwright PEP 723；纯标准库优先

## 清单 C：置信度自评

- 判据1 机器检查：通过（round 4 exit=0，0 error 0 warn）
- 判据2 P0/P1：无。P2 遗留 3 项（记录于下）
- 判据3 负向验证：bad-args / 非小红书域名（已提前校验不启动浏览器）/ 批量请求 /
  裸链接推演通过；bad-args、bad-url 在测试门实跑
- 判据4 错误路径：blocked / wrongNote / notScoped / no-page / ambiguous 均有 JSON 错误结构与 hint
- 判据5 边界抽查：slugify 空/超长；序号递增；--tab 多匹配歧义处理——推演通过
- 判据6 需求对照：用户三项决定逐条落实
- 判据7 fresh eyes：SKILL.md 通读，引用的 playbook/evals 均真实存在

## P2 遗留（不阻塞评审，测试报告需标注）

1. 端到端抓取未实测（用户决定暂缓）：真实页面提取、图片/视频/实况下载行为未验证
2. --tab 模式对已开标签页的匹配依赖窗口标题，运行时才能验证
3. playbook 的 noteDetailMap 结构基于 AgentPhoto 2026-11 实战，平台变更需按排查路径核对

置信度自评：95%
