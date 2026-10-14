# dws 采集故障排查记录（外部 CLI）

记录本机 `dws` 采集钉钉消息时反复出现的间歇性失败，包含已确认事实、已排除项、当前处置和复现命令。目的是避免重复投入同一批排查。

## 现象

`dws chat +search-msg` 间歇返回：

```json
{"error": {"category": "api", "code": 1, "message": "下游缺少明确的集合字段，无法判定结果为空"}}
```

- 退出码 `1`，stdout 为空，stderr 为该 JSON（前面可能带一行 dws 告警）。
- 该文案是 **dws 自己的结论守卫**产生的，不是本 skill 的文字：成功响应里带 `conclusionGuard`（含 `absenceWithinQueryRangeAllowed`、`requiredActionForAllHistory`），dws 拒绝把「上游未给出集合字段」的响应当作空结果。
- 因此：**该错误不等于没有消息，也不等于查询成功但结果为空**。本 skill 一律按来源失败处理。

## 已确认事实（2026-10-14 实测）

1. **`--debug` 不暴露上游原因**：失败时 stderr 只多一行
   `level=DEBUG msg=runtime.host_owned_pat hostOwned=false agentCodeEnvPresent=false`，
   没有任何请求/响应体或状态码，无法据此定位上游。
2. **与窗口宽度无关**：40 分钟、1 小时、2 小时、6 小时、24 小时窗口都出现过成功与失败。
3. **与 `-v/--verbose` 无关**：`-v` 同样复现；`--debug` 同样复现。
4. **与 dws Skill 安装状态无关**：执行 `dws skill setup --mode multi` 后，dws 的
   「检测到旧升级器留下的嵌套 Skill」告警消失，但该 API 错误仍复现。
5. **随时间波动**：同一时段约 1/3 调用失败；另一时段连续 6 次单次调用全部成功。
   因此**单次采样不能作为结论**，任何“已修复/未修复”的判断必须给出多次调用。
6. **重试有效**：同一命令、同一参数、同一窗口的失败，随后重查可以成功。

## 已排除（不要重复投入）

- **不是登录或权限问题**：`dws auth status --profile <profile>` 通过；同一账号在其他时段能成功。
- **不是参数漂移**：命令、参数集合与 leaf Schema 未变化。
- **不是窗口过大**：窄窗口（40 分钟）同样失败；宽窗口（24 小时）也常成功。
- **不是 dws Skill 安装残留**：完成 `multi` 迁移后仍复现（见事实 4）。
- **不是本 skill 的解析问题**：失败发生在 dws 进程内，退出码 1，本 skill 未参与解析。
- **不要改用 `chat message list-all` 来“修”这个问题**：同账号同时段对照中，
  `chat message list-all`（`--start/--end` 传 RFC3339 带偏移）返回
  `success=true`、`result.conversationMessagesList=[]`、`paging.total=0`、
  `paging.sourceExhausted=true`，而 `+search-msg` 在同一窗口能找到消息。
  即 `list-all` 的空列表**不能作为“该窗口没有消息”的依据**；`--page-all` 还观测到长时间不返回。
- **不要把该错误解释为“没有消息”**，也不要据此清空或覆盖已采集证据。

## 当前处置（已实现）

1. **形状类失败有界退避重试**：`dingtalk.shape_retries`（0–3，默认 2），退避序列固定为 5s / 10s / 20s。
2. **仍失败则宽窗口降级**：按 `dingtalk.fallback_window_hours`（默认 3）切分；失败的切片再二分
   `dingtalk.split_max_depth`（默认 2）次；切片查询总数封顶 `2 × dingtalk.max_sub_windows`（默认 12）。
   合并时按 `(conversationId, messageId)` 去重，任一失败都保留已取得证据并标 `complete=false`。
3. **熔断**：降级过程中若连续 ≥ 8 次查询都是形状失败且尚未拿到任何切片，
   判定上游处于故障时段，停止剩余切片；避免对已降级的上游继续无效调用。
4. **服务端指示的重试只做一次**：仅当 dws 明确给出 `retryable=true` 时按
   `retry_after_seconds` / `next_retry_at` 等待一次；不进入上面的退避序列。
5. **失败关闭**：最终仍失败时 `sources.dingtalk=false`、`complete=false`，草稿必须披露来源失败。

## 复现与验证命令

单次调用（观察是否复现）：

```bash
timeout -k 5 180 dws chat +search-msg --limit 30 --page-limit 40 --page-all \
  --order asc --no-reactions \
  --start <RFC3339 含偏移> --end <RFC3339 含偏移> \
  --profile <corpId:userId> --format json
```

连续采样（判断是否处于故障时段，建议 ≥6 次）：

```bash
for i in 1 2 3 4 5 6; do
  timeout -k 5 180 dws chat +search-msg ... --format json >out.$i.json 2>err.$i.json
  echo "$i rc=$? bytes=$(wc -c < out.$i.json)"
done
```

注意事项：

- 在 WSL 中调用 `dws.exe` 时用 `timeout -k 5 <秒>`；只给 `timeout` 时，Windows 进程可能不退出并残留
  （用 `tasklist /FI "IMAGENAME eq dws.exe"` 检查，`taskkill /PID <pid> /F` 清理）。
- `--debug` 会显著拖慢调用，且不提供上游细节，不要指望用它定位。
- 不要把 dws 的 stderr 原文写入配置、草稿或版本库；本记录只保留固定的脱敏诊断。

## 参考

- dws leaf help：`dws chat +search-msg --help`、`dws chat message list-all --help`。
- 迁移后的 dws 文档：`~/.agents/skills/dingtalk-chat/references/chat/message-query.md`、
  `~/.agents/skills/dingtalk-chat/SKILL.md`（跨会话读取推荐入口与完整性要求）。
- 本记录依据 2026-10-14 的实测；调试输出为临时产物，未纳入版本库。
