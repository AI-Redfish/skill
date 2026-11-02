# GrClean 逆向分析报告（pc-manager 的功能蓝本）

> 分析对象：github.com/graent/grclean v2.3.1（Electron 28 + Vue3 + TS 开源 Windows
> 清理优化工具）。分析方法：源码全量精读（src/main/engine 35 个模块 + IPC 面），
> 原计划用 rea MCP 的 JavaScript 应用图分析，但其 4.1.0 在该仓库上稳定复现内部
> schema 错误（identity/key too_small），故以源码精读为证据来源——源码可得时本就是
> 更可靠的一手证据。本报告即 pc-manager 清理类 23 项功能（调优项另见
> optimizerduck-tweaks.md）的设计与实现原理依据。

## 1. 总体架构

```
Electron 主进程（Node/TS）
  engine/ 35 模块 = 纯逻辑引擎（扫描 async generator 流式 + PowerShell 采集）
  ipc/    流式(scan-*:start) + 一次性(handle) 双通道
渲染进程 Vue3 仅展示；系统操作全部经 PowerShell / 原生命令完成
```

关键结论：**所有 Windows 系统操作的真实执行介质是 PowerShell 与系统原生命令**
（注册表 Get-ItemProperty、回收站 VisualBasic FileIO COM、schtasks、robocopy、
fsutil、compact.exe、pnputil、vssadmin、takeown/icacls、Get-Volume/Disk/PhysicalDisk
CIM 链）。Node 层只是编排。→ pc-manager 用 PowerShell 脚本复刻是最忠实的等价实现。

## 2. 安全模型（全模块共享的纵深防御，pc-manager 完整继承）

### 2.1 受保护路径（protected.ts，fail-safe）
- 前缀：Program Files / Program Files (x86) / ProgramData / $Recycle.Bin / Recovery /
  Windows（动态按 WINDIR/SystemDrive，兼容非 C 系统盘）
- 精确文件：pagefile.sys / hiberfil.sys / swapfile.sys / bootmgr / BOOTNXT
- 无法解析路径 → 保护；盘根 → 保护；用户主目录根 → 保护；应用自身目录 → 保护
- 系统级清理项放行 = 「用户显式勾选该项」+「候选路径落在该项声明的根目录内」
  双重校验（patternRoot 截断到首个通配段），杜绝"一次勾选全盘放行"

### 2.2 删除防线（delete.ts，七道）
1. 仅接受候选 id，会话反查真实路径（前端/AI 无法注入任意路径）
2. 执行期再校验 isProtected
3. 仅删文件（junk 类），目录跳过
4. 默认回收站，-Purge 才永久
5. .lnk 快捷方式自动跳过（无收益且常失败）
6. 占用/无权（EBUSY/EPERM/EACCES/ETXTBSY）归"跳过"不报错
7. 成功删除写审计日志（audit.jsonl）

### 2.3 PowerShell 调用规范（ps.ts 实测经验）
- `-NoProfile -NonInteractive -ExecutionPolicy Bypass` + 强制 UTF-8 输出
- PS 启动 ~4s 固定成本 → **一次调用完成全部采集，绝不拆多次**
- 逐行输出必须 `[Console]::Out.Flush()`（管道缓冲会延迟首行 1-2s）
- 读注册表大量键用 .NET `[Microsoft.Win32.Registry]`（比 Get-ItemProperty 快 ~80 倍）
- 错误信息取 stderr 尾部几行（execFile 默认只抛无用的 "Command failed"）

## 3. 各功能实现原理速览

| 功能 | 核心机制 |
|---|---|
| 垃圾清理 | 内置规则（%TEMP%>7天 + 三浏览器缓存）+ 14 增强项（风险分级 safe/caution/danger）；扫描期预过滤：Windows 危险子路径 25+（system32\config、winsxs…）、危险扩展名(.sys/.cat/.drv)、系统标记文件(desktop.ini/thumbs.db)、.lnk、易锁文件(.tmp/.lock/~/partial)预开检测 |
| 社交专清 | 11 款应用；四级风险（safe 临时缓存/advise 图片/caution 视频文件/locked 聊天记录锁死）；跨盘探测（每盘根/Documents/Users\<u>\Documents + reloc 名）；微信 4.x 读 `%APPDATA%\Tencent\xwechat\config\*.ini` 首行定位自定义数据目录；LOCKED_EXT 逐文件锁 .db/.sqlite（.dat 不锁=加密图片缓存可清）；目录名→等级映射 DFS 深度≤6；backup/all_users/migrate 永不展开；整目录快路径（目录内无锁定文件→一次回收站操作） |
| 重复文件 | 三级筛选：大小分组 → 头4KB+尾4KB SHA-256 预筛 → 全量 SHA-256；worker_threads 线程池（full=CPU核数≤8，header=16）；忽略系统目录/node_modules/.git/AppData |
| 大文件 | 用户目录（中英文目录名适配）或全盘；fg.stream 不带 stats（盘根+stats 的已知bug）+并发 stat |
| 安装包 | 扩展名 9 种 + 名字特征（setup/install/驱动/绿色版/portable）或 ≥10MB；系统盘下载目录深3 / 其他盘盘根深8 |
| 日志 | app（*.log 用户目录）/temp/crash（*.dmp + WER 目录整体计体积）三组；系统盘用户目录 / 其他盘盘根深8 |
| 卸载残留 | 已装程序名/厂商/安装目录名 → 白名单词元（归一化宽松双向匹配）；4 根一级子目录；DENY 硬编码排除 + >60天未动 + ≥10MB；采集失败全部视为在用（宁漏报不误报） |
| 启动项 | 三源：注册表 Run/RunOnce（HKCU/HKLM/WOW6432Node）+ 启动文件夹 .lnk（用户+所有用户）+ schtasks（过滤 \Microsoft\）；禁用=追加 `.grdisabled` 后缀可逆重命名 |
| 注册表 | 只检 4 类"判定明确"失效项（卸载残留/无效启动项/丢失SharedDLL/无效App Paths）；Get-ExeFromCommand 引号感知+逐段累加防 "C:\Program" 误判；删前自采快照备份（失败中止）+ 二次校验（项存在+目标仍不存在）；不碰 HKLM\SYSTEM/服务/文件关联 |
| 软件卸载 | 3 视图枚举（过滤 SystemComponent/父组件/补丁）；流式 .NET Registry；id 反查重读卸载命令；msiexec /I→/X 修正；引号感知命令拆分+PATH解析；spawn 不等待；监听 error+1.2s 早期 exit 防误报"已启动" |
| 优化 | 4 项：Trim（fsutil DisableDeleteNotify，仅SSD）/碎片（defrag，仅HDD）/存储感知（注册表'01' 或 Start-ScheduledTask DiskFootprint\StorageSense）/CompactOS（compact.exe）；延迟服务：Auto 启动第三方（~70 系统服务白名单，路径不在 \Windows\）sc.exe config delayed-auto；WSL/Docker VHD 只检测给建议不代劳 |
| C盘瘦身 | 7 项方案：hibernation（powercfg -h off 可逆）/windows_old（Takeown+icacls+删，不可逆）/update_cache/delivery_opt/temp_install（清内容留目录）；dirSize 带 maxFiles 上限；风险分级+actionable 标志 |
| 右键菜单 | 6 个 HKCR shell 根；系统谓词白名单 ~30 锁死；禁用=LegacyDisable 空串（可逆）；删除前 reg export 备份；外壳图标（MyComputer\NameSpace 3 根+7 系统 GUID 锁死）；Win11 经典菜单=HKCU CLSID\{86ca1aa0-…}\InprocServer32 空默认值+重启 explorer |
| 磁盘/SMART | Get-Volume→Get-Partition→Get-Disk 链；fsutil Trim；Get-StorageReliabilityCounter（温度开尔文→摄氏/通电时长/磨损→剩余寿命，需管理员）；root\wmi 故障预测；Get-PhysicalDisk 物理盘聚合 |
| 驱动清理 | DriverStore\FileRepository；Win32_PnPSignedDriver.InfName 在用集合 + Get-WindowsDriver -Online 发布名映射（回退 pnputil 文本解析）；同 inf 版本比较判 old_confirmed；删除 pnputil /delete-driver /force；无法解析发布名只展示不删 |
| 体检评分 | 11 因素加权（见 scoring）线性插值 largerBetter/smallerBetter；等级 ≥85优秀/≥70良好/≥50一般/≥30较差/<30危险；建议= score<max×0.7 的因素触发针对性文案 |
| 回收站 | 按用户 SID 定位各盘 $Recycle.Bin\<SID>；解析 $I 二进制（version 2：偏移8=大小/16=FILETIME/24-27=路径长度/28起=UTF-16 路径；旧版路径从24起）；移入用 windows-trash.exe 批量(200/批并发6)→PS VisualBasic FileIO 兜底（pc-manager 直接用后者，免 exe 依赖） |
| 快照 | 各卷容量+系统盘顶层(深1)体积 → JSON；两次对比=各盘增减+膨胀目录 Top+新增目录 |
| 计划任务 | schtasks /create /tr "<exe> --privacy-clean --schedule-id <id>" /sc daily|weekly；到点无界面跑 junk -Recommended（仅 safe 级+回收站） |
| 迁移 | robocopy /MOVE /E（跨卷带重试）→ cmd /c mklink /J 联接回填 → 探针文件读写校验 → 失败回滚；白名单根（AppData/Documents/Office 一级子目录）+ DENY 目录；体积统计 robocopy /L /E /XJ 列表模式（快 ~6.7 倍）；目标剩余 > 源 1.2 倍 |
| 页面文件 | 读 PagingFiles MultiString + Win32_PageFileUsage；建议 ≤8GB×1.5 / 8-16×1.25 / ≥16×1，封顶32GB；写回注册表重启生效 |
| 还原点 | Get-ComputerRestorePoint；策略=保留最近1个只删更早；vssadmin delete shadows /oldest 逐条；Checkpoint-Computer 创建（24h 限1个） |

## 4. 性能经验（grclean 实测注释中沉淀，pc-manager 设计参考）

- 盘符探测用原生 existsSync/statfs（3ms）而非 Get-PSDrive（实测 13.7s 且返回空）
- 目录统计并发度是关键：条目串行 21.9s → 并发10 6.9s（3.2x）；逐个 await stat
  是慢因 → 批量并发 32
- 整目录回收站 3.26s vs 逐文件 9.6s（600 文件），成本不随文件数增长
- 回收站批量 200/批并发 4-6 最优（800 文件 63s→11.6s）
- PowerShell 只读注册表：.NET Registry API 比 provider 快 ~80 倍
- 一次 PS 调用做完所有采集（PS 启动 4s 固定成本）

## 5. 未复刻项（GUI 专属，不适用 CLI/skill 形态）

8 套主题 / 全局字号缩放 / 磁盘 treemap 可视化 / 捐赠页 / 多语言 i18n（skill 直接中文）
/ 应用内更新（remote.ts + PHP 后端分发）。功能层面 23 项全部复刻。
