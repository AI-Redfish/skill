# Bug 修复位置配置

将 `assets/routes.example.json` 复制到被修复项目的 `.agents/zentao-bugfix/routes.json`，填写 config 并修改 rules 中的真实目录和分支。该文件统一保存原 `.env` 配置与匹配规则；没有规则时使用默认独立 worktree 流程，禅道访问仍须配置账号。监听器不自动生成包含虚构目录的生效规则。

```json
{
  "config": {
    "ZENTAO_BASE_URL": "https://zentao.example.com",
    "ZENTAO_ACCOUNT": "你的账号",
    "ZENTAO_PASSWORD": "你的密码",
    "BUGFIX_BASE_BRANCH": "release",
    "DWS_LISTEN_USERS": "李四,张三",
    "AGENT_TYPE": "pi",
    "AGENT_MODEL": "provider/model",
    "LISTEN_MODE": "auto",
    "POLL_INTERVAL_SECONDS": "20",
    "LISTEN_AUTOSTART": "on"
  },
  "rules": [
    {
      "name": "指定 Bug",
      "match": {"bug_id": "12345"},
      "workspace": "D:/projects/order-service",
      "target_branch": "feature/order"
    },
    {
      "name": "订单改造测试",
      "match": {"title_contains": "订单改造"},
      "workspace": "D:/projects/order-service",
      "target_branch": "feature/order"
    }
  ]
}
```

## 配置与迁移

- `config` 保存全部原 `.env` 配置键，值必须为字符串，包括秒数和 on/off。完整键列表见 assets/routes.example.json 与监听文档。
- `rules` 保存原匹配规则，可为空；只有 rules 的旧 JSON 仍可读取规则，config 视为空。只使用线上/default worktree 时可配置 `"rules": []`。
- 脚本不再读取旧 `.env`，也不自动从旧文件获取密码。把原 KEY=VALUE 写成 `"KEY": "VALUE"` 加入 config；JSON 中 Windows 路径使用 `/` 或转义反斜杠 `\\\\`。
- `save-config KEY=VALUE...` 命令仍可使用，写入 routes.json 的 config 并保留规则及其他配置。禁止用只含 config 的新文件覆盖已有 rules。
- 手动修复从 `--project` 的 routes.json 读取 config；监听从启动工作区读取 config。TARGET_PROJECT_PATH 指向其他项目时，只把 ZENTAO_* 合并到目标 config，目标项目 rules 独立保留。
- 生效 routes.json 可含密码，保留为本地文件，不纳入代码提交；config-status 只展示脱敏密码。

## 匹配约定

- 每条规则只使用 `bug_id` 或 `title_contains` 其中一种条件，不支持任务、需求、迭代等字段。
- `bug_id` 为数字字符串，精确匹配；命中 ID 后不再考虑标题规则。
- `title_contains` 为非空字符串，针对禅道接口返回的实际标题做普通子串匹配。英文忽略大小写；不使用正则、不自动分词、不读取钉钉消息作为标题。
- `workspace` 为已有 Git 工作区根目录，推荐绝对路径；相对路径基于配置所在项目根目录。WSL 支持将 `D:/...` 或 `D:\\...` 转换为 `/mnt/d/...`。
- `target_branch` 是工作区必须已检出的 Git 分支名，不是新 worktree 基准分支。
- 同一优先级命中相同目标视为一次命中；命中不同目标视为冲突，记录原因并创建独立 worktree。未命中也默认创建 worktree。
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

绑定模式可以保留其他文件上的暂存、未暂存和未跟踪开发内容。自动修复不触碰已有变更文件；混合修改同一文件时暂停，不尝试猜测哪些行属于本 Bug。禁止全量暂存、自动 stash/reset、绕过 hook 或自动 push。

每个 Bug 仍有独立分析/方案/修复报告和 commit ID。确认无代码改动可通过验证后标记 no_change，不生成空提交。

## 故障恢复

- ready 失败：代码在分析完成前已发生变化，先核对现场，不继续修改。
- 验证或 hook 失败：修复失败原因后 retry；锁保留，后续 Bug 等待。
- 已生成 commit 但后置检查失败：记录中保留 commit，人工检查 Git 状态，不再次提交或强行清锁。
- 监听/电脑重启：操作系统活动锁自动释放；持久锁保留现场，retry 恢复前一 Bug。
- 未完成修复时不允许通过修改 routes.json 转移目标；先恢复原目标并解决该 Bug。
