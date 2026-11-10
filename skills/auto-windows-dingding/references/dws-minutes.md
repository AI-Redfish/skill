# dws 会议听记读取参考

本 skill 的会议总结流程只使用下列只读命令。dws 未加入 PATH 时用完整路径 `%USERPROFILE%\.local\bin\dws.exe`。参考来源：官方 dingtalk-minutes skill（https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/main/skills/multi/dingtalk-minutes/references/minutes.md）与 dws v1.0.62 本地实测。

## 命令速查（只读）

| 目的 | 命令 |
|---|---|
| 登录状态 | `dws auth status --format json` |
| 按标题关键词/时间搜索 | `dws minutes +search --query "<关键词>" --scope all --page-all --format json` |
| 我创建的听记列表 | `dws minutes +list-mine --page-all --format json` |
| 他人共享的听记列表 | `dws minutes +list-shared --page-all --format json` |
| 我最新一条听记 | `dws minutes +latest [--keyword <词>]` |
| 批量聚合读取产物 | `dws minutes +detail --id <taskUuid> --artifacts basic,summary,keywords,todos --format json` |
| 完整逐字稿（跨页去重） | `dws minutes +transcript --id <taskUuid> --format json` |
| 行动项（typed state） | `dws minutes +action-items --id <taskUuid>` |
| 申请访问权限 | `dws minutes +apply-permission --id <taskUuid> --policy <2\|3\|4>` |

`+search` 的 `--scope` 可选 `mine`、`shared`、`all`；`--start/--end` 接受 RFC3339，至少指定 query/start/end 之一。时间戳一律为毫秒 epoch，展示前转本地时区。

## URL → taskUuid 解析

`--id` 只接受纯 taskUuid。用户给链接时由 Agent 解析：

| URL 形态 | 取值方式 |
|---|---|
| `https://shanji.dingtalk.com/app/transcribes/<taskUuid>` | 取 `/transcribes/` 后至 `?` 或路径结束 |
| `https://shanji.dingtalk.com/meeting/minutes?taskUuid=<taskUuid>` | 读 `taskUuid` query 参数 |
| 其他可信听记链接含 `minutesId` | 读 `minutesId` query 参数，作为 taskUuid 使用 |

## 输出信封字段

**`+search`**：业务集合在 `data`（`scope/count/minutes/pages/complete`），分页在 `meta.pagination`（`endpoint_exhausted/next_token`）。`data.complete` 非 true 时用 `--page-all` 重跑证明完整性。候选字段：`taskUuid`、`title`、`startTime/endTime`（毫秒）、`status`、`url`、`flashUserInfo.name`（创建人）。

**`+detail`**：按 `--artifacts` 返回 `basic/summary/keywords/todos` 各分支，bundle 级 `complete` 与 `failureCount` 判定整体完整性；任一产物失败为 partial，已取得的结果仍可用，但不许把 partial 当完整。

| 产物 | 关键字段 | 注意 |
|---|---|---|
| basic | `result.title/duration/startTime/endTime/taskUuid/url` | duration 为毫秒 |
| summary | `result.fullSummary`（原生 AI 摘要 Markdown）、`result.generatingStatus` | 仅 `COMPLETED` 才算生成完毕；此命令组只读 |
| keywords | `result.keywords`（字符串数组） | 不从空字段编造关键词 |
| todos | `result.dingtalkTodoList` / `result.items`（结构化：`title/minutesTodoId/executorList`）、`result.itemCount` | `result.actions` 是 JSON 字符串数组，解析后再用；空数组是合法的「无行动项」，与调用失败区分 |

**`+transcript`**：`data.complete`、`data.pages` 判定完整性；`paragraphList` 每段含 `nickName/paragraph/startTime/endTime`。长稿用 `+detail --artifacts transcript --transcript-output file --output-dir <相对目录>`，输出目录必须是安全相对路径；临时稿总结后删除。

## 权限

无权限访问时响应会报错，不绕过、不重试爆破。请用户确认后运行 `dws minutes +apply-permission --id <taskUuid> --policy <2|3|4>`（2=编辑、3=查看下载、4=仅查看），`--policy` 必须显式传入。

## 故障排查

| 现象 | 处理 |
|---|---|
| 搜索零命中 | 换关键词或扩大时间范围重搜一次；仍零命中则停止并报告，不编造 |
| 搜索多命中 | 列候选（标题 + 时间 + taskUuid）请用户选择，不猜选 |
| `data.complete` 非 true | 带 `--page-all` 重跑 |
| bundle `complete:false` 或 `failureCount>0` | 报告 partial 与缺失产物，缺失部分留空并标注，不换 taskUuid |
| `generatingStatus` 非 COMPLETED | 摘要仍在生成，告知用户稍后重试 |
| 无权限访问 | 如实报告；经用户确认后走 `+apply-permission` |
| 逐字稿过长撑爆上下文 | 用 `--transcript-output file` 落临时目录，读取所需段落后删除临时文件 |
| 音频地址（`minutes get audio`） | URL 敏感且会过期，不写入总结文档、不长期保存 |

## 禁止事项

- `dws minutes +summary` 是**覆盖纪要正文**的写命令，禁止在总结流程中调用。
- 不执行任何 minutes 写操作（update/replace/share/record/upload 等），除非用户明确要求。
- 听记原文与总结文档不发送到钉钉或外部，除非用户明确指定收件人并确认内容。
