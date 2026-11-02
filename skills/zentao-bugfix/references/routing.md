# Bug 修复位置配置

将 `assets/routes.example.json` 复制到被修复项目的 `.agents/zentao-bugfix/routes.json`，填写 config 并修改 rules 中的真实目录和分支。该文件统一保存原 `.env` 配置与匹配规则；没有规则时使用默认独立 worktree 流程，禅道访问仍须配置账号。监听器不自动生成包含虚构目录的生效规则。

```json
{
  "config": {
    "ZENTAO_BASE_URL": "https://zentao.example.com",
    "ZENTAO_ACCOUNT": "你的账号",
    "ZENTAO_PASSWORD": "你的密码",
    "BUGFIX_BASE_BRANCH": "release",
    "FRONTEND_WORKSPACES": "D:/projects/tenant-web",
    "DWS_LISTEN_USERS": "李四,张三",
    "AGENT_TYPE": "pi",
    "AGENT_MODEL": "provider/model",
    "LISTEN_MODE": "auto",
    "POLL_INTERVAL_SECONDS": "20",
    "LISTEN_AUTOSTART": "on",
    "AUTO_PR": "off",
    "AUTO_PR_BASE_BRANCH": "",
    "AUTO_PR_REMOTE": "",
    "AUTO_PR_CMD": "",
    "AUTO_PR_DRAFT": "off"
  },
  "rules": [
    {
      "name": "指定 Bug",
      "match": {"bug_id": "12345"},
      "workspace": "D:/projects/order-service",
      "target_branch": "feature/order",
      "auto_pr": true
    },
    {
      "name": "订单改造测试",
      "match": {"title_contains": "订单改造"},
      "workspace": "D:/projects/order-service",
      "target_branch": "feature/order",
      "auto_pr": false
    }
  ]
}
```

## 配置与迁移

- `config` 保存全部原 `.env` 配置键，值必须为字符串，包括秒数和 on/off。完整键列表见 assets/routes.example.json 与监听文档。
- `FRONTEND_WORKSPACES`（可选）是前端只读分析工作区，多个用英文逗号分隔，支持绝对路径与项目相对路径。它只用于在 `analysis.md` 中判定「前端问题还是后端问题」，不参与分流、不是修复目标：脚本不写入、不暂存、不提交、不切分支。修复后端 Bug 时在这里配置前端仓库（如 `D:/develop/project/wukong`）；修复前端 Bug 时也可以反向配置后端仓库地址。该键从被修复项目的路由文件读取；留空时分析报告必须写明前端归属无法用本地代码验证。
- `rules` 保存原匹配规则，可为空；只有 rules 的旧 JSON 仍可读取规则，config 视为空。只使用线上/default worktree 时可配置 `"rules": []`。
- 脚本不再读取旧 `.env`，也不自动从旧文件获取密码。把原 KEY=VALUE 写成 `"KEY": "VALUE"` 加入 config；JSON 中 Windows 路径使用 `/` 或转义反斜杠 `\\\\`。
- `save-config KEY=VALUE...` 命令仍可使用，写入 routes.json 的 config 并保留规则及其他配置。禁止用只含 config 的新文件覆盖已有 rules。
- 自动发起 PR 的 config 键（均可选，详见下文「自动发起 Pull Request」）：`AUTO_PR`（on/off，默认 off）、`AUTO_PR_BASE_BRANCH`、`AUTO_PR_REMOTE`、`AUTO_PR_CMD`、`AUTO_PR_DRAFT`。
- 手动修复从 `--project` 的 routes.json 读取 config；监听从启动工作区读取 config。TARGET_PROJECT_PATH 指向其他项目时，只把 ZENTAO_* 合并到目标 config，目标项目 rules 独立保留。
- 生效 routes.json 可含密码，保留为本地文件，不纳入代码提交；config-status 只展示脱敏密码。

## 匹配约定

- 每条规则只使用 `bug_id` 或 `title_contains` 其中一种条件，不支持任务、需求、迭代等字段；可选布尔字段 `auto_pr` 配置该 workspace 修复后是否自动发起 PR（缺省回退 config `AUTO_PR`，非布尔值报配置错误）。
- `bug_id` 为数字字符串，精确匹配；命中 ID 后不再考虑标题规则。
- `title_contains` 为非空字符串，针对禅道接口返回的实际标题做普通子串匹配。英文忽略大小写；不使用正则、不自动分词、不读取钉钉消息作为标题。
- `workspace` 为已有 Git 工作区根目录，推荐绝对路径；相对路径基于配置所在项目根目录。WSL 支持将 `D:/...` 或 `D:\\...` 转换为 `/mnt/d/...`。
- `target_branch` 是工作区必须已检出的 Git 分支名，不是新 worktree 基准分支。
- 同一优先级命中相同目标视为一次命中；命中不同目标视为冲突，记录原因并创建独立 worktree。同目标多条规则的 `auto_pr` 不一致时以第一条命中为准（Bug ID 优先于标题）。未命中也默认创建 worktree。
- 无效 JSON、未知字段、空关键字视为配置错误，不自动猜测。

## 匹配后工作区异常

目录不存在、不是 Git 根目录、当前分支不一致或处于合并/变基时，停止该 Bug；不创建目录、不切分支、不回退 worktree。HTML 报告写到当前工作区：

```text
.agents/zentao-bugfix/<bugId>/errors/<运行标识>/report.html
```

自动打开默认浏览器（WSL 优先 Windows），失败也保留 HTML，并在同目录 report.json、监听 status.last_fix 中记录原因。目录错误修正后可重新发送新消息，或执行：

```bash
python <skill_dir>/scripts/dingtalk_listen.py retry <bugId>
```

不受先前 message_id 去重影响。手动 prepare 默认当前工作区为 `--project`，`--current-workspace` 可显式指定。

## 顺序修复与提交

同一仓库/分支和同一工作区均以持久锁互斥。绑定模式依次执行 prepare → 补全分析/方案 → ready → 修复 → report/补全 → finish。finish 执行验证、为一个 Bug 创建一个 commit、记录提交结果，然后释放锁。下一 Bug 才能开始。

失败不自动清锁，监听器把后续等待任务保存在 `.agents/logs/pending-bugs.json`；可继续处理其他未占用的工作区。恢复前一 Bug 使用 retry 或 `prepare <bugId> --reuse`，沿用原始快照，避免把未完成修复误当开发改动。

绑定模式可以保留其他文件上的暂存、未暂存和未跟踪开发内容。自动修复不触碰已有变更文件；混合修改同一文件时暂停，不尝试猜测哪些行属于本 Bug。禁止全量暂存、自动 stash/reset、绕过 hook 或自动 push（auto_pr 开启时的 create-pr 除外，见下文）。

每个 Bug 仍有独立分析/方案/修复报告和 commit ID。确认无代码改动可通过验证后标记 no_change，不生成空提交。

## 自动发起 Pull Request

是否修复后自动推送并发起 PR 完全由 routes.json 决定，默认关闭：

- **规则级**（按 workspace 逐规则配置）：规则内布尔字段 `"auto_pr": true/false`。适合同一项目里
  不同工作区/分支采用不同的交付方式（如 feature 分支自动 PR、release 分支仅本地提交）。
- **config 级**（全局默认）：`AUTO_PR`（on/off，默认 off）。规则未写 `auto_pr` 时回退此值；
  未命中任何规则（独立 worktree 流程）也只看此值。规则显式值始终优先于 config。
- 开启即视为用户预先授权 push 与创建 PR；禅道状态仍不自动修改，也不 force push。

修复完成后（绑定模式 finish 提交成功；worktree 模式三份报告补全）执行：

```bash
python <skill_dir>/scripts/bugfix.py create-pr <bugId> --project <项目目录>
```

| 行为 | 绑定（inplace）模式 | worktree 模式 |
|---|---|---|
| 前置条件 | 该 Bug 已 finish 提交（有 commit） | 三份报告完整、有代码变更 |
| 提交 | 使用 finish 产生的 commit | 自动提交全部代码变更（排除 `.agents/` 与根 `AGENTS.md`），提交信息同 finish |
| 推送 | 推送绑定分支 | 推送 `bugfix/<bugId>_<日期>` 分支 |
| PR | 绑定分支 → 目标分支 | bugfix 分支 → 目标分支 |

目标分支：`--base` 参数 > config `AUTO_PR_BASE_BRANCH` > 平台默认分支。标题默认同提交信息，
正文取自 fix-report.md 节选与 Bug 链接；`AUTO_PR_DRAFT=on` 创建草稿 PR。

创建命令的选择顺序：config `AUTO_PR_CMD` 模板（占位符 `{head}` `{base}` `{title}` `{body}`
`{body_file}` `{remote}` `{draft}`）> GitHub 远程用 `gh pr create` > GitLab 远程用 `glab mr create`。
`gh`/`glab` 需已安装并登录；`AUTO_PR_REMOTE` 指定推送远程名（默认 origin，无 origin 取第一个远程）。
其他平台（Gitee、自建 Git 服务等）用 `AUTO_PR_CMD` 对接各自 CLI 或 API。

安全与幂等：

- 三份报告必须完整（无（待填写）标记，与 finish 同一门槛）才发起；`--force` 可人工确认后跳过开关与门槛。
- `--dry-run` 只打印将执行的提交/推送/PR 命令，不提交、不推送、不创建。
- 运行记录已存 PR 时重复执行只回显已有 PR；平台返回 PR 已存在时同样回显不重复创建。
- 推送被拒绝（远端有新提交）时停止，人工同步分支后重试；绝不 force push。
- PR 创建失败输出 `PR_STATUS=failed` 与原因，退出码 1；已产生的修复提交不受影响，不回滚。
- 成功后 PR 信息写入运行记录与 meta.json，fix-report.md 追加「## Pull Request」章节并同步更新 HTML。

## 故障恢复

- ready 失败：代码在分析完成前已发生变化，先核对现场，不继续修改。
- 验证或 hook 失败：修复失败原因后 retry；锁保留，后续 Bug 等待。
- 已生成 commit 但后置检查失败：记录中保留 commit，人工检查 Git 状态，不再次提交或强行清锁。
- create-pr 推送失败：远端可能有新提交，人工同步分支后重跑 create-pr；不 force push。
- create-pr 创建失败：按错误信息检查 CLI 登录、权限或 AUTO_PR_CMD；修复提交不受影响，重跑只补 PR。
- 监听/电脑重启：操作系统活动锁自动释放；持久锁保留现场，retry 恢复前一 Bug。
- 未完成修复时不允许通过修改 routes.json 转移目标；先恢复原目标并解决该 Bug。
