# 配置格式

配置文件：`<workdir>/.agents/work-experience-accumulate/config.json`。

账号、密码和令牌不写入此文件。敏感值放在 `<workdir>/.agents/.env`，键名由外部适配器约定。

```json
{
  "schedule": {"frequency": "daily", "time": "09:00", "lookback_days": 1, "task_name": "AI-Redfish-work-experience-accumulate"},
  "dingtalk": {
    "search_args": [],
    "notify_user_id": "由用户指定的稳定用户标识",
    "notify_command": ["dws", "chat", "+messages-send", "--as", "current-user", "--to-user", "{user_id}", "--text", "{text}", "--format", "json"]
  },
  "agent_command": ["pi", "-p", "--no-session", "{run_dir}", "请补全 draft.md"] ,
  "zentao": {
    "query_command": ["python3", ".../zentao_query.py", "--start", "{start}", "--end", "{end}", "--resolved-by", "{user_id}"],
    "user_id": "当前用户在禅道中的稳定标识"
  },
  "git_repositories": [
    {"path": "/path/to/repository", "branches": ["main", "release/1.0"]}
  ],
  "agent_workspaces": ["/path/to/agent/workspace"],
  "targets": {
    "skill": [],
    "workflow": [],
    "mcp": [],
    "knowledge": []
  }
}
```

## 适配器约定

- `dingtalk.search_args` 只放经 `dws chat +search-msg --help` 确认过的参数，不放命令本身。脚本自动追加时间窗口和 `--format json`。
- `dingtalk.notify_command` 只放经当前 dws Schema/help 确认过的 argv。允许 `{user_id}`、`{text}` 和 `{run_dir}` 占位符。配置前必须核对 leaf help，不要照抄示例中的未确认 flag。
- `agent_command` 是可选的 argv 数组。允许 `{run_dir}` 和 `{skill_dir}` 占位符。未配置时定时任务只生成草稿模板，不假装完成总结。
- `zentao.query_command` 是 argv 数组，不经过 shell。命令输出必须是 JSON，结果应包含已解决且解决人为 `user_id` 的 Bug。脚本会追加或替换 `{start}`、`{end}`、`{user_id}` 占位符，不会猜禅道部署版本的字段。
- `targets` 只记录审核后允许写入的位置。首次运行可以为空。
- Git 仓库的 `branches` 必须非空。脚本不会使用当前分支兜底。
- `agent_workspaces` 至少一个路径。多个路径用于多个 Agent 或项目的会话范围。
- `schedule.frequency` 只能是 `daily` 或 `weekly`。`weekly` 固定每周一执行。
- `schedule.task_name` 是 Windows 任务计划程序根目录下的任务名称。默认值为 `AI-Redfish-work-experience-accumulate`。不得包含目录分隔符或控制字符。
- Windows 任务使用当前用户的 `Interactive` 登录类型，不保存 Windows 密码。电脑重启后任务定义仍存在，用户重新登录后继续执行。
