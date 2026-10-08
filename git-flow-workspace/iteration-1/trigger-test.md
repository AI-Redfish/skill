# 触发测试 — iteration-1（人工模拟判定，无 claude CLI）

依据 description 四要素逐条判定；正例预期触发、负例为近邻场景预期不触发。

| # | Query | 预期 | 判定 | 依据 |
|---|---|---|---|---|
| 1 | 帮我新建一个worktree，基于分支 origin/dev/v6.0.9.0 | 触发 | ✅触发 | "新建一个worktree"+"基于分支"命中核心触发语 |
| 2 | 从 dev/v6.0.8.1 给我拉个工作区，分支 v6.0.8.1/fixbug/qk-75339-20261008 | 触发 | ✅触发 | "拉个工作区"=创建 worktree 口语变体；信息完整直接执行 |
| 3 | 帮我开个 worktree 空间并行改 bug | 触发 | ✅触发 | worktree/空间/并行开发命中；缺参数→理解闭环先问基分支 |
| 4 | create a worktree based on origin/dev/v6.0.8.1, branch v6.0.8.1/feature/xyz | 触发 | ✅触发 | 英文变体，"worktree"+基分支命中 |
| 5 | 把这个 worktree 删了，不需要了 | 不触发 | ✅不触发 | description 边界明确"不处理 worktree 删除" |
| 6 | 帮我在当前目录切到 dev 分支 | 不触发 | ✅不触发 | description 边界"当前工作区内切分支"不处理 |
| 7 | 把 worktree 里的改动合并回 dev | 不触发 | ✅不触发 | description 边界"跨分支合并与提交流程"不处理 |
| 8 | 帮我把这个仓库 clone 到本地另一份 | 不触发 | ✅不触发 | clone 是完整副本非 worktree，无"worktree/工作区/基于分支"触发语 |

## 结果

- 正向触发率：4/4 = 100%（达标线 ≥85%）
- 负向误触发率：0/4 = 0%（达标线 100% 不触发）
- 结论：**通过**
