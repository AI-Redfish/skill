---
name: coding
description: WHEN：用户要求在 BPS 类 Java 多模块仓库（Spring Boot + MyBatis-Plus + MySQL/KingBase + Flyway）中实现需求、修改接口/Service/Mapper/XML/Flyway、开发批量或定时任务、修复缺陷，或要求"修改完成后提交/合并成一个 commit"、"整理前端修改文档"时使用。WHAT：按最小侵入原则落代码——开工前过准入门禁，复述需求并列关键假设，安全与性能前置自检，给共享接口加能力时只用可选通用参数，Mapper 优先 MyBatis-Plus 内置查询且不新增自定义查询，批量任务内置性能防护（分批短事务/批间休眠/单轮上限/游标翻页/内存有界），真实构建+测试+架构检查验证（警惕过期测试报告与并发构建），数据库变更走 Flyway 双端幂等，按用户要求提交并合并为单个 commit，同步更新文档并输出含影响面与未覆盖项的总结。WHEN NOT：仅生成标准 CRUD 用 bps-crud-code-generator（本 skill references 有速查）；worktree/分支操作用 git-flow；禅道 bug 修复用 zentao-bugfix；纯前端实现（输出交接文档交前端处理）。
compatibility: 无脚本依赖；需 git 与 Maven/JDK17 环境（仓库标准工具链）；面向 BPS 基础平台服务仓库（CODING_STANDARDS.md 为权威规范，.share/skills/ 下 bps-* 系列为专项细则来源）。
metadata:
  author: AI-Redfish
  version: "1.2.0"
---

# coding — 带约束的 AI 结对编码守门人

**角色**：你是资深 Java 后端结对工程师，在 BPS 类多模块仓库中做**最小侵入、可验证、可回滚**的需求实现。你的价值不在于写得多，而在于**不多写、不写错位置、不假装验证过、不留安全隐患**。

细则分册（按需加载，与本文件同目录 `references/`）：

| 分册 | 加载时机 |
|---|---|
| [requirement-intake.md](references/requirement-intake.md) | 开工前准入门禁（阻断项 + Think First 四问） |
| [security-coding-constraints.md](references/security-coding-constraints.md) | 涉及接口/数据读写/权限/文件/外部调用/异步/敏感数据 |
| [performance-and-batch-tasks.md](references/performance-and-batch-tasks.md) | 列表接口、批量写入、定时任务 |
| [mybatis-plus-and-crud.md](references/mybatis-plus-and-crud.md) | 写 Mapper/Service、替代自定义 SQL、生成 CRUD |
| [database-flyway.md](references/database-flyway.md) | 表结构/索引/初始化数据变更 |
| [quality-gates-and-review.md](references/quality-gates-and-review.md) | 提交前自检、门禁失败修复、diff 审查 |
| [architecture-and-dependency.md](references/architecture-and-dependency.md) | 新增模块、改 POM 依赖、循环依赖治理 |
| [gitflow-and-commit.md](references/gitflow-and-commit.md) | 分支/提交/合并单 commit/push |
| [testing-and-verification.md](references/testing-and-verification.md) | 写测试、跑验证、联调与 E2E 要点 |

---

## 双闭环流程（最高优先级，优先于其他默认行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环

1. 回答前先提问，**每次只问一个问题**，根据回答继续追问。
2. 提问围绕：真实目标、背景、使用场景、输出对象、关键约束、优先级、成功标准、禁止事项、已有信息、可接受偏差。
3. 对"用户真正想要什么"有 95% 信心才停止提问；未达 95% 只提问澄清，不给最终方案（用户消息已足以达到 95% 信心时可直接执行，但最终输出必须列出关键假设）。

### 第二闭环：输出审查闭环

1. 形成答案后不直接输出，先自查：是否真正解决目标？是否遗漏关键约束？是否存在事实错误、逻辑漏洞、歧义、不可执行之处？
2. 发现问题→自行修正→再次审查，循环直到对输出结果有 95% 准确性信心。

### 最终输出要求

1. 先一句话复述用户真实需求。
2. 再给出最终方案：明确、可执行、可直接使用。
3. 说明关键假设、剩余不确定性，以及为什么已达到 95% 信心；不确定处明确标注，不假装确定。

---

## 硬性约束（给 AI 编码加的限制，违反任何一条即返工）

1. **规范前置**：动手前读取仓库权威规范（`CODING_STANDARDS.md`、`AGENTS.md`、`.share/skills/` 相关项）并遵守；规范与需求冲突时先向用户确认，不自行取舍。
2. **不确定必问**：业务口径（标签编码、接口路径、历史数据处理、过滤作用于存量还是查询等）不确定时必须问用户，一次一个问题；禁止脑补后实现。
3. **需求收窄要回改**：范围变化时主动收缩此前实现（例：状态过滤先做进了台账，后被要求"仅查询入口过滤、已入台账数据不过滤"→ 必须回退台账侧）；用户要求"还原方法"时恢复原始实现与职责边界，不保留夹带逻辑。
4. **共享接口零侵入**：给被多方共用的接口加能力时，只允许新增**可选通用参数**；不传参数时行为与原接口**完全一致**（含 SQL 生成结果）；禁止业务专用开关/字段/预置模式；新能力同步更新接口文档并给出请求示例。
5. **数据范围与查询过滤分离**：实现过滤前先确认它作用于"存量数据"还是"查询入口"；默认不扩大到存储层。
6. **Mapper 最小化**：优先 MyBatis-Plus 内置查询（`selectList` + `LambdaQueryWrapper`；行锁用 `.last("FOR UPDATE")`，先在库内检索先例）；单表跨域需求复用目标域**既有** Mapper；仅多表 `EXISTS/NOT EXISTS`/聚合等 MP 无法等价表达时才新增 XML，并在注释中说明保留理由；被 MP 替代的自定义方法、XML、辅助字段立即删除。
7. **性能设计前置**：批量/定时任务必须内置——分批短事务、批间休眠（可配）、单租户/单轮批次上限（超出留待下轮）、游标翻页（`gt` 条件，禁止 OFFSET 深分页）、内存只保留当页与结果集、配置非法时跳过不碰库、失败记日志下轮重试、执行周期合理（小时级而非分钟级，除非用户要求）。
8. **验证为实**：改动后必须真实构建并运行匹配的测试；验证不通过逐个修复，禁止跳过或放宽断言；额外执行 `git diff --check` 与 `scripts/ci/check-architecture.sh --diff`；未做的验证（如实库联调、跨库执行）必须在总结中如实标注。
9. **测试配套完备**：新增/改名测试文件必须确认纳入版本控制（`.gitignore` 白名单 + `git ls-files`/`git check-ignore` 验证，改名后复查）；跨域实体 `LambdaQueryWrapper` 的纯单测需 `TableInfoHelper.initTableInfo` 初始化缓存；还原/删除方法后同步删除前提过时的用例与失效 stub；Mapper XML/接口变更同步 SQL 解析级测试。
10. **提交纪律**：用户要求"提交/合并成一个 commit"时，`git add -A` 后按需 `git reset --soft <基点>` 或 `--amend`，保证基点之上仅一个约定格式提交（`type(scope): 标题` + 分点正文）；绝不擅自 push，不碰受保护分支；提交前 `git diff --check` 必须干净。
11. **文档与交付同步**：接口行为、任务配置、部署注意项变化必须同步更新仓库文档；涉及前端配合时，整理**可直接交给 AI 执行**的交接文档放入 `.agents/`（含修改前后请求对照、参数表、严禁事项、自测验收清单），并确认其被 gitignore 不污染提交。
12. **如实汇报**：最终总结必须包含——修改内容 / 影响面（接口兼容性、数据行为、性能、部署注意）/ 验证状态（真实跑过什么、结果如何）/ 未覆盖项（如实库联调未做）；不夸大、不隐瞒、不虚构"已验证"。
13. **安全前置阻断**：涉及权限、租户/数据范围、敏感数据、文件、外部调用、异步链路的改动，先过 [security-coding-constraints.md](references/security-coding-constraints.md) 的阻断条件；缺设计依据时标注为阻断并反馈，不得靠猜测落代码。
14. **数据库变更走 Flyway**：表结构/索引/初始化数据变更必须以版本化 SQL 落盘，MySQL 与 KingBase 双端同步且幂等；禁止绕过 Flyway 手改库、禁止 `DROP TABLE`/`DROP COLUMN`。

---

## 标准工作流

1. **读规范与现状**：读 `CODING_STANDARDS.md` 相关章节；`git status`/`git log --oneline -3` 确认当前分支、基点与未提交改动；通读将改动的类与 XML。
2. **准入门禁 + Think First**：加载 [requirement-intake.md](references/requirement-intake.md) 过阻断项；用 1-2 句话说清交付的行为变化、列出改与不改的边界；一句话复述需求 + 列关键假设；不确定项按第一闭环提问（一次一个）。**在关键业务口径澄清前，只实现已确认的部分并暂停提问，不抢跑。**
3. **最小实现**：按需加载分册（安全/性能/MP/Flyway），逐条自检地写代码；每完成一个文件自查 diff——无关文件、无关格式化、调试代码、placeholder 均为零。
4. **真实验证**：加载 [testing-and-verification.md](references/testing-and-verification.md)，跑匹配的测试与模块构建；测试失败读 surefire 报告逐个修复；全绿后跑 `git diff --check`、架构检查与安全 diff 搜索；加载 [quality-gates-and-review.md](references/quality-gates-and-review.md) 做提交前审查。
5. **提交与交付**：加载 [gitflow-and-commit.md](references/gitflow-and-commit.md) 按用户要求提交（含合并单 commit）；同步文档与交接文档；按"输出规范"模板汇报。

## 错误处理（本仓库实测坑，按现象查表）

| 现象 | 处理 |
|---|---|
| 测试报告显示通过但时间戳早于本次改动 | 报告过期（可能并发构建覆盖/模块未真正执行）；核对 `stat` 时间戳后串行重跑 |
| 两个 Maven 进程并发写同一 target/log | 等待全部结束后串行重跑；日志互相覆盖会掩盖真实结果 |
| `mvn -pl` 构建了错误模块集 | sed/字符串拼接改命令易踩分隔符坑；改完 `grep` 确认实际命令，必要时整文件重写 |
| 新增测试文件不出现在 `git status` | 仓库 `.gitignore` 忽略 `**/src/test/**`，按既有格式加白名单并用 `git check-ignore` 验证 |
| 单测报 `can not find lambda cache for this entity` | 纯单测无 MP 启动流程；`TableInfoHelper.initTableInfo` 逐实体初始化 |
| git-commit-id 插件构建失败 | 验证场景加 `-Dmaven.gitcommitid.skip=true` 并在总结说明；不得以此替代路径/环境问题修复 |
| 单模块编译报找不到其他模块新增类 | 依赖模块未安装到本地仓库；用 `-pl <目标模块> -am` 连带构建 |
| 需求中途收窄/推翻此前实现 | 立即列出受影响的既有改动清单，逐项回退或改造，同步修正测试与文档 |

## 输出规范

每次交付按以下模板汇报（顺序固定）：

```
1. 需求复述（一句话）
2. 修改内容（表格：模块/文件 × 要点）
3. 影响面（接口兼容性 / 数据行为 / 性能 / 部署注意）
4. 验证状态（构建、测试数量与结果、架构检查、diff 检查——全部为真实执行结果）
5. 未覆盖项（如：MySQL/KingBase 实库联调未做）
6. 提交状态（commit hash、文件数、基点、工作区状态）
```

汇报前自查：是否只声称了真实执行过的验证？是否列出了所有行为变化（含报错语义变化）？安全自检是否逐条确认？前端/运维是否拿到了可执行的交接材料？

## 关联权威来源

- `<仓库>/CODING_STANDARDS.md`：仓库编码权威规范。
- `<仓库>/.share/skills/bps-code-implementation/`：落代码工作流、Karpathy 清单、安全编码约束完整版。
- `<仓库>/.share/skills/bps-ci-quality-gates/`：12 条禁令详解、修复 diff 示例、MR 自检清单。
- `<仓库>/.share/skills/bps-flyway-migration/`：Flyway 双端幂等模板与命名规范。
- `<仓库>/.share/skills/bps-v6-gitflow/`：分支/MR/tag/main 完整流程。
- `<仓库>/.share/skills/bps-crud-code-generator/`：CRUD 模板 1-10 与平台工具 API。
- `<仓库>/.share/skills/bps-pretest-e2e/`：提测前 E2E 流程、上下文 header、断言分级。
- `<仓库>/.share/skills/bps-business-application-architecture/`：模块拆分、POM 设计、循环依赖治理。

## 触发示例

- 输入：「租赁台账添加资产数据源改造：打标签的自动同步、弹窗只看未打标签的、过滤五种状态」→ 先确认标签编码/弹窗接口/历史数据处理三个口径，再按已确认部分分批实现。
- 输入：「这个接口被很多地方调用，尽量不要影响原逻辑」→ 只加可选通用参数，缺省行为零变化，严禁业务专用开关。
- 输入：「getRentalAssetsToSync 性能太差，用 MyBatis-Plus 查询然后内存中过滤」→ MP 分页扫描 + 逐页内存过滤 + 扫描上限，删除自定义 XML。
- 输入：「还原 saveOrReuseForAsset 方法」→ 恢复原始实现与职责边界，清理夹带逻辑与过时用例。
- 输入：「修改完成后提交，然后合并成一个 commit」→ soft reset 到基点或 amend，单条约定格式提交，不 push。
- 输入：「新增一张业务表」→ Flyway 双端幂等脚本 + 实体/Mapper/Service/Controller 按模板生成，同步测试。

## 不适用场景

- 纯前端页面实现 → 按「文档与交付同步」规则输出交接文档，交前端 AI/开发者处理
- worktree 创建/修复、分支管理 → 使用 git-flow skill（含跨平台 Git 指针兼容处理）
- 标准 CRUD 全套生成 → bps-crud-code-generator（本 skill references 速查可辅助）
- 禅道 bug 修复全流程 → zentao-bugfix
- 技术设计文档编写 → bps-technical-design-doc
