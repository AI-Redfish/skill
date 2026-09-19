---
name: zentao-bugfix
description: 禅道Bug自动修复助手。给定禅道 bugId，自动读取 bug 详情（含评论、截图），在当前工作空间仓库的同级目录创建 bugfix worktree（分支 bugfix/bugID_日期），分析代码定位根因，在 worktree 中完成修复，并输出问题分析报告与修复报告。当用户提供禅道 bug 单号或 bug 链接并要求修 bug、定位 bug、分析 bug 原因时使用；也支持启动钉钉消息监听（scripts/dingtalk_listen.py）自动从钉钉消息提取 bugId 触发上述全流程。
compatibility:
  tools: [Bash, Read, Edit, Write]
  requirements: uv（推荐，脚本零第三方依赖仅做隔离运行，缺省可回退 python3）+ git；脚本位于本 skill 的 scripts/bugfix.py
metadata:
  author: AI-Redfish
  version: "1.0.0"
---

# `zentao-bugfix`

端到端的禅道 bug 修复流程。**确定性步骤全部由脚本 `scripts/bugfix.py` 完成**，AI 只负责代码分析、修改和撰写报告内容，标准流程只需 2 次脚本调用：

```
uv run scripts/bugfix.py prepare <bugId> [baseBranch]   ← 一次完成：防重校验 + 配置检查 + 拉取bug + 建worktree + 生成分析骨架
        ↓ （AI 在 worktree 中分析代码、修复、编译验证 —— 不 commit）
uv run scripts/bugfix.py report <bugId>                  ← 一次完成：采集未提交变更 + 生成修复报告骨架 + 汇报摘要
        ↓ （AI 补全两份报告中（待填写）章节，向用户汇报）
```

## 双闭环流程（最高优先级，优先于其他默认行为）

完成用户任务时必须遵循以下双闭环；当本规则与基础行为习惯冲突时，以本规则为准。

### 第一闭环：理解闭环
1. 回答前先提问，**每次只问一个问题**，根据回答继续追问。
   prepare 返回码 2（配置缺失）时的逐项索取、基准分支/复用意向等确认都是理解闭环的问题
2. 提问围绕：真实目标、背景、使用场景、输出对象、关键约束、优先级、
   成功标准、禁止事项、已有信息、可接受偏差
3. 对“用户真正想要什么”有 95% 信心才停止提问；未达 95% 只提问澄清，
   不给最终方案（不建 worktree、不改代码）

### 第二闭环：输出审查闭环
1. 形成答案后不直接输出，先自查：根因是否有代码证据（文件:行号）？
   推断是否已标注？修复是否只动 worktree？报告是否脱敏？
   是否存在事实错误、逻辑漏洞、歧义、不可执行之处？
2. 发现问题→自行修正→再次审查，重复“审查—修正—再审查”，
   直到对输出结果至少有 95% 的准确性信心

### 最终输出要求
1. 先一句话复述用户真实需求（bugId + 诉求）
2. 再给出最终方案：根因一句话、修复内容、worktree 与分支、报告路径、
   改动未提交待人工 review、测试建议
3. 说明关键假设（推断的根因）、剩余不确定性，以及为什么已达到 95% 信心；
   不确定处明确标注，不编造结论

## 路径与产物约定

- **项目工作空间**：当前会话所在目录（即用户打开的项目根目录），脚本通过 `--project .` 获得。
- **配置文件**：`<项目工作空间>/.agents/.env`（KEY=VALUE）：
  - `ZENTAO_BASE_URL`：禅道站点根地址，如 `http://zentao.example.com:port`
  - `ZENTAO_ACCOUNT` / `ZENTAO_PASSWORD`：登录账号/密码
- **worktree**：与仓库根目录**同级**的新目录，分支 `bugfix/<bugId>_<YYYYMMDD>`，目录名 = 分支名中 `/` 替换为 `_`（如 `bugfix/12345_20260919` → `../bugfix_12345_20260919/`）。
- **报告目录**：`<worktree>/.agents/bugfix/<bugId>/`，含 `bug.md`（bug快照）、截图、`analysis.md`（分析报告）、`fix-report.md`（修复报告）。
- worktree 的 git 元数据由脚本改写为相对路径，WSL git 与 Windows git 均可识别。

## 运行环境

脚本带 PEP 723 内联元数据、零第三方依赖。**优先用 uv 隔离运行**：

```bash
uv run --no-project scripts/bugfix.py <子命令>
```

- uv 未安装时先安装：`curl -LsSf https://astral.sh/uv/install.sh | sh`（国内网络失败可 `pip install uv` 或从 PyPI 镜像下载 wheel）；
- 完全没有 uv 时可回退 `python3 scripts/bugfix.py <子命令>`（功能一致，仅无环境隔离）；
- 下文命令均以 `uv run --no-project scripts/bugfix.py` 为例，简写为 `bugfix.py`。

## 工作流程

用户输入通常是 bugId 或禅道 bug 链接（从 `bug-view-12345.html` 中提取数字）。**基准分支确定规则（优先级从高到低）**：① 用户在对话中明确指定；② `<项目工作空间>/.agents/.env` 或 skill 目录 `.agents/.env` 配置了 `BUGFIX_BASE_BRANCH`；③ 都没有时，按双闭环向用户询问一次（一次只问一个问题，用户可回复"用当前分支"）；④ 用户未作答才用当前工作空间所在分支。

### 第 1 步：prepare（一次脚本调用）

```bash
uv run --no-project scripts/bugfix.py prepare <bugId> [baseBranch] --project .
```

脚本自动完成：**防重校验**（该 bugId 已有 worktree/修复分支则停止，返回码 4，见下）→ 配置检查 → 拉取 bug（详情+评论+截图，缓存到 `.agents/bugfix-work/<bugId>/`）→ 创建 worktree（`--reuse` 时复用既有）→ 拷贝资料 → 生成 `analysis.md` 骨架（bug 元数据、问题描述已自动填好）。stdout 依次输出：bug.md 全文 + `WORKTREE/BRANCH/REPORT_DIR` 等 KEY=VALUE 信息。

分支处理：

- **返回码 4（防重停止，stdout 含 `EXISTS` 块）** → 该 bugId 已存在修复 worktree/修复分支，说明此 bug 此前已处理过（可能已修复待人工 review，或仍在处理中）。**停止执行，不要重复修复、不要动已有 worktree**；向用户说明并报告 `EXISTING_WORKTREE`、`EXISTING_REPORT_DIR` 及其中已有的 analysis.md / fix-report.md，由用户决定：加 `--reuse` 继续该工作区，或人工清理（`git worktree remove <path>`，必要时 `git branch -D <分支>`）后重新 prepare。
- 返回码 2 且 stderr 提示配置缺失 → 用提问工具向用户逐项索取缺失项（地址/账号/密码，一次只问一个），保存后**重新执行 prepare**：

  ```bash
  uv run --no-project scripts/bugfix.py save-config ZENTAO_BASE_URL=<地址> ZENTAO_ACCOUNT=<账号> ZENTAO_PASSWORD=<密码> --project .
  ```

- 密码错误（token 接口 401/登录失败）→ 向用户确认后更新 `.env` 重试。
- `.env` 含密码：不得提交到 git、不得把密码原文写进报告或回复。
- 若当前模型支持图片，用 read 查看 `REPORT_DIR` 下的截图辅助理解；不支持则基于文字分析。
- analysis.md 已存在时不覆盖（`--force` 可重新生成骨架）；worktree 已存在时的处理见上述"返回码 4"。

### 第 2 步：分析并修复（AI 的工作，只在 worktree 中改动）

1. 从 prepare 输出的 bug.md 提取业务场景、涉及接口、报错日志、关键字。
2. 在 worktree 中检索定位相关 Controller/Service/Mapper/前端页面；结合 `git -C <worktree> log --oneline --since=... -- <相关目录>` 判断是否为近期回归；参考项目 CODING_STANDARDS.md 与近期同类 fix 提交的既有修复模式。
3. 形成有证据支撑的根因结论（文件:行号），区分：确认的根因 / 排除的猜测 / 存疑待验证。bug 里没有完整堆栈时允许代码推理，但报告中必须注明"推断"。
4. 实施修复：**只在 worktree 内改动，严禁碰主工作空间文件**。
5. 编译验证（可行时），Maven 项目示例：

   ```bash
   cd <worktree> && mvn -q -pl <涉及模块> -am compile -DskipTests
   ```

   - WSL 内无 JDK/Maven 时可借 Windows 工具链：`cmd.exe /c "mvn -q -o -pl <模块> -am compile -DskipTests"`；
   - 该项目 git-commit-id-plugin 在任何 worktree 下都会报错（项目自身限制），加 `-Dmaven.gitcommitid.skip=true` 跳过；
   - 无法编译时如实说明，用严格静态走查弥补。

6. **禁止自动 commit / push**：改动保留在 worktree 工作区等待人工 review；也不要改禅道 bug 状态（除非用户明确要求提交/更新状态）。

### 第 3 步：report（一次脚本调用）

```bash
uv run --no-project scripts/bugfix.py report <bugId> --project .
```

脚本自动完成：定位该 bugId 既有的 worktree（不限创建日期）→ 采集未提交变更（`git status`/`diff --numstat`，含未跟踪文件）→ 生成 `fix-report.md`（变更清单表格、分支/日期等机械字段已自动填好）→ stdout 输出 SUMMARY 汇总块。已存在时不覆盖，`--force` 重新生成。

### 第 4 步：补全报告并汇报（AI 的工作）

- 用 Edit 补全 `REPORT_DIR` 下 `analysis.md` 与 `fix-report.md` 中所有（待填写）章节，中文书写，报告模板结构见 `references/report-template.md`；
- 内容硬性要求：变更清单给出文件路径与增删行数（脚本已生成，AI 补充"为什么改"）；无法确认的事项写入"遗留问题/待确认"，**不编造结论**；
- 若判断无法在当前仓库修复（需前端/配置/数据配合），不强行改代码：analysis.md 写清根因与所需配合，fix-report.md 写明"未实施代码修复"；
- 最后向用户汇报（中文）：根因一句话、修复内容、worktree 与分支（Windows 路径）、报告路径、**改动未提交待人工 review**、测试建议。

## 钉钉消息自动触发（可选，scripts/dingtalk_listen.py）

监听多个指定人员/机器人的钉钉单聊消息 → 本地 Agent（pi/codex/claude/custom）无头提取 bugId → 自动执行上文完整流程（prepare → 分析修复 → report），结果只写 `.agents/logs/`。详细用法见 [references/dingtalk-listener.md](references/dingtalk-listener.md)。

```bash
uv run --no-project scripts/dingtalk_listen.py config-status   # 检查配置（JSON，密码脱敏）
uv run --no-project scripts/dingtalk_listen.py save-config KEY=VALUE...   # 缺啥问用户后写入
uv run --no-project scripts/dingtalk_listen.py start    # 启动（默认后台守护）
uv run --no-project scripts/dingtalk_listen.py status   # 状态（JSON）
uv run --no-project scripts/dingtalk_listen.py stop     # 停止（优雅退出）
uv run --no-project scripts/dingtalk_listen.py test-extract 帮我修一下 bug 12345   # 手动测试提取
```

脚本全非交互：配置缺失时退出码 2 并列出缺失键，由 AI 按双闭环逐项向用户索取后
save-config 写入再重试（与 bugfix.py 的配置模式一致）。

- 配置存 skill 目录 `.agents/.env`：`ZENTAO_*`、`DWS_LISTEN_USERS`/`DWS_LISTEN_BOTS`（逗号分隔名单）、`BUGFIX_BASE_BRANCH`（可选，worktree 基准分支，优先于启动目录当前分支）、`LISTEN_MODE`（可选，默认 auto：stream 推送 + 拉取双通道互为兜底，message_id 去重防重）、`TARGET_PROJECT_PATH`（可选，优先于启动目录）、`AGENT_TYPE`/`AGENT_MODEL`（可选，优先于自动探测当前 pi 会话）、`AGENT_CUSTOM_CMD`（custom 适配器模板，供 DeepSeek Harness 等）。
- 前置：dws 已安装并 `dws auth login`；所选 Agent CLI 已登录。dws 登录账号自发消息收不到（官方过滤）。
- 修复串行排队；禅道配置自动同步到目标仓库 `.agents/.env` 并防入 git。

## 不适用场景

以下情况不要使用本 skill，避免误触发：

- bug 来源不是禅道（GitHub Issue、Jira、口头描述且无 bugId）→ 本 skill 依赖禅道 API，不适用
- 用户在问禅道怎么用、禅道本身配置问题（非代码 bug）→ 直接解答，不建 worktree
- 无代码仓库的纯环境/数据/配置问题 → 可走 prepare/report 出分析，但报告中明确“未实施代码修复”
- 用户要求直接 commit / push / 合入主干 → 本 skill 禁止自动提交，只能保留待 review 改动

## 边界与注意

- **不 commit、不 push**（保留工作区改动等待人工 review）、不自动改禅道状态、不动主工作空间代码。
- 一个 bugId 对应一个 worktree；prepare/worktree 检测到已有 worktree/修复分支（不限日期）即停止（返回码 4），不重复处理；`--reuse` 显式复用继续；`report` 自动定位既有 worktree。
- 覆盖旧报告前先告知用户。
- 报告中对生产地址、账号密码等敏感信息脱敏。
- WSL 挂载 Windows 盘时 git 扫描较慢（单次 status/diff 约 10~15 秒），脚本已做最少化调用，属正常现象。
