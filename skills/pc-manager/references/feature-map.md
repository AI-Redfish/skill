# 功能 → 脚本速查表（参数 / 输出 / 权限）

统一约定：
- 调用：`powershell -NoProfile -ExecutionPolicy Bypass -File <skill_dir>/scripts/<脚本> …`
- stdout：`{ status: ok|error, data: …, error?: … }`；退出码 0/1
- 删除类动作通用参数：`-Session <scan返回的会话文件>`（必填）+ `-Ids id1,id2`
  （或 `-Recommended` = 全部 safe 级默认项）+ `-Purge`（永久删）+ `-Force`（danger 确认）
- 「管理员」列：●=需要管理员才能生效；○=普通权限；◐=部分子动作需要

## junk.ps1 垃圾清理 ◐
| 动作 | 参数 | 输出要点 |
|---|---|---|
| scan | `-ExtraIds id,…`（增强项，14 个：downloaded_program_files/inet_temp/windows_error_report/dx_shader_cache/delivery_optimization/temp_files/thumbnails/windows_upgrade_logs/temp_windows_install/user_error_report/windows_old|windows_update_cleanup|memory_dump(danger)/recycle_bin(特殊) | count/total_bytes/by_level/session/candidates（id,path,size,level,recommend） |
| delete | `-Session -Ids|-Recommended [-Purge] [-Force]` | deleted_count/bytes, skipped, errors |
| list | — | 内置规则 + 增强项目录（含各自说明与风险级） |

内置规则（无需勾选自动扫）：user_temp(>7天)、edge_cache、chrome_cache、firefox_cache。

## social.ps1 社交专清 ○
| 动作 | 参数 | 输出要点 |
|---|---|---|
| scan | — | items（app,level,name,path,size,file_count,blocked,locked,recommend）+ by_level |
| delete | `-Session -Ids [-Purge]` | 同通用；锁定级机制性拒绝 |

应用：微信（3.x/4.x/自定义 ini 路径）、QQ、钉钉、企业微信、飞书、微博、抖音、YY、
陌陌、Soul、千牛。四级：safe（临时缓存）/advise（图片，含微信 .dat 加密图）/
caution（视频、接收文件，默认不勾）/locked（聊天记录，不可删）。

## dup.ps1 重复文件 ○
参数：`-MinMb 10`（最小体积）、`-Scope user|all`、`-Drive D`、`-MaxPerGroup`。
输出：groups（hash,size,count,wasted=size×(count-1),files 按 mtime 升序=最旧在前）。
判定链：大小 → 头尾 4KB SHA-256 → 全量 SHA-256。删除引导：用户选组内旧副本 →
`recycle.ps1 -Action trash -Path '<文件>'` 逐个移入回收站。

## bigfile.ps1 大文件 ○
参数：`-MinMb 200`、`-Scope user|all`、`-Drive D`、`-Top 200`、`-Depth 8`。
输出：files（path,size,mtime）按体积降序。仅分析；删除经 recycle trash。

## installer.ps1 安装包清理 ○
| 动作 | 参数 | 输出 |
|---|---|---|
| scan | `-MinMb 0 -MinDays 0 -Drive ''|all|D` | items（path,size,days,ext,byName） |
| delete | 通用 | 通用 |

判定：扩展名（exe/msi/iso/zip/rar/7z/cab/msix/appx）+ 名字特征（setup/install/
driver/安装包/驱动/绿色版/portable）或 ≥10MB。

## logs.ps1 日志清理 ○
| 动作 | 参数 | 输出 |
|---|---|---|
| scan | `-MinDays 0 -Drive ''|all|D` | items（group: app|temp|crash, path,size）+ by_group |
| delete | 通用（crash 组目录会展开为文件清单） | 通用 |

## residue.ps1 卸载残留 ○
| 动作 | 参数 | 输出 |
|---|---|---|
| scan | `-MinMb 10 -MinDays 60` | items（name,path,size,days,source）+ hint |
| delete | 通用 | 通用 |

判定：在装程序白名单反查 + 长期未动 + ≥阈值；DENY 目录排除；宁漏报不误报。

## startup.ps1 启动项 ○（HKLM 禁用需权限）
| 动作 | 参数 | 输出 |
|---|---|---|
| list | — | entries（id,name,command,location,source:registry|folder|task,enabled） |
| disable / enable | `-Id '<id>'` | done（可逆：.grdisabled 后缀 / schtasks） |

## registry.ps1 注册表清理 ◐（HKLM 删需权限）
| 动作 | 参数 | 输出 |
|---|---|---|
| scan | — | items（category,key_path,name,kind,target,detail）+ by_category |
| delete | `-Session [-Ids]`（先自动备份，失败中止） | deleted_count, backup_file, skipped |
| backups | — | 备份列表 |
| restore | `-BackupFile <json>` | restored, errors |

四类：卸载残留/无效启动项/丢失SharedDLL/无效App Paths。

## uninstall.ps1 软件卸载 ○
| 动作 | 参数 | 输出 |
|---|---|---|
| list | — | entries（id,name,version,publisher,install_location,size_kb,can_uninstall） |
| uninstall | `-Id '<root|view|key>' [-Quiet]` | launched=true（原生卸载器弹窗） |

## optimize.ps1 系统优化 ◐
| 动作 | 参数 | 输出 |
|---|---|---|
| status | `-Drive C` | options（trim/defrag/storagesense/compactos 各带 status,value,advice） |
| services | — | 服务列表（third_party,recommend_delay） |
| vhd | — | WSL/Docker 占用与迁移建议 |
| trim / compactos | `-Enabled:$true|:$false` | done |
| defrag | `-Drive C [-Analyze]` | output |
| storagesense-run | — | done |
| service-delay | `-Name <服务> -Enabled:$true` | done（白名单服务拒绝） |

## slim.ps1 C盘瘦身 ◐（windows_old 等需管理员）
| 动作 | 参数 | 输出 |
|---|---|---|
| plan | — | items（kind,name,size,risk,recommend,actionable,goto）按体积降序 |
| run | `-Kinds k1,k2 [-Force]` | results（kind,ok,message） |

kinds：hibernation(safe 可逆)/windows_old(danger)/update_cache/delivery_opt/
temp_install(safe)；social/bigfiles 走对应脚本。

## contextmenu.ps1 右键菜单 ◐（HKLM 删需权限）
| 动作 | 参数 | 输出 |
|---|---|---|
| list / icons | — | 条目（system 项不可操作） |
| disable / enable / delete / icons-delete | `-Id` | done / deleted（.reg 备份路径） |
| classic | `-Enabled`（加=经典菜单，不加=Win11 新菜单） | 生效提示 |
| restart-explorer | — | 重启资源管理器（改动后生效用） |

## disk.ps1 磁盘 ○（SMART 计数器部分需管理员）
动作：`list [-Drive C]` / `smart -DeviceId 0` / `physical`。输出见脚本；
smart rows 含 admin 标记与「需管理员权限/不支持」区分。

## drivers.ps1 驱动清理 ●
| 动作 | 参数 | 输出 |
|---|---|---|
| scan | — | items（status: in_use/old_confirmed/recommended/unknown, candidate, actionable, published） |
| delete | `-Published oemNN.inf -Force` | output |

## health.ps1 一键体检 ○
参数：`-Quick`（跳过重复哈希全扫）。输出：score/level/level_color/factors（11 项
key,label,weight,score,detail）/suggestions/stats。

## sysinfo.ps1 系统信息 ○
输出：os/arch/processor/cpu_cores/threads/cpu_ghz/mem_total_gb/mem_free_gb/
computer_name/user。

## recycle.ps1 回收站 ◐（顽固项提权重试）
| 动作 | 参数 | 输出 |
|---|---|---|
| list | — | entries（name,original_path,size,deleted_at,drive；$I 解析） |
| delete | `-Session [-Ids]`（永久删除，先清只读+重试） | deleted_count/bytes |
| trash | `-Path`（任意文件/目录移入回收站，受保护拦截） | moved |

## snapshot.ps1 空间快照 ○
动作：`take` / `list` / `diff -BaseId <早> -TargetId <晚>` / `delete -SnapshotId`。
diff 输出：volumes（各盘 delta）+ dirs（膨胀目录按 delta 降序，is_new）+ days。

## schedule.ps1 定时清理 ◐
动作：`list` / `add -Name <名> -Time HH:MM [-Weekly]` / `remove -Name` /
`run-now -Name`。任务到点无窗口执行 `junk.ps1 -Action delete -Recommended`
（仅 safe 级推荐项 + 回收站）。

## migrate.ps1 目录迁移 ○
| 动作 | 参数 | 输出 |
|---|---|---|
| list | `-MinMb 500` | items（is_junction 已迁标记, junction_target） |
| run | `-Path <目录> -TargetDrive D` | migrated / 失败自动回滚 |
| undo | `-Path <联接路径>` | restored |

约束：白名单根一级子目录；目标剩余 > 源 1.2 倍；robocopy /MOVE + mklink /J + 探针校验。

## pagefile.ps1 页面文件 ●（apply 需管理员）
动作：`info`（现状+建议值）/ `targets`（可迁盘）/ `apply -Mode auto|custom|move
[-DriveLetter D] [-InitialMb] [-MaxMb]`。重启生效。

## restore.ps1 还原点 ●
动作：`list` / `delete-oldest -Count N -Force`（保底留 1 个，逐条删最老）/
`create -Description '<描述>'`（24h 限 1 个）。
