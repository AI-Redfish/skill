<#
optimize.ps1 — 系统优化（检测为主，变更需显式动作；绝不自动改系统设置）

复刻 grclean optimize.ts。
  status   采集磁盘四项状态：SSD Trim / 碎片整理(仅HDD) / 存储感知 / CompactOS
  services 列出可延迟启动的第三方服务（系统服务白名单排除）
  vhd      检测 WSL / Docker 虚拟磁盘占用（只检测给建议，不自动迁移）
  变更动作：trim / defrag / storagesense-run / compactos（部分需管理员）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File optimize.ps1 -Action status -Drive C
  powershell -NoProfile -ExecutionPolicy Bypass -File optimize.ps1 -Action trim -Enabled:$false
  powershell -NoProfile -ExecutionPolicy Bypass -File optimize.ps1 -Action defrag -Drive C [-Analyze]
  powershell -NoProfile -ExecutionPolicy Bypass -File optimize.ps1 -Action storagesense-run
  powershell -NoProfile -ExecutionPolicy Bypass -File optimize.ps1 -Action compactos -Enabled:$true
  powershell -NoProfile -ExecutionPolicy Bypass -File optimize.ps1 -Action service-delay -Name Xxx [-Enabled:$false]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'status',
    [string]$Drive = 'C',
    [switch]$Enabled,
    [switch]$Analyze,
    [string]$Name = ''
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

# 系统关键服务白名单（复刻 optimize.ts $deny；这些绝不建议延迟）
$DenyServices = @('LSM','DPS','EventLog','EventSystem','Power','PlugPlay','ProfSvc','Schedule','SENS',
    'Winmgmt','RpcSs','RpcEptMapper','DcomLaunch','BFE','mpssvc','WinDefend','WdNisSvc',
    'SecurityHealthService','sppsvc','TrustedInstaller','wuauserv','BITS','CryptSvc','LanmanServer',
    'LanmanWorkstation','Themes','AudioSrv','Audiosrv','FontCache','gpsvc','iphlpsvc','Dhcp','Dnscache',
    'NlaSvc','nsi','netprofm','WlanSvc','Wcmsvc','UserManager','ShellHWDetection','SysMain','WSearch',
    'UsoSvc','BrokerInfrastructure','SystemEventsBroker','SgrmBroker','CoreMessagingRegistrar',
    'PimIndexMaintenanceSvc','OneSyncSvc','CDPSvc','WpnService','WpnUserService','tiledatamodelsvc',
    'DiagTrack','DusmSvc','DoSvc','AppXSvc','ClipSvc','cbdhsvc','GraphicsPerfSvc','TimeBrokerSvc',
    'TokenBroker','DeviceAssociationService','DevicesFlowUserSvc','PcaSvc','Spooler','RasMan',
    'NcbService','NcdAutoSetup','WFDSConMgrSvc','FrameServer','ClickToRunSvc','OfficeSvc')

function Get-DriveMedia {
    param([string]$Letter)
    $L = $Letter.Replace(':', '').ToUpper()
    $vol = Get-Volume -DriveLetter $L -ErrorAction SilentlyContinue
    if (-not $vol) { return $null }
    $part = $vol | Get-Partition -ErrorAction SilentlyContinue | Select-Object -First 1
    $disk = $part | Get-Disk -ErrorAction SilentlyContinue
    return @{ vol = $vol; disk = $disk; media = if ($disk) { "$($disk.MediaType)" } else { 'Unknown' } }
}

if ($Action -eq 'status') {
    $info = Get-DriveMedia -Letter $Drive
    $media = if ($info) { $info.media } else { 'Unknown' }
    $isSSD = ($media.ToUpper() -eq 'SSD'); $isHDD = ($media.ToUpper() -eq 'HDD')

    # Trim（fsutil；0=启用）
    $trim = $null
    try {
        $t = ((fsutil behavior query DisableDeleteNotify) -replace '[^0-9]', '')
        if ($t) { $trim = ($t -eq '0') }
    } catch { }

    # 存储感知（注册表 01 值）
    $ss = $null
    try {
        $k = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StorageSense'
        $p = Get-ItemProperty -Path $k -ErrorAction SilentlyContinue
        if ($p -and ($p.PSObject.Properties.Name -contains '01')) { $ss = ([int]$p.'01' -eq 1) }
    } catch { }

    # CompactOS
    $compact = $null
    try {
        $c = (compact.exe /CompactOS:query) -join ' '
        if ($c -match 'not in the compact|未处于压缩|未压缩') { $compact = $false }
        elseif ($c -match 'in the compact|处于压缩') { $compact = $true }
    } catch { }

    $opts = [System.Collections.Generic.List[object]]::new()
    if (-not $isSSD) {
        $opts.Add([PSCustomObject]@{ id='trim'; status='unknown'; value="当前盘为 $media，Trim 不适用" })
    } elseif ($trim -eq $true) {
        $opts.Add([PSCustomObject]@{ id='trim'; status='good'; value='已启用（DisableDeleteNotify=0）' })
    } elseif ($trim -eq $false) {
        $opts.Add([PSCustomObject]@{ id='trim'; status='warn'; value='未启用（DisableDeleteNotify=1）'; advice='建议开启（trim -Enabled），瞬时生效'; need_admin=$true })
    } else {
        $opts.Add([PSCustomObject]@{ id='trim'; status='unknown'; value='采集失败（可能无权限）' })
    }
    $opts.Add([PSCustomObject]@{
        id='defrag'
        status = $(if ($isHDD) { 'warn' } else { 'good' })
        value  = $(if ($isHDD) { 'HDD，可分析整理（碎片率>10%再整理）' } else { "$media 不建议整理" })
    })
    if ($ss -eq $true) { $opts.Add([PSCustomObject]@{ id='storagesense'; status='good'; value='已开启' }) }
    elseif ($ss -eq $false) { $opts.Add([PSCustomObject]@{ id='storagesense'; status='warn'; value='未开启'; advice='建议开启，让系统自动维护（storagesense-run 可立即跑一次）' }) }
    else { $opts.Add([PSCustomObject]@{ id='storagesense'; status='unknown'; value='状态未知（版本差异）' }) }
    if ($compact -eq $true) { $opts.Add([PSCustomObject]@{ id='compactos'; status='good'; value='已压缩' }) }
    elseif ($compact -eq $false) { $opts.Add([PSCustomObject]@{ id='compactos'; status='warn'; value='未压缩（可省 1-2GB）'; advice='磁盘紧张时可开启（compactos -Enabled），耗时较长'; need_admin=$true }) }
    else { $opts.Add([PSCustomObject]@{ id='compactos'; status='unknown'; value='采集失败' }) }

    Write-Result -Status ok -Data @{ drive = $Drive; media = $media; options = $opts }
}

if ($Action -eq 'trim') {
    $v = '1'; if ($Enabled) { $v = '0' }
    try {
        $out = fsutil behavior set DisableDeleteNotify $v
        $note = '已关闭 Trim'
        if ($Enabled) { $note = '已开启 Trim' }
        Write-Result -Status ok -Data @{ done = $true; output = "$out"; note = $note }
    } catch { Write-Result -Status error -Error "执行失败（可能需管理员）：$($_.Exception.Message)" }
}

if ($Action -eq 'defrag') {
    $L = $Drive.Replace(':', '').ToUpper()
    $arg = '/A'; if (-not $Analyze) { $arg = '/U /V' }
    try {
        $out = defrag "$L`:" $arg 2>&1 | Out-String
        Write-Result -Status ok -Data @{ done = $true; output = $out }
    } catch { Write-Result -Status error -Error "执行失败（整理需管理员且较慢）：$($_.Exception.Message)" }
}

if ($Action -eq 'storagesense-run') {
    try {
        Start-ScheduledTask -TaskPath '\Microsoft\Windows\DiskFootprint\' -TaskName 'StorageSense' -ErrorAction Stop
        Write-Result -Status ok -Data @{ done = $true; note = '已触发存储感知任务（后台执行）' }
    } catch { Write-Result -Status error -Error "触发失败：$($_.Exception.Message)" }
}

if ($Action -eq 'compactos') {
    $arg = ':never'; if ($Enabled) { $arg = ':always' }
    try {
        $out = compact.exe "/CompactOS$arg" 2>&1 | Out-String
        Write-Result -Status ok -Data @{ done = $true; output = $out }
    } catch { Write-Result -Status error -Error "执行失败（可能需管理员）：$($_.Exception.Message)" }
}

if ($Action -eq 'services') {
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($s in (Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object { $_.StartMode -eq 'Auto' })) {
        if ($DenyServices -contains $s.Name) { continue }
        $path = "$($s.PathName)"
        $third = $true
        if ($path -match '\\Windows\\' -or $path -match '\\WinSxS\\' -or -not $path) { $third = $false }
        $delayed = $false
        $rk = "HKLM:\SYSTEM\CurrentControlSet\Services\$($s.Name)"
        $p = Get-ItemProperty -Path $rk -ErrorAction SilentlyContinue
        if ($p -and ($p.PSObject.Properties.Name -contains 'DelayedAutostart')) { $delayed = ([int]$p.DelayedAutostart -eq 1) }
        $out.Add([PSCustomObject]@{
            name = $s.Name; display_name = "$($s.DisplayName)"
            delayed = $delayed; third_party = $third
            recommend_delay = ($third -and -not $delayed)
        })
    }
    $out = @($out | Sort-Object @{ E = { -$([int]$_.third_party) } }, delayed, name)
    Write-Result -Status ok -Data @{ count = $out.Count; services = $out }
}

if ($Action -eq 'service-delay') {
    if (-not $Name) { Write-Result -Status error -Error '需要 -Name <服务名>' }
    $safe = ($Name -replace '[^A-Za-z0-9_.-]', '')
    if ($safe -ne $Name -or -not $safe) { Write-Result -Status error -Error '服务名含非法字符' }
    if ($DenyServices -contains $safe) { Write-Result -Status error -Error "服务 $safe 在系统关键服务白名单内，拒绝操作" }
    $start = 'auto'; if ($Enabled) { $start = 'delayed-auto' }
    try {
        $out = sc.exe config $safe start= $start 2>&1 | Out-String
        Write-Result -Status ok -Data @{ done = $true; service = $safe; start = $start; output = $out }
    } catch { Write-Result -Status error -Error "执行失败（可能需管理员）：$($_.Exception.Message)" }
}

if ($Action -eq 'vhd') {
    $result = [System.Collections.Generic.List[object]]::new()
    # WSL：发行版 + ext4.vhdx 体积
    $wslBytes = [int64]0; $wslLoc = '未检测到 WSL 发行版'; $wslExist = $false
    try {
        $distros = @((wsl.exe -l -q 2>$null) | Where-Object { $_ -and $_.Trim() })
        if ($distros.Count -gt 0) {
            $wslExist = $true; $wslLoc = ($distros -join ', ')
            foreach ($vhd in (Get-ChildItem -Path "$env:LOCALAPPDATA\Packages" -Filter ext4.vhdx -Recurse -ErrorAction SilentlyContinue | Select-Object -First 10)) {
                $wslBytes += $vhd.Length
            }
        }
    } catch { }
    $result.Add([PSCustomObject]@{
        id = 'wsl'; title = 'WSL 虚拟磁盘'; location = $wslLoc; bytes = $wslBytes; exists = $wslExist
        advice = 'ext4.vhdx 默认在 C 盘且只增不减；可用 wsl --export/--import 迁移（不自动代劳）'
    })
    # Docker：settings.json DataFolder 或默认 ext4.vhdx
    $dBytes = [int64]0; $dLoc = '未检测到 Docker'; $dExist = $false
    try {
        $sf = Join-Path $env:APPDATA 'Docker\settings.json'
        if (Test-Path -LiteralPath $sf) {
            $j = Get-Content -LiteralPath $sf -Raw | ConvertFrom-Json
            $root = ''
            if ($j.PSObject.Properties.Name -contains 'DataFolder') { $root = "$($j.DataFolder)" }
            if ($root -and (Test-Path -LiteralPath $root)) {
                $dExist = $true; $dLoc = $root
                $sum = (Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
                if ($sum) { $dBytes = [int64]$sum }
            }
        }
        if (-not $dExist) {
            $dvhd = Join-Path $env:LOCALAPPDATA 'Docker\wsl\data\ext4.vhdx'
            if (Test-Path -LiteralPath $dvhd) { $dExist = $true; $dLoc = $dvhd; $dBytes = [int64](Get-Item -LiteralPath $dvhd).Length }
        }
    } catch { }
    $result.Add([PSCustomObject]@{
        id = 'docker'; title = 'Docker 数据目录'; location = $dLoc; bytes = $dBytes; exists = $dExist
        advice = 'Docker Desktop → Settings → Resources 修改 Disk image location，或改 daemon.json 的 data-root'
    })
    Write-Result -Status ok -Data @{ items = $result }
}
