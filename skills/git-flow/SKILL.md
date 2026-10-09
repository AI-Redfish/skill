---
name: git-flow
description: 基于指定远程分支创建 git worktree 并行开发工作区（同级目录、目录名=分支名中"/"换"_"）。当用户说"帮我新建一个 worktree"、"基于分支 xx 拉一个 worktree"、"从 dev/vx.x.x 拉个工作区/工作空间"、"创建分支工作区并新建分支"、"新开一个工作空间开发 xx 功能"时使用本 skill。不处理 worktree 删除/清理、当前工作区内切分支、跨分支合并与提交流程。
compatibility: Python 3.9+ 纯标准库（python/python3 直跑，零安装）；需 git ≥2.20；支持 Linux/macOS/Windows 与 WSL（自动转换 /mnt/<盘> 与盘符路径）。
metadata:
  author: AI-Redfish
  version: "1.1.0"
---

# git-flow — 基于远程分支一键创建同级 worktree 并行开发

## 双闭环流程（最高优先级，优先于其他默认行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环
1. 回答前先提问，**每次只问一个问题**，根据回答继续追问
2. 提问围绕：真实目标、背景、使用场景、输出对象、关键约束、优先级、
   成功标准、禁止事项、已有信息、可接受偏差
3. 对"用户真正想要什么"有 95% 信心才停止提问；未达 95% 只提问澄清，
   不给最终方案（用户消息已足以达到 95% 信心时可直接执行，
   但最终输出必须列出关键假设）

### 第二闭环：输出审查闭环
1. 形成答案后不直接输出，先自查：是否真正解决目标？是否遗漏关键约束？
   是否存在事实错误、逻辑漏洞、歧义、不可执行之处？
2. 发现问题→自行修正→再次审查，重复"审查—修正—再审查"，
   直到对输出结果至少有 95% 的准确性信心

### 最终输出要求
1. 先一句话复述用户真实需求
2. 再给出最终方案：明确、可执行、可直接使用
3. 说明关键假设、剩余不确定性，以及为什么已达到 95% 信心；
   不确定处明确标注，不假装确定

## 核心规则（最高优先级指令，必须遵守）

1. worktree 目录必须创建在**主仓库目录的同级**（父目录下），不得放入仓库内部
2. worktree 目录名 = 新分支名，其中所有 `/` 替换为 `_`（例：
   `v6.0.8.1/feature/zly-sharelease-20261008` → `v6.0.8.1_feature_zly-sharelease-20261008`）
3. 新分支必须基于用户指定的基分支（通常 `origin/<dev 分支>`）创建
4. **创建操作必须调用本 skill 的脚本**，不要手工拼接 git worktree 命令
   （脚本内含全部守卫与恢复逻辑）：
   `python3 <skill_dir>/scripts/worktree_create.py --repo <主仓库> --base <基分支> --branch <新分支> [--dry-run] [--fetch] [--reuse-branch]`
5. 新建worktree必须使用真实Git管理目录将 `.git` 的 `gitdir:` 和管理目录中的 `gitdir` 回指针写为相对路径，统一 `/` 分隔符；创建脚本自动处理，不按目录名猜测管理目录。Linux/macOS单环境也使用相对路径；Windows/WSL共用时须在同一Windows盘，跨盘或仅WSL可访问的布局不得声称双环境兼容。
6. 禁止执行任何删除类操作（`git worktree remove`、`git branch -D`、rm 目录），
   恢复场景中涉及删除的一律先向用户确认

## 路径与输出位置约定

- `<skill_dir>` 指本 SKILL.md 所在目录；脚本一律带 `<skill_dir>` 前缀调用
- 产物（新 worktree）位置由核心规则 1/2 决定，不在 skill 目录内产生任何文件
- 用户消息中的路径可能为 Windows 格式（`D:\...`），bash/WSL 环境需转换为
  `/mnt/d/...`；向用户汇报时转换回 Windows 格式

## 使用前提（首次自检）

- `git --version` 可用且 ≥2.20；`python3 --version` ≥3.9（或 `python`）
- 在主仓库内执行（或通过 `--repo` 指定主仓库路径）
- 自检失败时：提示用户安装 git/python 后重试，不得改用手工命令绕过守卫

## 标准工作流

1. **收集参数**：核对用户消息中的「基分支」「新分支名」两项；
   缺失任一项 → 进入理解闭环，**一次只问一个**（先问基分支：
   "基于哪个分支创建？"，通常为 `origin/dev/vx.x.x`；再问新分支名）
2. **dry-run 预览**：执行脚本带 `--dry-run`，将 JSON 中 `plan` 展示给用户
   （目录名、路径、分支、基分支 commit）；信息完整时可直接进入下一步，
   但需在最终输出中列出关键假设
3. **正式创建**：去掉 `--dry-run` 执行；**工具超时必须设置 ≥900 秒**
   （大型仓库在 Windows/WSL 挂载盘检出上万文件需数分钟，详见下方实战坑）
4. **验证汇报**：按退出码与 JSON 结果，使用「输出规范」模板向用户汇报；
   用 `git worktree list` 确认新条目存在，并检查 JSON `data.plan.compatibility`。脚本验证根目录、分支、HEAD；WSL挂载盘上可找到Windows `git.exe` 时自动交叉验证。未安装另一端Git时明确列出 `not-checked`，不能当作已验证。

已有worktree只读检查：`python3 <skill_dir>/scripts/worktree_paths.py --repo <worktree>`。
用户已授权修复时加 `--repair`；只改两个指针，验证失败恢复原始字节，不删除工作区、不重建分支。
Windows创建后需要WSL使用时，从WSL再运行只读检查；Windows脚本不自动启动WSL发行版。
IDEA不显示Git时先验证IDE使用的Git，再检查Directory Mappings；不把IDE配置文件自动加入每个新工作区。

## 参数决策指南

| 决策点 | 默认 | 说明 |
|---|---|---|
| 基分支 `--base` | 无默认 | **必问项**；用 `git branch -r` 帮用户确认存在性 |
| 新分支名 `--branch` | 无默认 | **必问项**；推荐格式 `<版本>/feature\|fixbug/<缩写>-<主题>-<yyyymmdd>` |
| 主仓库 `--repo` | 当前目录 | 当前目录不明确时先问用户确认是哪个仓库 |
| fetch 最新 `--fetch` | 不 fetch | 网络受限时 fetch 常超时；默认用本地 `origin/*` 引用，`git log <base> -1` 展示引用时间供用户判断是否需要 `--fetch` |
| 中断恢复 `--reuse-branch` | 不启用 | 仅当脚本报 `BRANCH_EXISTS` 且用户确认是中断残留时使用 |
| 检出方式 | 全量检出 | 不做 sparse-checkout，除非用户明确要求 |

## 错误处理

| 退出码 | error_code | 含义 | 处理 |
|---|---|---|---|
| 0 | — | 成功 / dry-run 成功 | 按「输出规范」汇报 |
| 2 | NOT_A_GIT_REPO | 路径不是仓库 | 确认 --repo 或 cd 到仓库内 |
| 2 | INVALID_BRANCH_NAME | 分支名非法 | 按脚本 message 修正后重试 |
| 2 | PATH_EXISTS | 目标目录已存在 | 中断残留→用户确认后清理（需用户同意）；误建→换名 |
| 2 | BRANCH_EXISTS | 本地分支已存在 | 确认为中断残留后加 `--reuse-branch` 重试 |
| 2 | BRANCH_CHECKED_OUT | 分支已被其他 worktree 占用 | 换分支名或改在现有 worktree 开发 |
| 2 | BRANCH_NOT_FOUND | --reuse-branch 但分支不存在 | 去掉该参数重试 |
| 2 | BASE_NOT_FOUND | 基分支不存在 | `git branch -r` 核对；注意 origin/ 前缀 |
| 2 | WORKTREE_COMPATIBILITY_FAILED | 已创建但跨平台验证失败 | 保留目录与分支，诊断并显式修复，不重复创建 |
| 1 | WORKTREE_ADD_FAILED | git 执行失败 | 读 stderr 的 git 原始错误；中断恢复见 references/troubleshooting.md |

详细排查步骤（含中断恢复、残留清理、fetch 超时、WSL 路径）：
读 <skill_dir>/references/troubleshooting.md，按 error_code 查表执行，不凭记忆猜测。

## 实战坑（来自真实生产环境，必读）

1. **检出超时**：万级文件仓库在 Windows/WSL 挂载盘（/mnt/d）上全量检出实测约
   6 分钟；工具调用超时 <900s 会导致进程被杀、目录被 git 回滚。**永远设置 ≥900s**
2. **fetch 网络超时**：内网 GitLab fetch 单分支也可能超 120s；默认跳过 fetch、
   使用本地 `origin/*` 引用（用 `git log <base> -1 --format=%ci` 展示引用新鲜度）
3. **中断恢复**：`worktree add` 被中断后典型状态是"分支已建、目录已回滚"，
   此时**不要**重新 `-b` 建分支，直接用 `--reuse-branch` 复用残留分支
4. **WSL 路径双轨**：命令参数与Python宿主系统一致，不能把WSL绝对路径写入Windows IDE要读取的Git指针；命令里用 `/mnt/d/...`，对用户汇报用 `D:\...`；
   脚本 JSON 已同时输出两种格式（`worktree_path` / `worktree_path_windows`）

## 输出规范

- 脚本必须带标准参数执行；结果 JSON 自动到 stdout，不要二次包装
- 成功后按以下模板汇报（占位符从脚本 JSON `data.plan` 取值）：

```
✅ Worktree 创建成功
- 目录：<worktree_path_windows 或 worktree_path>
- 分支：<branch>（基于 <base> @ <base_commit 前 12 位>）
- 验证：git worktree list 已包含新条目 <worktree_name>
```

- 汇报前自查：路径同级？目录名已将 `/` 换 `_`？分支基于正确基分支？
  同时核对相对指针、原生Git验证、另一端验证/未验证说明。
  任一已要求的验证失败即未达 95% 信心，回到输出审查闭环修正

## 触发示例

- 「帮我新建一个worktree，基于分支：origin/dev/v6.0.8.1，新分支名称：
  v6.0.8.1/feature/zly-sharelease-20261008」→ 信息完整，直接走标准工作流
- 「从 dev/v6.0.7.0 给我拉一个工作区，分支叫 fixbug/abc-75339」→ 基分支补
  origin/ 前缀后执行
- 「新开个空间开发共享租约功能」→ 缺基分支与新分支名，理解闭环先问：
  「基于哪个分支创建？」（一次只问这一个）
- 「帮我把这个 worktree 删掉」→ 不适用场景，说明后引导用户使用
  `git worktree remove`（需用户自行确认）

## 不适用场景

- worktree 删除/清理（`git worktree remove|prune`）与分支删除
- 在当前工作区内切换/新建分支（`git checkout -b`/`git switch -c`）
- 跨 worktree 合并、rebase、提交 MR/PR 的流程编排
- 子模块批量更新、仓库迁移、bare 仓库管理
