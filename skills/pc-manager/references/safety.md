# 安全防线规范（pc-manager 继承自 GrClean 的纵深防御）

本 skill 直接操作系统，安全模型是第一优先级。AI 编排时必须遵守本文；
所有防线的**机制实现**在 `scripts/common.psm1` 与各脚本内，不依赖 AI 自觉。

## 1. 七道删除防线（机制保证，非约定）

1. **扫描/删除分离 + 会话反查**：delete 只接受 scan 落盘的会话文件
   （`%LOCALAPPDATA%\pc-manager\sessions\*.json`）中的 id。调用方传不了任意路径，
   从机制上杜绝"AI 被诱导删除任意文件"
2. **受保护路径 fail-safe 拦截**（`Test-ProtectedPath`）：无法解析/非绝对路径/
   盘根（`C:\`）/ 系统前缀（Windows、Program Files×2、ProgramData、$Recycle.Bin、
   Recovery——Windows 目录动态按 WINDIR/SystemDrive 计算）/ 用户主目录根 →
   一律按保护处理。系统级清理项的放行 = `AllowSystemPrefixes`（该清理项声明的
   根目录）且路径必须落在其内，双重校验
3. **默认回收站**：所有删除默认 `Move-ToRecycleBinSafe`（系统标准 COM 接口，
   VisualBasic FileIO.SendToRecycleBin）；`-Purge` 才永久删除
4. **危险分级强确认**：danger 级（Windows.old / Windows 更新清理 / 内存转储 /
   驱动删除 / 还原点删除）必须 `-Force`；社交 locked 级（聊天记录）无参数可解，
   机制性拒绝
5. **预过滤链**：Windows 危险子路径（system32\config、winsxs、boot 等 25+）与
   危险扩展名（.sys/.cat/.drv）扫描期即跳过；desktop.ini/thumbs.db 等标记文件、
   .lnk 快捷方式、被占用的临时文件（预开检测）不列出
6. **删除前备份**（registry / contextmenu）：注册表自采快照 JSON（含值类型，
   备份失败整体中止）；右键菜单 reg export .reg；均可一键恢复
7. **审计日志**：全部删除/变更写 `%LOCALAPPDATA%\pc-manager\audit.jsonl`
   （时间戳/动作/路径列表），事后可追溯

## 2. 风险分级体系（复刻 grclean 三级+锁死级）

| 级别 | 含义 | 默认行为 | 删除条件 |
|---|---|---|---|
| safe | 可重建缓存/残留，删除无感 | 默认勾选 | 普通确认（-Recommended 或勾选） |
| caution | 可能有用的数据（接收文件/视频/回收站） | 默认不勾 | 逐项确认 |
| danger | 不可逆（Windows.old/更新缓存/转储/驱动/还原点） | 默认不勾+不默认执行 | 用户显式同意 + `-Force` |
| locked | 聊天记录数据库 | 仅展示体积 | **不可删**（机制锁死） |

社交缓存锁定扩展名：`.db .db-wal .db-shm .sqlite .sqlite3`（在展开与执行两层
双保险剔除）。注意 `.dat` 不在锁内——微信/QQ 的加密图片缓存属"图片缓存"可清。

## 3. AI 编排守则（与机制互补的行为约束）

1. **先扫描后删除**：任何清理先跑只读动作出清单；绝不未扫描直接 delete
2. **清单必展示分级**：给用户看的清单必须带风险标记与总量；danger 项单独列出
   并说明不可逆后果（"清完补丁卸载不了"级别的具体后果）
3. **不绕防线**：遇到"受保护路径已拦截"，如实说明，不换脚本/换方式重试；
   用户坚持删系统目录 → 明确拒绝并说明风险（这是红线，不是流程问题）
4. **错误如实转述**：管理员权限不足就告诉用户提权重试，不静默降级、不假装成功
5. **会话即弃**：scan 返回的 session 路径只在当轮删除时使用，不跨轮复用
   （过期会话里的路径可能已变化）
6. **高危操作二次口播**：执行 danger 级、`-Purge`、驱动删除、还原点删除前，
   最后向用户复述一遍操作对象与后果再执行

## 4. 各脚本的权限需求

- 普通权限可用：junk/social/dup/bigfile/installer/logs/residue/startup(HKCU 部分)/
  uninstall/list 类全部/disk(list/smart 基础)/health/sysinfo/recycle/snapshot/
  schedule(创建当前用户任务)/migrate/contextmenu(HKCU 部分)/optimize(status)
- 需管理员：slim 的系统目录项与 windows_old、registry 删 HKLM 项、drivers 删除、
  pagefile apply、restore 全部变更、optimize 的 trim/defrag/compactos、
  SMART 可靠性计数器、startup 禁用 HKLM 项
- 脚本不会自动提权（不弹 UAC）：报错引导用户以管理员身份重开终端重试

## 5. 与 GrClean 的差异点（如实标注）

| 项 | GrClean | pc-manager | 理由 |
|---|---|---|---|
| 回收站移入 | windows-trash.exe 批量（快）+ PS 兜底 | 仅 PS VisualBasic FileIO | 免外部 exe 依赖；批量性能损失可接受（AI 场景单次清理量小于 GUI 场景） |
| 流式进度 | async generator + IPC 批量推送 | 一次性 JSON 返回 | CLI 形态无流式消费者；进度走 stderr |
| 并发哈希 | worker_threads 线程池 | 顺序哈希 | PS 5.1 无轻量并发原语；正确性优先，性能以 MinMb 门槛补偿 |
| 定时清理 | 调自身 exe 静默模式 | schtasks 调 junk.ps1 -Recommended | 等价实现（同为仅 safe 级+回收站） |
| 注册表读取 | .NET Registry API（80x 快） | provider Cmdlet | 篡改收益在枚举数百键时才显著；扫描结果量级相同 |
