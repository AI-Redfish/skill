# 系统调优目录（tweaks.ps1，移植自 optimizerDuck）

来源：开源项目 [optimizerDuck](https://github.com/itsfatduck/optimizerDuck)
（WPF/.NET 10，GPLv3）。本 skill 对其 `Domain/Optimizations/Categories/*.cs`
逐项逆向，把 41 项调优的注册表/服务/计划任务改动移植为 PowerShell 目录。
**与源项目无代码拷贝关系，仅复刻其公开的调优参数与风险分级思路**；
optimizerDuck 为 GPLv3，若分发本 skill 的衍生代码请同样遵守。

## 与 optimizerDuck 的设计对应

| optimizerDuck | pc-manager tweaks.ps1 |
|---|---|
| 42 项 Optimization（C# 类 + RegistryService/ServiceProcess/ScheduledTask） | 41 项目录（hashtable 目录 + reg/regdel/svc/task/hiber/usb/plan 七类步骤） |
| Revert 数据 `%LocalAppData%\optimizerDuck\Revert\{id}.json`（applied 以文件存在为准） | `%LOCALAPPDATA%\pc-manager\tweaks\{id}.json`（同设计） |
| 风险 Safe / Moderate / Risky | safe / caution / danger（Safe→safe，Moderate→caution，Risky→danger） |
| 条件系统（Win10/Win11、GPU 品牌、Recall 已装等 Condition） | `os`/`vendor` 字段 + apply/list 时动态判定（build ≥22000 = Win11；`Win32_VideoController` 名称匹配厂商；`VideoControllerN` → Display Class 索引 `0000…`） |
| 每步 revert 自校验（read-back） | reg 写入后读回校验，不一致记 failed |

**未移植项（有意为之，见各处说明）**：
- `ConfigureServices`（200+ 服务启动类型重整，Risky 级）——CLI+AI 编排形态无法
  逐项复核 200 个服务，误伤面太大；`optimize.ps1 service-delay` 已覆盖"延迟启动"
  这一安全子集。
- 自带 `.pow` 电源计划导入（二进制资源）——改用 Windows 内置"终极性能"计划
  `powercfg /duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61` 等价实现。
- AppX bloatware 批量卸载——`uninstall.ps1` 已覆盖（触发原生卸载器更稳）。

## 目录清单（41 项）

`risk`：safe=可放心应用 / caution=需用户确认（对应 optimizerDuck Moderate）。
`os` 列：win10/win11 = 仅该版本适用（脚本自动跳过不适用的）。
`管理员`：●=需管理员（HKLM 写入/服务/任务/电源操作），○=当前用户即可。

### 性能（7 项）

| id | 名称 | 风险 | 管理员 | 改动要点（源自 optimizerDuck 对应类） |
|---|---|---|---|---|
| perf-bgapps | 禁用后台应用 | caution | ○ | HKCU BackgroundAccessApplications\GlobalUserDisabled=1；Search\BackgroundAppGlobalToggle=0（DisableBackgroundApps） |
| perf-svchost | 合并服务进程 | caution | ● | SvcHostSplitThresholdInKB=物理内存KB（运行时读取，ConsolidateServiceHosts） |
| perf-priority | 前台优先级 | safe | ● | Win32PrioritySeparation=38（ProcessPriority） |
| perf-mmcss | 多媒体调度 | safe | ● | SystemProfile 4 值 + Tasks\Games 4 值（OptimizeMultimediaScheduler） |
| perf-keyboard | 键盘响应 | safe | ○ | KeyboardDelay=0/KeyboardSpeed=31（REG_SZ，KeyboardLatency） |
| perf-hotkeys | 辅助热键 | caution | ○ | StickyKeys/Keyboard Response/ToggleKeys Flags（DisableAccessibilityKeyboardHotkeys） |
| perf-webdav | WebDAV 上限 | safe | ● | FileSizeLimitInBytes=0xFFFFFFFF（LiftWebDavFileSizeLimit） |

### 隐私（13 项）

| id | 名称 | 风险 | 管理员 | 改动要点 |
|---|---|---|---|---|
| priv-telemetry | 遥测与反馈 | caution | ● | 14 处注册表 + 删 PeriodInNanoSeconds + 停 DiagTrack/dmwappushservice/DcpSvc/diagnosticshub.standardcollector.service + 禁 10 个遥测任务（DisableTelemetry，最大单项） |
| priv-errorreport | 错误报告 | caution | ● | WER Disabled=1 + 停 WerSvc/PcaSvc + 禁 4 任务（DisableErrorReporting） |
| priv-ads | 广告与推荐 | safe | ● | AdvertisingInfo/CloudContent/InputPersonalization 等 12 值（DisableAdvertisingAndSuggestions） |
| priv-news | 资讯与兴趣 | safe | ● | Dsh AllowNewsAndInterests=0 + Feeds 视图模式（DisableNewsAndInterests） |
| priv-meetnow | Meet Now | safe | ○ | HideSCAMeetNow=1，仅 Win10（HideMeetNowButton） |
| priv-activity | 活动历史 | safe | ● | System 策略 4 值（DisableActivityHistory） |
| priv-location | 位置与传感器 | safe | ● | LocationAndSensors/CapabilityAccessManager/lfsvc 等 10 值 + 禁 MapsUpdateTask（DisableLocationAndSensors） |
| priv-autologger | WMI 日志 | caution | ● | Autologger 10 会话 Start=0（DisableAutoLogger） |
| priv-cortana | Cortana | caution | ● | Windows Search 策略 5 值 + HKCU Consent 2 值，仅 Win10（DisableCortana） |
| priv-copilot | Copilot | caution | ● | WindowsCopilot 策略 HKLM+HKCU + 隐藏按钮 + Shell Extensions Blocked CLSID，仅 Win11（DisableCopilot） |
| priv-cdm | 内容传递 | safe | ○ | ContentDeliveryManager 6 值（DisableContentDeliveryManager） |
| priv-findmy | 查找设备 | safe | ● | FindMyDevice 策略 1 值（DisableFindMyDevice） |
| priv-deliveryopt | 传递优化 | safe | ● | DODownloadMode=0（DisableDeliveryOptimization） |

### 显卡（8 项，按厂商自动匹配；不适用的厂商项 list/apply 自动跳过）

注册表根：`HKLM\SYSTEM\CCS\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000…`
（每块匹配显卡各写一份；索引由 `Win32_VideoController.DeviceID` 换算）。

| id | 名称 | 风险 | 改动 |
|---|---|---|---|
| gpu-amd-ulps | AMD ULPS | safe | EnableULPS=0 |
| gpu-amd-powergating | AMD 电源门控 | caution | DisablePowerGating=1, PP_GPUPowerDownEnabled=0, DisableDynamicPstate=1 |
| gpu-amd-vce | AMD 视频时钟门控 | caution | DisableVCEPowerGating=1, DisableVceClockGating=1, EnableUvdClockGating=0, EnableVceSwClockGating=0 |
| gpu-amd-aspm | AMD ASPM | safe | EnableAspmL0s=0, EnableAspmL1=0 |
| gpu-nv-pstate | NVIDIA 动态调频 | safe | DisableDynamicPstate=1 |
| gpu-nv-async | NVIDIA 异步 P 状态 | caution | DisableASyncPstates=1 |
| gpu-int-asyncflips | Intel 异步翻转 | safe | Display1_DisableAsyncFlips=1 |
| gpu-int-vsync | Intel 自适应垂直同步 | safe | AdaptiveVsyncEnable=0 |

### 电源（4 项）

| id | 名称 | 风险 | 改动 |
|---|---|---|---|
| power-hibernation | 休眠与快速启动 | caution | `powercfg /h off`（备份 hiberfil.sys 原状态，revert 按需 `/h on`；与 slim.ps1 hibernation 项同一底层操作，此处多了可回滚记录） |
| power-usb | USB 选择性暂停 | safe | root\wmi MSPower_DeviceEnable 逐设备 Enable=false（备份每台设备原值，revert 逐台还原） |
| power-saving | 电源节制特性 | safe | AutomaticSurpriseRemoval AttemptRecoveryFromUsbPowerDrain=0 + PowerThrottlingOff=1（DisablePowerSaving） |
| power-ultimateplan | 极致性能计划 | safe | duplicatescheme 内置"终极性能"模板并激活（备份原活动计划 GUID，revert 恢复+删除新建计划） |

### 体验（6 项）

| id | 名称 | 风险 | 管理员 | 改动 |
|---|---|---|---|---|
| ux-menus | 菜单提速 | safe | ○ | Serialize\StartupDelayInMSec=0 + MenuShowDelay=0 |
| ux-visual | 视觉特效 | safe | ○ | TaskbarAnimations/ListviewShadow/EnableTransparency/EnableAeroPeek=0 |
| ux-websearch | 开始菜单联网搜索 | safe | ○ | HKCU 策略 DisableSearchBoxSuggestions=1 |
| ux-recommended | 开始菜单推荐区 | safe | ○ | HKCU 策略 HideRecommendedSection=1，仅 Win11 |
| ux-365ads | 设置页 365 广告 | safe | ● | DisableConsumerAccountStateContent=1 |
| ux-updatepause | 更新暂停上限 | safe | ● | FlightSettingsMaxPauseDays=0xFFFFFFFF（副作用：安全更新也会被长期暂停） |

### AI（2 项，均仅 Win11）

| id | 名称 | 风险 | 改动 |
|---|---|---|---|
| ai-recall | Recall 快照 | caution | WindowsAI：DisableAIDataAnalysis=1（HKLM+HKCU）、AllowRecallEnablement=0、TurnOffSavingSnapshots=1 |
| ai-clicktodo | Click To Do | safe | DisableClickToDo=1（HKLM+HKCU） |

### 预装（1 项）

| id | 名称 | 风险 | 改动 |
|---|---|---|---|
| bloat-preinstall | 预装应用回归 | safe | ContentDeliveryManager：PreInstalledApps/PreInstalledAppsEver/OemPreInstalled/SilentInstalled Enabled=0 |

## 动作与输出

| 动作 | 参数 | 输出要点 |
|---|---|---|
| list | — | admin/os_build/gpus + tweaks（id,category,name,risk,desc,applicable,need_admin,applied）；applied 的 live 检测基于 reg/svc 步骤全中，gpu/usb/plan 类以状态文件为准 |
| apply | `-Ids a,b [-Force]` | applied（id,steps_ok/skipped/failed,state_file）/ skipped（含原因）/ errors |
| revert | `-Ids a,b` | restored（id,steps_restored,partial）/ errors |
| status | — | 已应用清单（id,applied_at,file） |

apply 的安全序列（每项独立）：适用性判定 → 权限检查 → **备份全部旧状态**
（备份失败该项中止、绝不写入）→ 写入（reg 写后读回校验）→ 落回滚数据 → 审计。
部分项失败不影响其他项，如实分列 applied/skipped/errors。

## AI 编排要点

1. 先 `list` 再按用户诉求挑项；caution 项逐项向用户确认后再 apply
2. 显卡项不用问用户有没有——list 会自动标注 applicable，直接挑适用项
3. `ux-updatepause`/`power-ultimateplan`/`priv-autologger` 有明确副作用，
   展示清单时必须带上 desc 里的副作用说明
4. 用户说"恢复默认/撤销优化" → revert；一次撤销多项用逗号传 id
5. apply/revert 后提醒：部分项需重启或重登录生效；重大改动前建议先建还原点
   （`restore.ps1 -Action create`）
