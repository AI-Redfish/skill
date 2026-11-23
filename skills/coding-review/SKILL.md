---
name: coding-review
description: 通用 coding-review（代码审查）规范，持续迭代中。两种审查模式：① 变更审查——基于 Git diff 的行级审查，集成阿里开源 ocr CLI（open-code-review）做确定性文件筛选与规则匹配，适合代码变更、增量复查、提交前自查；② 全量静态安全审查——BPS（basic-platform-service，Java 多模块 + Redis/MySQL/RocketMQ/MinIO）专项：Redis 滥用（KEYS 命令/永久 key/凭据硬编码）、MySQL 事务与 SQL 注入面、索引核对（对照 basic-platform-service-sql 归档）、前后端接口抽查（对照 wukong 前端仓库）、MQ 中间件及自主扩展角度（上传下载、日志泄漏、依赖停维、越权抽查），产出双格式（Markdown + HTML）审查报告到 .agents/out/coding-review/。当用户要求"代码审查""code review""coding review""变更审查""diff 审查""检查这次改动""增量复查""检查项目安全隐患""安全审查""代码安全扫描""审查 Redis/MySQL/MQ 使用是否不当""核对索引是否缺失"时使用。不适用于：运行时渗透测试（无运行环境探测）、依赖漏洞 CVE 全量比对（需联网 OSV/NVD）、修复代码本身（审查通过后由用户另行安排修复）。
compatibility: 变更审查模式优先使用 `ocr` CLI（`npm install -g @alibaba-group/open-code-review`，需 Git >= 2.41）；未安装时降级为纯 git diff + 本规范流程。BPS 安全专项依赖 scripts/check-missing-indexes.py 等脚本（Python 3.9+ 纯标准库）；索引核对需本地存在 D:/develop/project/basic-platform-service-sql 归档仓库；接口抽查需前端仓库 D:/develop/project/wukong。适用于 BPS 主仓库 release 或 dev 分支基线。
metadata:
  author: AI-Redfish
  version: "3.0.0"
  source: v2.x 三轮 BPS 安全审查沉淀（基线 release@1d2cf4e513，已验证可复现）；v3.0 参考阿里开源 alibaba/open-code-review——方法论（精准优先、两段式规则、确定性流程）与工具（ocr CLI 委托模式集成）。
---

# Coding Review 规范

本文是通用 coding-review 操作规范。何时读：用户要求代码审查、变更审查、安全隐患审查、Redis/MySQL/MQ 使用核查或索引缺失核对时。

按需读取：
- 变更审查模式操作细节（ocr CLI 工作流、自定义规则、故障处理）→ references/ocr-cli.md
- BPS 全量安全审查全部规则与命令（10 个方向、复查模式、已知边界）→ references/bps-security.md

## 审查总则（所有模式通用，优先级最高）

借鉴 alibaba/open-code-review 设计理念：以精准度换低噪声，确定性工程约束流程，Agent 只负责动态决策与上下文召回。

1. **精准优先**：宁可漏报，不可误报。上下文无法确认的问题不写入报告正文，列入「待确认」。
2. **证据前置**：模式命中只是线索。必须读完整上下文、追调用链后再下结论；脚本自动结论必须抽查 3-5 项人工复核后才写入报告。
3. **全覆盖**：审查清单内每个文件必须标记 reviewed 或 skipped（附原因），禁止抽查式偷懒、禁止找到第一个高危就停。
4. **定位精确**：每个发现精确到 `文件:行`。定位失败时读文件确认上下文，仍无法定位则降级为文件级并注明。
5. **两段式规则**：每个检查点同时写明「应报告」与「不应报告」；不应报部分是误报甄别的第一道闸。
6. **静默丢弃误报**：复核确认的误报不进报告，不占读者注意力；有争议的降级为「待确认」。
7. **正面样本也记录**：报告中体现做得好的部分，保持平衡。

## 模式选择

| | 变更审查 | 全量静态审查 |
|---|---|---|
| 适用 | diff 范围：工作区改动、分支对比、单提交、增量复查 | 整个代码库或模块的安全隐患扫描 |
| 引擎 | ocr CLI 委托模式（宿主 agent 执行）或纯 git diff | 本规范流程 + Python 脚本 |
| 规则来源 | ocr 规则系统 + references/ocr-cli.md | references/bps-security.md |
| 输出 | 行级 findings，按严重度分组，含覆盖率 | 双格式报告（Markdown + HTML） |

选择规则：
- 用户说「审查这次改动 / diff / 提交 / 增量复查」→ 变更审查。
- 用户说「安全审查 / 全量扫描 / 检查项目隐患」→ BPS 专项全量流程。
- 全量审查后的「复查」（基线 commit 未变）→ 复查模式，见 references/bps-security.md「复查模式」节，不重跑全量。

## 通用流程（确定性五步）

1. **筛选**：产出审查文件清单。变更审查用 `ocr delegate preview --format json`（无 ocr 时 `git --no-pager diff --name-only`）；全量审查按 BPS 专项各方向的 grep 模式产出命中清单。
2. **打包**：关联文件归并为同一审查单元再读（同一功能的 Controller/Service/Mapper、同一表的 Mapper XML 与建表 SQL、同一配置的 Java 常量与 yml），避免孤立看单文件漏掉上下文。
3. **规则匹配**：按文件类型套用对应检查点（Java 侧 / Mapper XML / pom / 配置文件各有规则），一次专注一类规则，防止注意力分散。
4. **审查与定位**：逐单元审查。命中模式后读上下文、追调用链；发现按 `文件:行` 定位，标注 category（bug/security/performance/maintainability/test/style/documentation/other）与 severity（critical/high/medium/low）。
5. **反思**：报告前自检——覆盖率是否 100%（reviewed + skipped）；每个发现是否有证据支撑；抽查 3-5 项到源码/归档原文复核；误报是否已剔除。

## 报告输出规范

### 变更审查输出

- findings 按严重度分组：Critical/High（bug、安全、数据丢失风险，必报）→ Medium（性能、错误处理缺口，带上下文报）→ Low（仅明确有价值时报）。
- 汇总必须含 total_files / reviewed_files / skipped_files / coverage_rate；skipped 必须附原因。
- 实质行为变化（即使无缺陷，如删除公共参数）单独说明：受影响工作流、前后行为、证据位置。

### 全量审查输出（BPS 专项）

- 位置：`.agents/out/coding-review/security-review-<YYYY-MM-DD>.md` 与同名 `.html`，内容一致（用户已确认此约定）；同日复查加 `-r2`/`-rN` 后缀，不覆盖既有报告。
- 结构：元信息（基线 commit、方式）→ 风险总览表（编号 H/M/L + 文件:行）→ 分方向详述（每项：证据代码、影响、建议）→ 正面样本 → 修复优先级（立即/短期/中期）→ 覆盖范围与未覆盖项。
- 分级标准：高=可远程利用或凭据泄漏；中=性能劣化/防御缺失/停维组件；低=规范偏差/触发条件苛刻。
- 未覆盖项必须如实列（Nacos 实际配置、运行时实测等），不确定性明说，不编造。
- HTML 自包含样式（内联 CSS），风险标签色块（高红/中黄/低蓝/正面绿）。

### 修复交付格式（用户已确认）

- 每个审查点独立小节，固定三段标签 `**问题原因**` / `**影响**` / `**修复建议**`，保留一行一项的风险总览表。
- 密码轮换、Nacos 配置、EXPLAIN 实测、部署实例数确认等运维动作单列「需运维配合」清单，不混入代码修复项。

## 输出精简约束与产物 git 托管指定（所有落盘产物与答复通用）

1. **只落盘有用的**：只把用户会直接使用的产物写到磁盘；过程稿、中间草稿、重复副本一律不落盘。
2. **中间产物隔离**：确需保留的中间产物收进 `.agents/out/coding-review/`（非 git 托管产物目录），不与交付产物混放。
3. **落盘前自问**：写文件前先问「用户会直接使用它吗」；不会就不写，改为文字说明。
4. **答复同理**：汇报只讲结论、路径、风险与待办，不复述中间过程与脚本日志。
5. **产物 git 托管指定**：审查报告（Markdown 与 HTML）不需要被 git 管理，输出到 `<工作目录>/.agents/out/coding-review/`；不生成用户没要的总结或分析文件。

## 验证与交付

1. 脚本结论抽查 3-5 项到 SQL 归档原文核对（主键、现有索引），确认无误报后才写入报告。
2. 报告写完后复跑脚本确认可复现。
3. 交付只列变更文件、核心发现摘要、未覆盖项与风险，不粘贴报告全文。
