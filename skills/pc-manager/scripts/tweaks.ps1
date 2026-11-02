<#
tweaks.ps1 — 系统调优（性能/隐私/显卡/电源/体验/AI，41 项，每项可独立回滚）

移植自开源项目 optimizerDuck（github.com/itsfatduck/optimizerDuck，GPLv3）的
调优目录：注册表/服务/计划任务改动值逐一对照其源码，风险分级沿用本项目
safe/caution/danger 体系（optimizerDuck 的 Safe→safe、Moderate→caution、
Risky→danger；其 Risky 级 200+ 服务重整未移植——CLI 形态无法逐项复核）。

安全模型（与 registry.ps1 同源）：
  1. 只接受内置目录里的 id，不接受调用方传入的任何注册表路径/服务名/任务名
  2. apply 前先完整备份每项旧状态（值/类型/服务启动类型/任务状态/休眠状态/
     USB 供电状态/电源计划）；任一项备份失败则该项中止、绝不写入
  3. caution 级需用户显式确认（AI 编排层保证）；danger 级（当前无）需 -Force
  4. 需管理员的项在无权限时如实归类为 skipped 并说明，不静默跳过
  5. 回滚数据存 %LOCALAPPDATA%\pc-manager\tweaks\<id>.json（一项一文件，
     applied 状态以文件存在为准，复刻 optimizerDuck Revert 设计）
  6. 全部 apply/revert 写审计日志

动作:
  list    列出全部调优项（适用性/风险/是否已应用；live 检测基于 reg/svc 步骤）
  apply   -Ids id1,id2 [-Force]   应用（先备份→再写入→存回滚数据→审计）
  revert  -Ids id1,id2            按回滚数据恢复原状
  status  查看已应用项（回滚数据文件清单）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File tweaks.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File tweaks.ps1 -Action apply -Ids priv-telemetry,perf-keyboard
  powershell -NoProfile -ExecutionPolicy Bypass -File tweaks.ps1 -Action revert -Ids priv-telemetry
  powershell -NoProfile -ExecutionPolicy Bypass -File tweaks.ps1 -Action status

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('list', 'apply', 'revert', 'status')][string]$Action = 'list',
    [string]$Ids = '',
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking

function Get-StateDir {
    $dir = Join-Path (Get-PcManagerDir) 'tweaks'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

# ---------- 环境 ----------
function Get-OSBuild {
    try {
        $p = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop
        return [int]$p.CurrentBuild
    } catch { return 0 }
}

function Get-RamKB {
    try {
        $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        return [int64]($cs.TotalPhysicalMemory / 1KB)
    } catch { return 0 }
}

function Get-GpuAdapters {
    <# 显卡适配器：vendor(amd|nvidia|intel) + 注册表 Display Class 索引(0000…)。
    复刻 Gpu.TryParseDeviceIdToIndex：Win32_VideoController DeviceID "VideoControllerN" → 索引 N-1。 #>
    $out = @()
    try {
        foreach ($v in (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue)) {
            $name = "$($v.Name)"
            $vendor = ''
            if ($name -match 'AMD|Radeon') { $vendor = 'amd' }
            elseif ($name -match 'NVIDIA|GeForce|Quadro') { $vendor = 'nvidia' }
            elseif ($name -match 'Intel') { $vendor = 'intel' }
            if (-not $vendor) { continue }
            if ("$($v.DeviceID)" -match 'VideoController(\d+)$') {
                $idx = [int]$Matches[1] - 1
                if ($idx -ge 0) {
                    $out += @{ vendor = $vendor; index = ('{0:D4}' -f $idx); name = $name }
                }
            }
        }
    } catch { }
    return $out
}

function Test-TweakAdmin {
    return Test-Admin
}

# ---------- 调优目录（值与 optimizerDuck 源码逐一对照；gpu 步骤在执行时按适配器展开） ----------
function Get-TweakCatalog {
    $perf = 'HKLM:\SYSTEM\CurrentControlSet\Control'
    $pol  = 'HKLM:\SOFTWARE\Policies\Microsoft'
    $tsys = "$pol\Windows\System"
    $wai  = "$pol\Windows\WindowsAI"
    $waic = 'HKCU:\Software\Policies\Microsoft\Windows\WindowsAI'

    return @(
        # ===== 性能 =====
        @{ id='perf-bgapps'; cat='性能'; risk='caution'; os=''; vendor=''
           name='禁用后台应用'
           desc='禁止 UWP 应用在后台运行（省内存/CPU；后台通知与实时磁贴会失效）'
           steps=@(
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications'; n='GlobalUserDisabled'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Search'; n='BackgroundAppGlobalToggle'; v=0; ty='DWord'}) }
        @{ id='perf-svchost'; cat='性能'; risk='caution'; os=''; vendor=''
           name='合并服务进程（SvcHost 分组阈值=物理内存）'
           desc='按内存总量设 SvcHostSplitThresholdInKB，减少 svchost 进程数（大内存机器进程更少；排障时不易按组隔离）'
           steps=@(@{t='svchost'}) }
        @{ id='perf-priority'; cat='性能'; risk='safe'; os=''; vendor=''
           name='前台进程优先级提升'
           desc='Win32PrioritySeparation=38（短周期+高前台增益，前台程序获得更多 CPU 时间片）'
           steps=@(@{t='reg'; k="$perf\PriorityControl"; n='Win32PrioritySeparation'; v=38; ty='DWord'}) }
        @{ id='perf-mmcss'; cat='性能'; risk='safe'; os=''; vendor=''
           name='多媒体调度优化（MMCSS）'
           desc='后台多媒体调度保活+网络限流解除+游戏线程高优先级（降低音频/显示延迟）'
           steps=@(
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'; n='NoLazyMode'; v=1; ty='DWord'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'; n='AlwaysOn'; v=1; ty='DWord'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'; n='NetworkThrottlingIndex'; v=-1; ty='DWord'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'; n='SystemResponsiveness'; v=10; ty='DWord'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games'; n='Priority'; v=2; ty='DWord'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games'; n='Scheduling Category'; v='High'; ty='String'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games'; n='SFIO Priority'; v='High'; ty='String'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games'; n='GPU Priority'; v=8; ty='DWord'}) }
        @{ id='perf-keyboard'; cat='性能'; risk='safe'; os=''; vendor=''
           name='键盘响应优化'
           desc='键盘重复延迟最短+重复速率最快（打字手感变化明显，可随时还原）'
           steps=@(
               @{t='reg'; k='HKCU:\Control Panel\Keyboard'; n='KeyboardDelay'; v='0'; ty='String'},
               @{t='reg'; k='HKCU:\Control Panel\Keyboard'; n='KeyboardSpeed'; v='31'; ty='String'}) }
        @{ id='perf-hotkeys'; cat='性能'; risk='caution'; os=''; vendor=''
           name='关闭辅助功能键盘热键'
           desc='禁用粘滞键/筛选键/切换键的 Shift 连按等触发（游戏误触 StickyKeys 提示的场景）'
           steps=@(
               @{t='reg'; k='HKCU:\Control Panel\Accessibility\StickyKeys'; n='Flags'; v='26'; ty='String'},
               @{t='reg'; k='HKCU:\Control Panel\Accessibility\Keyboard Response'; n='Flags'; v='2'; ty='String'},
               @{t='reg'; k='HKCU:\Control Panel\Accessibility\ToggleKeys'; n='Flags'; v='34'; ty='String'}) }
        @{ id='perf-webdav'; cat='性能'; risk='safe'; os=''; vendor=''
           name='解除 WebDAV 4GB 传输上限'
           desc='FileSizeLimitInBytes=0xFFFFFFFF（仅影响 WebClient 映射盘的大文件复制）'
           steps=@(@{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Services\WebClient\Parameters'; n='FileSizeLimitInBytes'; v=-1; ty='DWord'}) }

        # ===== 隐私 =====
        @{ id='priv-telemetry'; cat='隐私'; risk='caution'; os=''; vendor=''
           name='关闭遥测与反馈'
           desc='诊断数据级别调至最低+关反馈+关兼容性遥测；停 DiagTrack/dmwappushservice 等诊断服务与 10 个遥测计划任务'
           steps=@(
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\DataCollection'; n='AllowTelemetry'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\DataCollection"; n='AllowTelemetry'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\DataCollection"; n='DoNotShowFeedbackNotifications'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\DataCollection"; n='AllowCommercialDataPipeline'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\DataCollection"; n='AllowDeviceNameInTelemetry'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\DataCollection"; n='MicrosoftEdgeDataOptIn'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Siuf\Rules'; n='NumberOfSIUFInPeriod'; v=0; ty='DWord'},
               @{t='regdel'; k='HKCU:\SOFTWARE\Microsoft\Siuf\Rules'; n='PeriodInNanoSeconds'},
               @{t='reg'; k="$cup\Policies\Microsoft\Windows\EdgeUI"; n='DisableMFUTracking'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\AppCompat"; n='DisableInventory'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\AppCompat"; n='AITEnable'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Policies\Microsoft\Assistance\Client\1.0'; n='NoExplicitFeedback'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Assistance\Client\1.0"; n='NoActiveHelp'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy'; n='HasAccepted'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; n='Start_TrackProgs'; v=0; ty='DWord'},
               @{t='svc'; n='DiagTrack'; v='disabled'},
               @{t='svc'; n='dmwappushservice'; v='disabled'},
               @{t='svc'; n='DcpSvc'; v='disabled'},
               @{t='svc'; n='diagnosticshub.standardcollector.service'; v='disabled'},
               @{t='task'; p='\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser'},
               @{t='task'; p='\Microsoft\Windows\Application Experience\ProgramDataUpdater'},
               @{t='task'; p='\Microsoft\Windows\Application Experience\MareBackup'},
               @{t='task'; p='\Microsoft\Windows\Application Experience\StartupAppTask'},
               @{t='task'; p='\Microsoft\Windows\Application Experience\PcaPatchDbTask'},
               @{t='task'; p='\Microsoft\Windows\Autochk\Proxy'},
               @{t='task'; p='\Microsoft\Windows\Customer Experience Improvement Program\Consolidator'},
               @{t='task'; p='\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip'},
               @{t='task'; p='\Microsoft\Windows\Feedback\Siuf\DmClient'},
               @{t='task'; p='\Microsoft\Windows\Feedback\Siuf\DmClientOnScenarioDownload'}) }
        @{ id='priv-errorreport'; cat='隐私'; risk='caution'; os=''; vendor=''
           name='关闭错误报告与兼容性助手'
           desc='停 Windows 错误上报、手写错误报告与程序兼容性助手（WerSvc/PcaSvc）及相关计划任务'
           steps=@(
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting'; n='Disabled'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\HandwritingErrorReports"; n='PreventHandwritingErrorReports'; v=1; ty='DWord'},
               @{t='svc'; n='WerSvc'; v='disabled'},
               @{t='svc'; n='PcaSvc'; v='disabled'},
               @{t='task'; p='\Microsoft\Windows\Windows Error Reporting\QueueReporting'},
               @{t='task'; p='\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticDataCollector'},
               @{t='task'; p='\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticResolver'},
               @{t='task'; p='\Microsoft\Windows\Diagnosis\Scheduled'}) }
        @{ id='priv-ads'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭广告 ID 与系统推荐'
           desc='广告 ID、定制体验、消费者特性、第三方应用推荐、输入个性化采集全部关闭'
           steps=@(
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo'; n='Enabled'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\AdvertisingInfo"; n='DisabledByGroupPolicy'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Privacy'; n='TailoredExperiencesWithDiagnosticDataEnabled'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\CloudContent"; n='DisableTailoredExperiencesWithDiagnosticData'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\CloudContent"; n='DisableWindowsConsumerFeatures'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\CloudContent"; n='DisableSoftLanding'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\CloudContent"; n='DisableThirdPartySuggestions'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement'; n='ScoobeSystemSettingEnabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\InputPersonalization'; n='RestrictImplicitInkCollection'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\InputPersonalization'; n='RestrictImplicitTextCollection'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\InputPersonalization\TrainedDataStore'; n='HarvestContacts'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Control Panel\International\User Profile'; n='HttpAcceptLanguageOptOut'; v=1; ty='DWord'}) }
        @{ id='priv-news'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭资讯与兴趣'
           desc='任务栏新闻/天气资讯流关闭（Win10 任务栏与 Win11 Widgets 的内容推送面）'
           steps=@(
               @{t='reg'; k="$pol\Dsh"; n='AllowNewsAndInterests'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Feeds'; n='ShellFeedsTaskbarViewMode'; v=0; ty='DWord'}) }
        @{ id='priv-meetnow'; cat='隐私'; risk='safe'; os='win10'; vendor=''
           name='隐藏任务栏 Meet Now 按钮'
           desc='移除 Win10 任务栏的 Meet Now 视频会议入口'
           steps=@(@{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'; n='HideSCAMeetNow'; v=1; ty='DWord'}) }
        @{ id='priv-activity'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭活动历史记录'
           desc='时间线活动采集与跨设备上传全部关闭'
           steps=@(
               @{t='reg'; k=$tsys; n='PublishUserActivities'; v=0; ty='DWord'},
               @{t='reg'; k=$tsys; n='EnableActivityFeed'; v=0; ty='DWord'},
               @{t='reg'; k=$tsys; n='PublishUserActivitiesOnUserConsent'; v=0; ty='DWord'},
               @{t='reg'; k=$tsys; n='UploadUserActivities'; v=0; ty='DWord'}) }
        @{ id='priv-location'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭位置与传感器'
           desc='定位服务、传感器、地图自动更新、WiFi 热点报告全部关闭'
           steps=@(
               @{t='reg'; k="$pol\Windows\LocationAndSensors"; n='DisableLocation'; v=1; ty='DWord'},
               @{t='reg'; k="$pol\Windows\LocationAndSensors"; n='DisableSensors'; v=1; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\Maps'; n='AutoUpdateEnabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Sensor\Permissions\{BFA794E4-F964-4FDB-90F6-51056BFE4B44}'; n='SensorPermissionState'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location'; n='Value'; v='Deny'; ty='String'},
               @{t='reg'; k='HKLM:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location'; n='Value'; v='Deny'; ty='String'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Geolocation'; n='Status'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Services\lfsvc\Service\Configuration'; n='Status'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\Software\Microsoft\PolicyManager\default\WiFi\AllowWiFiHotSpotReporting'; n='Value'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\Software\Microsoft\PolicyManager\default\WiFi\AllowAutoConnectToWiFiSenseHotspots'; n='Value'; v=0; ty='DWord'},
               @{t='task'; p='\Microsoft\Windows\Maps\MapsUpdateTask'}) }
        @{ id='priv-autologger'; cat='隐私'; risk='caution'; os=''; vendor=''
           name='关闭 WMI AutoLogger 诊断会话'
           desc='停 10 个开机即录的诊断日志会话（减少磁盘写入；排查系统问题时缺这些日志）'
           steps=@(
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\AppModel'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\Cellcore'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\CloudExperienceHostOobe'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\DataMarket'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\DiagLog'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\Diagtrack-Listener'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\LwtNetLog'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\SQMLogger'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\WdiContextLog'; n='Start'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger\WiFiSession'; n='Start'; v=0; ty='DWord'}) }
        @{ id='priv-cortana'; cat='隐私'; risk='caution'; os='win10'; vendor=''
           name='关闭 Cortana 与搜索联网'
           desc='Cortana 与开始搜索的云内容全部关闭（Win10；Win11 用 priv-copilot 与 ux-websearch）'
           steps=@(
               @{t='reg'; k="$pol\Windows\Windows Search"; n='AllowCortana'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\Windows Search"; n='AllowCloudSearch'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\Windows Search"; n='AllowCortanaAboveLock'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\Windows Search"; n='AllowSearchToUseLocation'; v=0; ty='DWord'},
               @{t='reg'; k="$pol\Windows\Windows Search"; n='ConnectedSearchUseWeb'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Search'; n='CortanaConsent'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Search'; n='CortanaConsent2'; v=0; ty='DWord'}) }
        @{ id='priv-copilot'; cat='隐私'; risk='caution'; os='win11'; vendor=''
           name='关闭 Windows Copilot'
           desc='策略关闭 Copilot 并隐藏任务栏按钮（Win11）'
           steps=@(
               @{t='reg'; k="$pol\Windows\WindowsCopilot"; n='TurnOffWindowsCopilot'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Policies\Microsoft\Windows\WindowsCopilot'; n='TurnOffWindowsCopilot'; v=1; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; n='ShowCopilotButton'; v=0; ty='DWord'},
               @{t='reg'; k='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked'; n='{CB3B0003-8088-4EDE-8769-8B354AB2FF8C}'; v=''; ty='String'}) }
        @{ id='priv-cdm'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭内容传递管理器'
           desc='开始菜单/锁屏的建议与应用推广推送关闭'
           steps=@(
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='ContentDeliveryAllowed'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='SubscribedContent-338387Enabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='SubscribedContent-338388Enabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='SubscribedContent-338389Enabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='SubscribedContent-353698Enabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='SystemPaneSuggestionsEnabled'; v=0; ty='DWord'}) }
        @{ id='priv-findmy'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭"查找我的设备"'
           desc='停止设备位置上报到微软账户'
           steps=@(@{t='reg'; k="$pol\FindMyDevice"; n='AllowFindMyDevice'; v=0; ty='DWord'}) }
        @{ id='priv-deliveryopt'; cat='隐私'; risk='safe'; os=''; vendor=''
           name='关闭传递优化 P2P 分享'
           desc='停止向局域网/互联网设备分享 Windows 更新带宽（下载模式改为仅本机）'
           steps=@(@{t='reg'; k="$pol\Windows\DeliveryOptimization"; n='DODownloadMode'; v=0; ty='DWord'}) }

        # ===== 显卡（按厂商自动匹配，不适用的项 list 会标注） =====
        @{ id='gpu-amd-ulps'; cat='显卡'; risk='safe'; os=''; vendor='amd'
           name='AMD 关闭 ULPS'
           desc='超低功耗状态关闭（多卡/核显+独显混交场景减少帧同步开销）'
           steps=@(@{t='gpu'; vals=@(@{n='EnableULPS'; v=0; ty='DWord'})}) }
        @{ id='gpu-amd-powergating'; cat='显卡'; risk='caution'; os=''; vendor='amd'
           name='AMD 关闭电源门控'
           desc='GPU 电源门控/动态调频关闭（延迟更低，待机功耗升高）'
           steps=@(@{t='gpu'; vals=@(
               @{n='DisablePowerGating'; v=1; ty='DWord'},
               @{n='PP_GPUPowerDownEnabled'; v=0; ty='DWord'},
               @{n='DisableDynamicPstate'; v=1; ty='DWord'})}) }
        @{ id='gpu-amd-vce'; cat='显卡'; risk='caution'; os=''; vendor='amd'
           name='AMD 关闭视频引擎时钟门控'
           desc='VCE/UVD 编解码引擎常供电（录屏/推流延迟更低，待机功耗升高）'
           steps=@(@{t='gpu'; vals=@(
               @{n='DisableVCEPowerGating'; v=1; ty='DWord'},
               @{n='DisableVceClockGating'; v=1; ty='DWord'},
               @{n='EnableUvdClockGating'; v=0; ty='DWord'},
               @{n='EnableVceSwClockGating'; v=0; ty='DWord'})}) }
        @{ id='gpu-amd-aspm'; cat='显卡'; risk='safe'; os=''; vendor='amd'
           name='AMD 关闭 PCIe ASPM'
           desc='GPU 链路节能状态 L0s/L1 关闭（降低延迟；整机功耗略升）'
           steps=@(@{t='gpu'; vals=@(
               @{n='EnableAspmL0s'; v=0; ty='DWord'},
               @{n='EnableAspmL1'; v=0; ty='DWord'})}) }
        @{ id='gpu-nv-pstate'; cat='显卡'; risk='safe'; os=''; vendor='nvidia'
           name='NVIDIA 关闭动态调频'
           desc='DynamicPstate 关闭（GPU 保持就绪频率，降低突发负载首帧延迟）'
           steps=@(@{t='gpu'; vals=@(@{n='DisableDynamicPstate'; v=1; ty='DWord'})}) }
        @{ id='gpu-nv-async'; cat='显卡'; risk='caution'; os=''; vendor='nvidia'
           name='NVIDIA 关闭异步 P 状态'
           desc='ASyncPstates 关闭（进一步压延迟；待机功耗升高）'
           steps=@(@{t='gpu'; vals=@(@{n='DisableASyncPstates'; v=1; ty='DWord'})}) }
        @{ id='gpu-int-asyncflips'; cat='显卡'; risk='safe'; os=''; vendor='intel'
           name='Intel 关闭异步翻转'
           desc='Display1_DisableAsyncFlips（降低显示管线延迟）'
           steps=@(@{t='gpu'; vals=@(@{n='Display1_DisableAsyncFlips'; v=1; ty='DWord'})}) }
        @{ id='gpu-int-vsync'; cat='显卡'; risk='safe'; os=''; vendor='intel'
           name='Intel 关闭自适应垂直同步'
           desc='AdaptiveVsyncEnable=0（交给游戏/驱动面板自己控制同步）'
           steps=@(@{t='gpu'; vals=@(@{n='AdaptiveVsyncEnable'; v=0; ty='DWord'})}) }

        # ===== 电源 =====
        @{ id='power-hibernation'; cat='电源'; risk='caution'; os=''; vendor=''
           name='关闭休眠与快速启动'
           desc='powercfg -h off，立即释放与内存等大的 hiberfil.sys（台式机常用；笔记本会失去休眠。slim.ps1 的 hibernation 项是同一操作的 C 盘瘦身视角）'
           steps=@(@{t='hiber'}) }
        @{ id='power-usb'; cat='电源'; risk='safe'; os=''; vendor=''
           name='关闭 USB 选择性暂停'
           desc='USB 设备停止节能挂起（外设/采集卡掉线重连问题的常用解法）'
           steps=@(@{t='usb'}) }
        @{ id='power-saving'; cat='电源'; risk='safe'; os=''; vendor=''
           name='关闭电源节制特性'
           desc='USB 意外移除恢复尝试关闭+PowerThrottling 关闭（后台进程不再被降频）'
           steps=@(
               @{t='reg'; k="$perf\USB\AutomaticSurpriseRemoval"; n='AttemptRecoveryFromUsbPowerDrain'; v=0; ty='DWord'},
               @{t='reg'; k="$perf\Power\PowerThrottling"; n='PowerThrottlingOff'; v=1; ty='DWord'}) }
        @{ id='power-ultimateplan'; cat='电源'; risk='safe'; os=''; vendor=''
           name='启用极致性能电源计划'
           desc='导入并激活 Windows 内置"终极性能"计划（台式机向；笔记本续航明显下降）'
           steps=@(@{t='plan'; template='e9a42b02-d5df-448d-aa00-03f14749eb61'}) }

        # ===== 体验 =====
        @{ id='ux-menus'; cat='体验'; risk='safe'; os=''; vendor=''
           name='菜单与资源管理器提速'
           desc='Explorer 启动延迟与菜单弹出延迟归零（手感更跟手）'
           steps=@(
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize'; n='StartupDelayInMSec'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Control Panel\Desktop'; n='MenuShowDelay'; v='0'; ty='String'}) }
        @{ id='ux-visual'; cat='体验'; risk='safe'; os=''; vendor=''
           name='精简视觉特效'
           desc='任务栏动画、列表阴影、透明度、Aero Peek 关闭（低配机更明显）'
           steps=@(
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; n='TaskbarAnimations'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'; n='ListviewShadow'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'; n='EnableTransparency'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\Software\Microsoft\Windows\DWM'; n='EnableAeroPeek'; v=0; ty='DWord'}) }
        @{ id='ux-websearch'; cat='体验'; risk='safe'; os=''; vendor=''
           name='关闭开始菜单联网搜索'
           desc='开始搜索不再查 Bing 与网页建议（纯本地搜索，更快更隐私）'
           steps=@(@{t='reg'; k='HKCU:\Software\Policies\Microsoft\Windows\Explorer'; n='DisableSearchBoxSuggestions'; v=1; ty='DWord'}) }
        @{ id='ux-recommended'; cat='体验'; risk='safe'; os='win11'; vendor=''
           name='关闭开始菜单"推荐"区'
           desc='Win11 开始菜单的推荐/最近文件区域隐藏'
           steps=@(@{t='reg'; k='HKCU:\SOFTWARE\Policies\Microsoft\Windows\Explorer'; n='HideRecommendedSection'; v=1; ty='DWord'}) }
        @{ id='ux-365ads'; cat='体验'; risk='safe'; os=''; vendor=''
           name='关闭设置页 Microsoft 365 广告'
           desc='设置里推送的 Microsoft 365 消费者账户推广内容关闭'
           steps=@(@{t='reg'; k="$pol\Windows\CloudContent"; n='DisableConsumerAccountStateContent'; v=1; ty='DWord'}) }
        @{ id='ux-updatepause'; cat='体验'; risk='safe'; os=''; vendor=''
           name='放开更新暂停上限'
           desc='FlightSettingsMaxPauseDays=0xFFFFFFFF（设置里可一次暂停更新到极限天数；安全更新也会被暂停，请自行定期恢复）'
           steps=@(@{t='reg'; k='HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'; n='FlightSettingsMaxPauseDays'; v=-1; ty='DWord'}) }

        # ===== AI（Win11） =====
        @{ id='ai-recall'; cat='AI'; risk='caution'; os='win11'; vendor=''
           name='关闭 Windows Recall 快照'
           desc='策略关闭 Recall 截屏快照与保存（隐私敏感功能；未装 Recall 的机器策略同样安全）'
           steps=@(
               @{t='reg'; k=$wai; n='DisableAIDataAnalysis'; v=1; ty='DWord'},
               @{t='reg'; k=$wai; n='AllowRecallEnablement'; v=0; ty='DWord'},
               @{t='reg'; k=$wai; n='TurnOffSavingSnapshots'; v=1; ty='DWord'},
               @{t='reg'; k=$waic; n='DisableAIDataAnalysis'; v=1; ty='DWord'}) }
        @{ id='ai-clicktodo'; cat='AI'; risk='safe'; os='win11'; vendor=''
           name='关闭 Click To Do 浮层'
           desc='Win11 的 AI"点击即做"覆盖层关闭'
           steps=@(
               @{t='reg'; k=$wai; n='DisableClickToDo'; v=1; ty='DWord'},
               @{t='reg'; k=$waic; n='DisableClickToDo'; v=1; ty='DWord'}) }

        # ===== 预装 =====
        @{ id='bloat-preinstall'; cat='预装'; risk='safe'; os=''; vendor=''
           name='阻止预装应用回归'
           desc='ContentDeliveryManager 的预装/OEM 静默安装通道关闭（卸掉的厂商应用不再被悄悄装回）'
           steps=@(
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='PreInstalledAppsEnabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='PreInstalledAppsEverEnabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='OemPreInstalledAppsEnabled'; v=0; ty='DWord'},
               @{t='reg'; k='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; n='SilentInstalledAppsEnabled'; v=0; ty='DWord'}) }
    )
}

# ---------- 步骤展开（gpu→reg；svchost→注入 RAM 值） ----------
function Expand-TweakSteps {
    param([Parameter(Mandatory)]$Tweak)
    $out = @()
    foreach ($s in @($Tweak.steps)) {
        if ($s.t -eq 'gpu') {
            foreach ($a in (Get-GpuAdapters | Where-Object { $_.vendor -eq $Tweak.vendor })) {
                $base = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\$($a.index)"
                foreach ($v in @($s.vals)) {
                    $out += @{ t='reg'; k=$base; n=$v.n; v=$v.v; ty=$v.ty }
                }
            }
        } elseif ($s.t -eq 'svchost') {
            $ram = Get-RamKB
            if ($ram -le 0) { return @() }   # 内存读取失败 → 不可用（与 optimizerDuck InvalidRAM 一致）
            $out += @{ t='reg'; k='HKLM:\SYSTEM\CurrentControlSet\Control'; n='SvcHostSplitThresholdInKB'; v=$ram; ty='DWord' }
        } else {
            $out += $s
        }
    }
    return $out
}

function Step-NeedAdmin {
    param([Parameter(Mandatory)]$Step)
    if ($Step.t -in @('svc', 'task', 'hiber', 'usb', 'plan', 'svchost')) { return $true }
    if ($Step.t -eq 'reg' -or $Step.t -eq 'regdel') { return ("$($Step.k)" -match '^HKLM:') }
    return $false
}

# ---------- 旧状态采集 ----------
function Get-RegBackup {
    param([string]$Key, [string]$Name)
    # key_existed：键本身原先是否存在（optimizerDuck RegistryRevertStep 会清理自己创建的键，
    # 恢复时若键原先不存在且已空则一并删除）
    $r = @{ existed = $false; kind = ''; value = $null; key_existed = $false }
    try {
        $k = Get-Item -LiteralPath $Key -ErrorAction SilentlyContinue
        if ($k) {
            $r.key_existed = $true
            if ($k.GetValueNames() -contains $Name) {
                $r.existed = $true
                try { $r.kind = "$($k.GetValueKind($Name))" } catch { }
                if ($r.kind -ne 'Binary') { $r.value = $k.GetValue($Name) } else { $r.value = $null }
            }
        }
    } catch { }
    return $r
}

function Get-SvcBackup {
    param([string]$Name)
    $r = @{ exists = $false; start = $null; delayed_existed = $false; delayed = 0 }
    $p = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$Name" -ErrorAction SilentlyContinue
    if ($p) {
        $r.exists = $true
        if ($p.PSObject.Properties.Name -contains 'Start') { $r.start = [int]$p.Start }
        if ($p.PSObject.Properties.Name -contains 'DelayedAutostart') {
            $r.delayed_existed = $true; $r.delayed = [int]$p.DelayedAutostart
        }
    }
    return $r
}

function Get-TaskBackup {
    param([string]$FullPath)
    $r = @{ found = $false; state = '' }
    try {
        $t = & schtasks.exe /Query /TN $FullPath /FO LIST 2>&1
        if ($LASTEXITCODE -eq 0) {
            $r.found = $true
            $text = ($t | Out-String)
            if ($text -match 'Status:\s*(\S+)') { $r.state = $Matches[1] }
            elseif ($text -match '状态:\s*(\S+)') { $r.state = $Matches[1] }
            if (-not $r.state) { $r.state = 'Ready' }
            if ($text -match '已禁用|Disabled') { $r.state = 'Disabled' }
        }
    } catch { }
    return $r
}

function Get-UsbBackup {
    $devs = @()
    try {
        foreach ($d in (Get-CimInstance -Namespace root\wmi -ClassName MSPower_DeviceEnable -ErrorAction SilentlyContinue |
                        Where-Object { "$($_.InstanceName)" -like 'USB\VID*' })) {
            $devs += @{ inst = "$($d.InstanceName)"; enable = [bool]$d.Enable }
        }
    } catch { }
    return $devs
}

function Get-ActivePlanGuid {
    try {
        $t = (& powercfg.exe /getactivescheme 2>&1 | Out-String)
        if ($t -match '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})') { return $Matches[1] }
    } catch { }
    return ''
}

# ---------- 状态文件 ----------
function Get-StateFile {
    param([string]$Id)
    return (Join-Path (Get-StateDir) "$Id.json")
}

function Test-HasState {
    param([string]$Id)
    return (Test-Path -LiteralPath (Get-StateFile $Id))
}

# ---------- live 已应用检测（reg/svc 步骤全中即视为已应用；gpu/usb/plan 等以状态文件为准） ----------
function Test-LiveApplied {
    param([Parameter(Mandatory)]$Tweak)
    $steps = Expand-TweakSteps -Tweak $Tweak
    if (-not $steps) { return $false }
    $checkable = 0
    foreach ($s in @($steps)) {
        if ($s.t -eq 'reg') {
            $checkable++
            $b = Get-RegBackup -Key $s.k -Name $s.n
            if (-not $b.existed) { return $false }
            $cur = $b.value
            if ("$cur" -ne "$($s.v)") { return $false }
        } elseif ($s.t -eq 'svc') {
            $checkable++
            $b = Get-SvcBackup -Name $s.n
            if (-not $b.exists) { return $false }
            $wantStart = @{ 'auto' = 2; 'auto-delayed' = 2; 'manual' = 3; 'disabled' = 4 }["$($s.v)"]
            if ($b.start -ne $wantStart) { return $false }
            if ($s.v -eq 'auto-delayed' -and [int]$b.delayed -ne 1) { return $false }
        } elseif ($s.t -eq 'regdel') {
            $checkable++
            $b = Get-RegBackup -Key $s.k -Name $s.n
            if ($b.existed) { return $false }
        }
    }
    return ($checkable -gt 0)
}

# ---------- 适用性判定 ----------
function Get-Applicability {
    param([Parameter(Mandatory)]$Tweak, [int]$Build, [array]$Adapters, [bool]$Admin)
    if ($Tweak.os -eq 'win10' -and $Build -ge 22000) { return @{ ok = $false; reason = '仅 Windows 10 适用（当前为 Win11）' } }
    if ($Tweak.os -eq 'win11' -and $Build -lt 22000) { return @{ ok = $false; reason = '仅 Windows 11 适用（当前为 Win10/更旧）' } }
    if ($Build -eq 0) { return @{ ok = $false; reason = '无法读取系统版本号' } }
    if ($Tweak.vendor) {
        $hit = @($Adapters | Where-Object { $_.vendor -eq $Tweak.vendor })
        if ($hit.Count -eq 0) { return @{ ok = $false; reason = "未检测到 $($Tweak.vendor) 显卡" } }
    }
    if ($Tweak.id -eq 'perf-svchost' -and (Get-RamKB) -le 0) { return @{ ok = $false; reason = '无法读取物理内存大小' } }
    return @{ ok = $true; reason = '' }
}

# ---------- apply ----------
if ($Action -eq 'apply') {
    if (-not $Ids) { Write-Result -Status error -Error 'apply 需要 -Ids id1,id2（先跑 -Action list 看目录）' }
    $catalog = Get-TweakCatalog
    $idList = @($Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $targets = @($catalog | Where-Object { $idList -contains $_.id })
    $unknown = @($idList | Where-Object { $targets.id -notcontains $_ })
    if ($unknown.Count -gt 0) {
        Write-Result -Status error -Error "未知 id：$($unknown -join ', ')（只接受内置目录 id，见 -Action list）"
    }

    $build = Get-OSBuild; $adapters = Get-GpuAdapters; $admin = Test-TweakAdmin
    $skipped = [System.Collections.Generic.List[object]]::new()
    $ready = [System.Collections.Generic.List[object]]::new()
    foreach ($t in $targets) {
        if (Test-HasState -Id $t.id) {
            $skipped.Add([PSCustomObject]@{ id = $t.id; reason = '已有应用记录（先 revert 才能重新应用）' }); continue
        }
        $app = Get-Applicability -Tweak $t -Build $build -Adapters $adapters -Admin $admin
        if (-not $app.ok) { $skipped.Add([PSCustomObject]@{ id = $t.id; reason = $app.reason }); continue }
        $steps = Expand-TweakSteps -Tweak $t
        if (-not $steps) { $skipped.Add([PSCustomObject]@{ id = $t.id; reason = '无可执行步骤（如未检测到匹配显卡）' }); continue }
        $needAdmin = @($steps | Where-Object { Step-NeedAdmin $_ }).Count -gt 0
        if ($needAdmin -and -not $admin) {
            $skipped.Add([PSCustomObject]@{ id = $t.id; reason = '需要管理员权限（以管理员身份重开终端后重试）' }); continue
        }
        if ($t.risk -eq 'danger' -and -not $Force) {
            Write-Result -Status error -Error "id=$($t.id) 为 danger 级，必须显式加 -Force 才能应用"
        }
        $ready.Add(@{ tweak = $t; steps = $steps })
    }

    # ---- 备份阶段：所有目标先完整采集旧状态，任一失败则该项中止，绝不半备份半写入 ----
    $plans = [System.Collections.Generic.List[object]]::new()
    foreach ($r in $ready) {
        $t = $r.tweak; $backup = @(); $ok = $true
        try {
            foreach ($s in @($r.steps)) {
                if ($s.t -in @('reg', 'regdel')) {
                    $b = Get-RegBackup -Key $s.k -Name $s.n
                    $backup += @{ t = $s.t; k = $s.k; n = $s.n; existed = $b.existed; kind = $b.kind; value = $b.value; key_existed = $b.key_existed }
                } elseif ($s.t -eq 'svc') {
                    $b = Get-SvcBackup -Name $s.n
                    $backup += @{ t = 'svc'; n = $s.n; exists = $b.exists; start = $b.start; delayed_existed = $b.delayed_existed; delayed = $b.delayed }
                } elseif ($s.t -eq 'task') {
                    $b = Get-TaskBackup -FullPath $s.p
                    $backup += @{ t = 'task'; p = $s.p; found = $b.found; state = $b.state }
                } elseif ($s.t -eq 'hiber') {
                    $present = (Test-Path -LiteralPath "$env:SystemDrive\hiberfil.sys" -ErrorAction SilentlyContinue)
                    $backup += @{ t = 'hiber'; present = [bool]$present }
                } elseif ($s.t -eq 'usb') {
                    $backup += @{ t = 'usb'; devs = @(Get-UsbBackup) }
                } elseif ($s.t -eq 'plan') {
                    $active = Get-ActivePlanGuid
                    $backup += @{ t = 'plan'; template = $s.template; old_guid = $active }
                }
            }
        } catch {
            $skipped.Add([PSCustomObject]@{ id = $t.id; reason = "备份失败，已中止该项（未写入任何更改）：$($_.Exception.Message)" })
            $ok = $false
        }
        if ($ok) { $plans.Add(@{ tweak = $t; steps = $r.steps; backup = $backup }) }
    }

    # ---- 写入阶段 ----
    $applied = [System.Collections.Generic.List[object]]::new()
    $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($p in $plans) {
        $t = $p.tweak; $stepsOk = 0; $stepsSkip = 0; $errs = @()
        foreach ($b in @($p.backup)) {
            try {
                if ($b.t -eq 'reg') {
                    $cur = Get-RegBackup -Key $b.k -Name $b.n
                    $target = $p.steps | Where-Object { $_.t -eq 'reg' -and $_.k -eq $b.k -and $_.n -eq $b.n } | Select-Object -First 1
                    if ($cur.existed -and "$($cur.value)" -eq "$($target.v)") { $stepsSkip++; continue }
                    if (-not (Test-Path -LiteralPath $b.k)) { New-Item -Path $b.k -Force -ErrorAction Stop | Out-Null }
                    if ($cur.existed) {
                        Set-ItemProperty -LiteralPath $b.k -Name $b.n -Value $target.v -Type $target.ty -Force -ErrorAction Stop
                    } else {
                        New-ItemProperty -LiteralPath $b.k -Name $b.n -Value $target.v -PropertyType $target.ty -Force -ErrorAction Stop | Out-Null
                    }
                    # 读回校验
                    $chk = Get-RegBackup -Key $b.k -Name $b.n
                    if (-not $chk.existed -or "$($chk.value)" -ne "$($target.v)") { throw "写入后读回不一致：$($b.k)\$($b.n)" }
                    $stepsOk++
                } elseif ($b.t -eq 'regdel') {
                    if ($b.existed) {
                        Remove-ItemProperty -LiteralPath $b.k -Name $b.n -Force -ErrorAction Stop
                        $stepsOk++
                    } else { $stepsSkip++ }
                } elseif ($b.t -eq 'svc') {
                    if (-not $b.exists) { $stepsSkip++; continue }
                    $svcStep = $p.steps | Where-Object { $_.t -eq 'svc' -and $_.n -eq $b.n } | Select-Object -First 1
                    $want = @{ 'auto' = @(2, 0); 'auto-delayed' = @(2, 1); 'manual' = @(3, 0); 'disabled' = @(4, 0) }["$($svcStep.v)"]
                    if (-not $want) { $want = @(4, 0) }
                    if ($b.start -eq $want[0] -and [int]$b.delayed -eq $want[1]) { $stepsSkip++; continue }
                    $svcKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$($b.n)"
                    Set-ItemProperty -LiteralPath $svcKey -Name 'Start' -Value $want[0] -Type DWord -Force -ErrorAction Stop
                    if ($b.delayed_existed -or $want[1] -eq 1) {
                        Set-ItemProperty -LiteralPath $svcKey -Name 'DelayedAutostart' -Value $want[1] -Type DWord -Force -ErrorAction Stop
                    }
                    $stepsOk++
                } elseif ($b.t -eq 'task') {
                    if (-not $b.found) { $stepsSkip++; continue }
                    if ($b.state -eq 'Disabled') { $stepsSkip++; continue }
                    $null = & schtasks.exe /Change /TN $b.p /DISABLE 2>&1
                    if ($LASTEXITCODE -ne 0) { throw "schtasks 禁用失败（exit=$LASTEXITCODE）：$($b.p)" }
                    $stepsOk++
                } elseif ($b.t -eq 'hiber') {
                    if (-not $b.present) { $stepsSkip++; continue }
                    $null = & powercfg.exe /h off 2>&1
                    if ($LASTEXITCODE -ne 0) { throw 'powercfg /h off 失败' }
                    $stepsOk++
                } elseif ($b.t -eq 'usb') {
                    if (@($b.devs).Count -eq 0) { $stepsSkip++; continue }
                    foreach ($d in @($b.devs)) {
                        try {
                            $ci = Get-CimInstance -Namespace root\wmi -ClassName MSPower_DeviceEnable -ErrorAction Stop |
                                Where-Object { "$($_.InstanceName)" -eq $d.inst } | Select-Object -First 1
                            if ($ci) { Set-CimInstance -CimInstance $ci -Property @{ Enable = $false } -ErrorAction Stop }
                        } catch { $errs += "USB $($d.inst) 设置失败：$($_.Exception.Message)" }
                    }
                    $stepsOk++
                } elseif ($b.t -eq 'plan') {
                    $dup = (& powercfg.exe /duplicatescheme $b.template 2>&1 | Out-String)
                    $m = [regex]::Match($dup, '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')
                    if (-not $m.Success) { throw "duplicatescheme 失败：$($dup.Trim())" }
                    $newGuid = $m.Groups[1].Value
                    $null = & powercfg.exe /setactive $newGuid 2>&1
                    if ($LASTEXITCODE -ne 0) { throw "setactive 失败：$newGuid" }
                    $b['new_guid'] = $newGuid
                    $stepsOk++
                }
            } catch { $errs += "$($b.t) 步骤失败：$($_.Exception.Message)" }
        }

        # ---- 落回滚数据（有任一成功步骤才落盘） ----
        if ($stepsOk -gt 0) {
            $file = Get-StateFile -Id $t.id
            @{ id = $t.id; name = $t.name; risk = $t.risk; applied_at = (Get-Date).ToString('o'); steps = @($p.backup) } |
                ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $file -Encoding UTF8
        }
        foreach ($e in $errs) { $errors.Add("$($t.id): $e") }
        $applied.Add([PSCustomObject]@{
            id = $t.id; steps_ok = $stepsOk; steps_skipped = $stepsSkip; steps_failed = $errs.Count
            state_file = $(if ($stepsOk -gt 0) { Get-StateFile -Id $t.id } else { '' })
        })
        if ($stepsOk -gt 0) {
            Write-AuditLog -Action 'tweaks-apply' -Items @($t.id) -Extra @{ name = $t.name; steps_ok = $stepsOk }
        }
    }

    Write-Result -Status ok -Data ([ordered]@{
        applied = $applied; skipped = $skipped; errors = $errors
        note = '部分项需重启/重登录生效；建议先创建系统还原点（restore.ps1 -Action create）'
    })
}

# ---------- revert ----------
if ($Action -eq 'revert') {
    if (-not $Ids) { Write-Result -Status error -Error 'revert 需要 -Ids id1,id2' }
    $idList = @($Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $restored = [System.Collections.Generic.List[object]]::new()
    $errors = [System.Collections.Generic.List[string]]::new()
    $notFound = @()
    foreach ($id in $idList) {
        $file = Get-StateFile -Id $id
        if (-not (Test-Path -LiteralPath $file)) { $notFound += $id; continue }
        try {
            $state = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            $errors.Add("$id`: 回滚数据损坏：$($_.Exception.Message)"); continue
        }
        $okSteps = 0; $errs = @()
        foreach ($it in @($state.steps)) {
            try {
                if ($it.t -in @('reg', 'regdel')) {
                    $wasBool = $false
                    if ($it.PSObject.Properties['existed']) { $wasBool = [bool]$it.existed }
                    if ($wasBool) {
                        $kind = if ($it.PSObject.Properties['kind'] -and "$($it.kind)") { "$($it.kind)" } else { 'DWord' }
                        if ($kind -eq 'Binary') { throw 'Binary 值无法安全恢复，跳过（原值未知）' }
                        if (-not (Test-Path -LiteralPath $it.k)) { New-Item -Path $it.k -Force -ErrorAction Stop | Out-Null }
                        $val = if ($it.PSObject.Properties['value']) { $it.value } else { $null }
                        if ($null -eq $val) { $val = 0 }
                        Set-ItemProperty -LiteralPath $it.k -Name $it.n -Value $val -Type $kind -Force -ErrorAction Stop
                    } else {
                        $cur = Get-RegBackup -Key $it.k -Name $it.n
                        if ($cur.existed) {
                            Remove-ItemProperty -LiteralPath $it.k -Name $it.n -Force -ErrorAction SilentlyContinue
                        }
                        # 键是 apply 时新建的且已无任何值/子键 → 一并删除（不留空壳键）
                        $keyWas = $true
                        if ($it.PSObject.Properties['key_existed']) { $keyWas = [bool]$it.key_existed }
                        if (-not $keyWas) {
                            $k2 = Get-Item -LiteralPath $it.k -ErrorAction SilentlyContinue
                            if ($k2 -and @($k2.GetValueNames()).Count -eq 0 -and @($k2.GetSubKeyNames()).Count -eq 0) {
                                Remove-Item -LiteralPath $it.k -Force -ErrorAction SilentlyContinue
                            }
                        }
                    }
                    $okSteps++
                } elseif ($it.t -eq 'svc') {
                    if ([bool]$it.exists) {
                        $svcKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$($it.n)"
                        if ($it.PSObject.Properties['start'] -and $null -ne $it.start) {
                            Set-ItemProperty -LiteralPath $svcKey -Name 'Start' -Value ([int]$it.start) -Type DWord -Force -ErrorAction Stop
                        }
                        if ($it.PSObject.Properties['delayed_existed'] -and [bool]$it.delayed_existed) {
                            Set-ItemProperty -LiteralPath $svcKey -Name 'DelayedAutostart' -Value ([int]$it.delayed) -Type DWord -Force -ErrorAction Stop
                        }
                        $okSteps++
                    }
                } elseif ($it.t -eq 'task') {
                    if ([bool]$it.found -and "$($it.state)" -ne 'Disabled') {
                        $null = & schtasks.exe /Change /TN "$($it.p)" /ENABLE 2>&1
                        if ($LASTEXITCODE -ne 0) { throw "schtasks 启用失败：$($it.p)" }
                        $okSteps++
                    }
                } elseif ($it.t -eq 'hiber') {
                    $was = $null
                    if ($it.PSObject.Properties['present']) { $was = [bool]$it.present }
                    if ($null -ne $it.PSObject.Properties['present'] -and $was) {
                        $null = & powercfg.exe /h on 2>&1
                        if ($LASTEXITCODE -ne 0) { throw 'powercfg /h on 失败' }
                        $okSteps++
                    } elseif ($null -ne $it.PSObject.Properties['present']) { $okSteps++ }   # 本来就没开，无需恢复
                    else { $errs += '休眠原状态未知，跳过恢复（如实不确定）' }
                } elseif ($it.t -eq 'usb') {
                    foreach ($d in @($it.devs)) {
                        try {
                            $ci = Get-CimInstance -Namespace root\wmi -ClassName MSPower_DeviceEnable -ErrorAction Stop |
                                Where-Object { "$($_.InstanceName)" -eq "$($d.inst)" } | Select-Object -First 1
                            if ($ci) { Set-CimInstance -CimInstance $ci -Property @{ Enable = ([bool]$d.enable) } -ErrorAction Stop }
                        } catch { $errs += "USB $($d.inst) 恢复失败：$($_.Exception.Message)" }
                    }
                    $okSteps++
                } elseif ($it.t -eq 'plan') {
                    $newG = "$($it.new_guid)"
                    if ($newG) {
                        $oldG = ''
                        if ($it.PSObject.Properties['old_guid']) { $oldG = "$($it.old_guid)" }
                        if ($oldG -and $oldG -ne $newG) {
                            $null = & powercfg.exe /setactive $oldG 2>&1
                            if ($LASTEXITCODE -ne 0) { $errs += "恢复原电源计划失败：$oldG" }
                        }
                        $null = & powercfg.exe /delete $newG 2>&1
                    }
                    $okSteps++
                }
            } catch { $errs += "$($it.t) 步骤恢复失败：$($_.Exception.Message)" }
        }
        if ($errs.Count -eq 0) {
            Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
            Write-AuditLog -Action 'tweaks-revert' -Items @($id) -Extra @{ name = "$($state.name)" }
            $restored.Add([PSCustomObject]@{ id = $id; name = "$($state.name)"; steps_restored = $okSteps })
        } else {
            foreach ($e in $errs) { $errors.Add("$id`: $e") }
            $restored.Add([PSCustomObject]@{ id = $id; name = "$($state.name)"; steps_restored = $okSteps; partial = $true })
        }
    }
    if ($notFound.Count -gt 0) {
        $errors.Add("以下 id 没有应用记录（未应用过或已恢复）：$($notFound -join ', ')")
    }
    Write-Result -Status ok -Data ([ordered]@{ restored = $restored; errors = $errors })
}

# ---------- list ----------
if ($Action -eq 'list') {
    $catalog = Get-TweakCatalog
    $build = Get-OSBuild; $adapters = Get-GpuAdapters; $admin = Test-TweakAdmin
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($t in $catalog) {
        $app = Get-Applicability -Tweak $t -Build $build -Adapters $adapters -Admin $admin
        $steps = Expand-TweakSteps -Tweak $t
        $needAdmin = @($steps | Where-Object { Step-NeedAdmin $_ }).Count -gt 0
        $live = $false
        if ($app.ok -and -not (Test-HasState -Id $t.id)) { $live = Test-LiveApplied -Tweak $t }
        $out.Add([PSCustomObject]@{
            id = $t.id; category = $t.cat; name = $t.name; risk = $t.risk; desc = $t.desc
            os = $t.os; vendor = $t.vendor
            applicable = $app.ok; not_applicable_reason = $app.reason
            need_admin = $needAdmin; has_state = (Test-HasState -Id $t.id); applied = ($live -or (Test-HasState -Id $t.id))
        })
    }
    Write-Result -Status ok -Data ([ordered]@{
        admin = $admin; os_build = $build; gpus = @($adapters)
        count = $out.Count
        by_category = @{
            性能 = @($out | Where-Object category -eq '性能').Count
            隐私 = @($out | Where-Object category -eq '隐私').Count
            显卡 = @($out | Where-Object category -eq '显卡').Count
            电源 = @($out | Where-Object category -eq '电源').Count
            体验 = @($out | Where-Object category -eq '体验').Count
            AI   = @($out | Where-Object category -eq 'AI').Count
            预装 = @($out | Where-Object category -eq '预装').Count
        }
        tweaks = $out
    })
}

# ---------- status ----------
if ($Action -eq 'status') {
    $items = @(Get-ChildItem -LiteralPath (Get-StateDir) -Filter *.json -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $j = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            [PSCustomObject]@{ id = $j.id; name = $j.name; risk = $j.risk; applied_at = $j.applied_at; file = $_.FullName }
        } catch { }
    })
    Write-Result -Status ok -Data ([ordered]@{ dir = (Get-StateDir); count = $items.Count; items = $items })
}
