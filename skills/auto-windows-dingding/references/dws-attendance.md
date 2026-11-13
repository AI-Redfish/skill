# dws 考勤工时核算参考

本 skill 的考勤核算只读取数据，不写任何考勤配置。核算脚本：`scripts/attendance_period_hours.py`（纯标准库，Python 3.7+，Windows/Linux 通用）。基于本机 dws v1.0.62 实测（2026-11），实机验证：中科医信组织一周窗口全链路跑通。

## 一行命令

```bash
python scripts/attendance_period_hours.py --org <组织名> --start YYYY-MM-DD --end YYYY-MM-DD \
  [--daily-hours 8] [--deduct-hours 1.5] [--today YYYY-MM-DD] [--user <userId>] [--profile corpId:userId] [--json]
```

- `--org` 须为本机 `dws profile list` 已登录组织；`--profile corpId:userId` 优先于 `--org`。
- `--end` 可在未来；脚本只核算 ≤ `--today`（默认真实今天）的工作日。
- `--user` 默认为该 profile 登录用户本人；代他人核算时显式传 userId（需有查看权限）。
- stdout 输出 Markdown 报告（`### 结论` 四项 + `### 逐日明细` 表）；stderr 输出 `[身份] 组织… 用户…` 行。
- `--json` 输出结构化结果（`identity` / `summary`，含逐日 `rows`、`fail_days`、`warnings`、`invalid_records`）供二次加工。
- 周期长度不限，脚本对打卡与审批按 28 天窗口自动分段拉取。

## .env 配置（skill 安装目录，已被仓库 .gitignore 忽略）

| 键 | 说明 | 示例 |
|---|---|---|
| `ATT_PROFILE` | corpId:userId，优先于 `ATT_ORG` | `dingxxxx:3004xxxx` |
| `ATT_ORG` | 组织名，须为本机已登录 profile | `中科医信` |
| `ATT_PERIOD_START` / `ATT_PERIOD_END` | 考勤周期起止，MM-DD；跨年周期按实际起止填 | `10-26` / `11-25` |
| `ATT_DAILY_HOURS` | 每日标准工时 | `8` |
| `ATT_DEDUCT_HOURS` | 每日扣除的休息小时（午休+晚休等） | `1.5` |
| `REPORT_TARGET_TYPE` | 报告渠道：`dm`=单聊 / `group`=群 | `dm` |
| `REPORT_TARGET` | 单聊姓名/花名，或群名 | `张三` |

周期解析规则（用户未给完整日期时）：以今天为锚把 MM-DD 解析为完整日期。起 MM-DD 晚于止 MM-DD 视为跨年周期（start 取上一年）；今天已过本周期 end 则整体后移一年；今天早于 start 则整体前移一年。解析结果先向用户复述。

## 考勤命令速查（只读）

| 目的 | 命令 |
|---|---|
| 已登录组织列表 | `dws profile list --format json` |
| 设备码登录新组织 | 后台执行 `nohup dws auth login --device --format json > /tmp/dws_login.log 2>&1 &`，把授权链接与 user_code 原样发给用户 |
| 排班（工作日/班次） | `dws --profile <sel> attendance schedule get --users <userId> --start D --end D` |
| 打卡流水 | `dws --profile <sel> attendance +check-record --users <userId> --start D --end D+1` |
| 审批（请假/加班/出差/补卡） | `dws --profile <sel> attendance +list-approve --users <userId> --types overtime,trip,leave,patch --start D --end D+1` |
| 班次工时口径复核 | `dws --profile <sel> attendance class get --class-id <classId>`（看 `workTimeMinutes`） |
| 只核对个别天 | 直接用 `+check-record`（`--end` 传目标日+1），不必整周期跑 |

## 报告发送

| 渠道 | 命令 |
|---|---|
| 单聊 | `dws chat +dm --to <姓名> --content "<报告>" --yes --format json` |
| 群 | `dws chat +send-to-group --group <群名> --content "<报告>" --yes --format json` |

- 报告含换行、竖线与表格字符：先把脚本 stdout 收进变量再 `--content "$report"` 传参，避免手工转义。
- 多组织时发送命令同样带全局 `--profile`，与考勤组织保持一致，避免发错组织。
- 成功核验、`--dry-run` 预览、姓名多候选处理、失败不重试等规则与 [dws-send.md](dws-send.md) 完全一致。

## 已知坑（脚本已内置处理，手工组合命令时同样必须遵守）

- **Windows 编码**：dws 输出恒为 UTF-8，Windows 控制台/管道默认 GBK。脚本已对 subprocess 与 stdout/stderr 显式 UTF-8；手工调用 dws 出现中文乱码时，前置 `PYTHONIOENCODING=utf-8`。
- **多组织路由**：登录后 `currentProfile` 会切换，但会话内早期命令可能仍打到旧组织；所有 dws 命令显式带 `--profile corpId:userId`，并核对 `[身份]` 输出。
- **`+check-record` 结束日不含当日**：`--end` 必须传 目标末日+1 天；脚本按 28 天窗口自动分段。
- **异常流水**：存在无 `checkType`/`userCheckTime` 的记录（如"常用手机数量"报错误码），不能计入打卡，脚本单列为"异常流水"。
- **补卡**：`sourceType=APPROVE` 的上班卡按计划时间（如 09:30）计入跨度，备注"补卡"。
- **半天请假**：审批 `请假`（duration 单位 DAY×标准小时）会下调当日应达小时（净跨度 ≥ 8−请假时长 才算达标）；请假前的实际在岗跨度仍扣全额 `--deduct-hours`（保守口径），报告中保留"请假未补足"等备注供人工确认，例如请假从 13:30 起但 12:02 即下班，中间 1.5h 属未覆盖缺勤。
- **多次打卡**：取当日最早 OnDuty 与最晚 OffDuty；`AUTO_CHECK` 自动卡与手动卡同权。
- **工作日口径**：以已导入排班（`schedule get`，isRest=N）为准；无排班数据时回退周一至周五并输出 warning，需提醒用户确认调休/单休。

## 故障排查

| 现象 | 处理 |
|---|---|
| 报错「本机未登录组织」 | `dws profile list` 核对名称；不在列表走设备码登录后重试 |
| 报错「组织重名/多账号无默认」 | 改用 `--profile corpId:userId`（见 profile list） |
| `[身份]` 组织与目标不符 | 停止并报告；显式 `--profile` 后重试，不转述错误组织的数据 |
| token expired | dws 会用 refresh token 自动续期，直接重跑；仍失败走 `dws auth login` |
| 报告含 `warnings`/`异常流水` | 原样转述给用户，不猜测补齐 |
| 发送失败 | 按 dws-send.md 排查；不自动重试 |

## 禁止事项

- 不调用任何 attendance 写命令（排班导入、审批提交/同意、补卡操作等）。
- 不为"凑达标"修改口径参数重跑；口径变更须用户明确说明。
- 报告数字按脚本输出转述，不人工修改。
