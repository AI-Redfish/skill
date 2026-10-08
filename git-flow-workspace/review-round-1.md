# 评审记录 — 第 1 轮（2026-10-08 18:00 +0800）

## 机器检查
- checklist JSON: checklist-round-1.json（failed=0, warned=0, passed=23/23）
- warning 确认: 无 warning

## 设计评审（清单 A）
- 通过项：双闭环四要素完整内嵌且与参数决策表无矛盾（缺参→"进入理解闭环，
  一次只问一个"）；单一职责（仅 worktree 创建）；description 四要素齐
  （做什么+何时用+触发说法+边界）；不适用场景含近邻负例（删 worktree/当前区
  切分支/合并提交流程）；SKILL.md 179 行（<500），细节外置 troubleshooting.md
  且引用真实存在；输入输出契约表格式（必填/默认/必问项）；五段式结构完整，
  核心规则紧随双闭环放开头；步骤动词开头可判定（≥900s、/→_、同级目录）；
  触发示例 4 个格式统一含口语/信息缺失变体；防幻觉条款（BASE_NOT_FOUND
  不猜测替代分支、"不凭记忆猜测，先取证"）
- 问题清单：
  - A1 (P2)：触发示例第 4 条「删除 worktree」放在"触发示例"章节，与
    "不适用场景"有少量重叠。已接受：作为负向示例展示如何拒答，保留。

## 实现评审（清单 B）
- 通过项：subprocess list 传参无 shell 注入；错误三要素（error_code/message/
  hint）齐全；退出码 0/1/2 且 SKILL.md 有对照表；幂等守卫（PATH_EXISTS/
  BRANCH_EXISTS/BRANCH_CHECKED_OUT）；--dry-run 与 --reuse-branch 覆盖
  中断恢复场景；纯标准库；JSON stdout/日志 stderr；单测 12/12（正常/边界/
  错误三路径齐）
- 发现并已修复的问题：
  - B1 (P0)：INVALID_BRANCH_PATTERNS 中 `[/\\]` 对全名 search，会拒绝
    **所有含 `/` 的合法分支名**（本 skill 主场景）。单测暴露（8 failed）。
    修复：删除该 pattern，首字符检查由 startswith 覆盖，反斜杠单独拦截。
  - B2 (P1)：非法字符类正则 `[*?:\[\\]~^]` 中 `\]` 提前关闭字符类，导致
    `~ ^ ] \` 检测失效。修复为 `[*?:\[\]\\~^]`，新增用例 a*b/a~b/a^b/a[b
    /a]b/a\b 全部拦截。
  - B3 (P2)：argparse 会把以 `-` 开头的分支名当选项（stdout 无 JSON）。
    处理：测试与文档统一用 `--branch=<value>` 等号形式；git 本身不允许该类
    分支名，argparse 行为可作第一道防线，接受。
- 修复后复核：单测 12/12 OK；机器检查重跑 23/23。

## 负向验证（判据 3）
1. 「帮我把这个 worktree 删掉」→ 触发示例 4 + 不适用场景明确拒答，
   SKILL.md 核心规则 5 禁止删除操作 ✓
2. 「在当前工作区切到 dev 分支」→ 不适用场景第 2 条，不触发 ✓

## 错误路径演练（判据 4）
- BASE_NOT_FOUND：单测 test_base_not_found，exit=2 + JSON error_code ✓
- 非法输入：test_invalid_branch_names 16 组，全部 INVALID_BRANCH_NAME ✓
- 非仓库路径：test_not_a_git_repo ✓

## 边界抽查（判据 5）
- 空分支名 → INVALID_BRANCH_NAME ✓（单测）
- 合法多级名/中文分支名 → 通过校验 ✓（test_validate_branch_name）
- WSL 路径 /mnt/d/a/b → D:\a\b，非挂载路径返回 None ✓（test_to_windows_path）
- 路径含空格：subprocess list 传参，无 shell 拼接 ✓

## 需求对照（判据 6）
| 澄清记录 | 落实 |
|---|---|
| 同级目录 + / → _ 命名 | 核心规则 1/2 + 脚本 plan 字段 + 单测验证 |
| 基于远程基分支创建 | --base 必填 + rev-parse 校验 |
| 检出超时坑 | SKILL.md 实战坑 1 + 工作流步骤 3（≥900s）+ troubleshooting §7 |
| fetch 网络受限降级 | 默认跳过 fetch + --fetch 可选 + 降级本地引用（实战坑 2） |
| 中断恢复 | --reuse-branch + BRANCH_EXISTS 提示 + troubleshooting §1 + 单测 |
| WSL/Windows 路径 | 脚本双格式输出 + 实战坑 4 + 单测 |
| 范围不含删除 | 不适用场景 + 核心规则 5 |
| 无环境键 | 无 .env 相关内容（clarify 假设 4） |

## fresh eyes 复读（判据 7）
以第一次阅读视角通读 SKILL.md：工作流 4 步均可执行、引用的
references/troubleshooting.md 存在且 error_code 与脚本一一对应；
「参数决策指南」与「标准工作流步骤 1」的必问项一致，无歧义。

## 置信度自评
置信度自评：96%
- 判据1 机器检查: 通过（0 warning）
- 判据2 P0/P1: 无遗留（B1/B2 已修复并复核；B3、A1 为 P2 已记录接受理由）
- 判据3 负向验证: 通过（删除 worktree、当前区切分支 2 例）
- 判据4 错误路径: 通过（BASE_NOT_FOUND/非法输入/非仓库 3 场景）
- 判据5 边界抽查: 通过（空名/中文/多级名/WSL 路径/含空格路径）
- 判据6 需求对照: 8/8 全部满足
- 判据7 fresh eyes: 无歧义、无未定义引用
结论：放行（≥95%）
