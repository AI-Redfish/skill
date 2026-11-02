<#
schedule.ps1 — 定时自动清理（Windows 计划任务 + 本工具 junk 规则）

复刻 grclean schedule.ts 思路（原版调自身 exe 静默模式；本版用 schtasks 定时
以无窗口方式运行 junk.ps1 的 -Recommended 清理，等价实现「定时隐私清理」）。
  配置存 %LOCALAPPDATA%\pc-manager\schedules\*.json；系统任务名 PcManagerClean_<id>
  任务到点执行：powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass
                -File <本脚本目录>\junk.ps1 -Action delete -Recommended
  （默认只清 safe 级推荐项且移入回收站；受保护路径照常拦截）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File schedule.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File schedule.ps1 -Action add -Name 每日清理 -Time 09:00 [-Weekly]
  powershell -NoProfile -ExecutionPolicy Bypass -File schedule.ps1 -Action remove -Name 每日清理
  powershell -NoProfile -ExecutionPolicy Bypass -File schedule.ps1 -Action run-now -Name 每日清理

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'list',
    [string]$Name = '',
    [string]$Time = '09:00',
    [switch]$Weekly
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

function Get-SchedulesDir {
    $dir = Join-Path (Get-PcManagerDir) 'schedules'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function Get-ScheduleTaskName { param([string]$N) return 'PcManagerClean_' + ($N -replace '[^A-Za-z0-9_-]', '_') }

function Get-ScheduleId { param([string]$N) return ($N -replace '[^A-Za-z0-9_-]', '_') }

if ($Action -eq 'list') {
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($f in (Get-ChildItem -LiteralPath (Get-SchedulesDir) -Filter *.json -ErrorAction SilentlyContinue)) {
        try {
            $c = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $exists = [bool](schtasks /query /tn (Get-ScheduleTaskName $c.name) 2>$null)
            $out.Add([PSCustomObject]@{
                name = $c.name; frequency = $c.frequency; time = $c.time
                enabled = $c.enabled; system_task_exists = $exists
            })
        } catch { }
    }
    Write-Result -Status ok -Data @{ schedules = $out }
}

if ($Action -eq 'add') {
    if (-not $Name.Trim()) { Write-Result -Status error -Error '计划名称不能为空' }
    if ($Time -notmatch '^([01]\d|2[0-3]):[0-5]\d$') { Write-Result -Status error -Error '时间格式应为 HH:MM（24小时制）' }

    $junkScript = Join-Path $PSScriptRoot 'junk.ps1'
    $tr = "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$junkScript`" -Action delete -Recommended"
    $taskName = Get-ScheduleTaskName $Name
    $args = @('/create', '/tn', $taskName, '/tr', $tr, '/f')
    if ($Weekly) { $args += @('/sc', 'weekly', '/d', 'MON', '/st', $Time) }
    else { $args += @('/sc', 'daily', '/st', $Time) }

    $out = schtasks @args 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Result -Status error -Error "创建系统计划任务失败（可能需要权限）：$($out.Trim())"
    }
    $cfg = [PSCustomObject]@{ name = $Name.Trim(); frequency = $(if ($Weekly) { 'weekly' } else { 'daily' }); time = $Time; enabled = $true; created_at = (Get-Date).ToString('o') }
    $file = Join-Path (Get-SchedulesDir) "$(Get-ScheduleId $Name).json"
    $cfg | ConvertTo-Json | Set-Content -LiteralPath $file -Encoding UTF8
    Write-AuditLog -Action 'schedule' -Items @($taskName) -Extra @{ op = 'add'; at = $Time }
    Write-Result -Status ok -Data @{ created = $true; name = $Name; task = $taskName; time = $Time
        note = '到点自动执行 junk.ps1 -Recommended：仅清 safe 级推荐项且移入回收站' }
}

if ($Action -eq 'remove') {
    if (-not $Name) { Write-Result -Status error -Error '需要 -Name' }
    $file = Join-Path (Get-SchedulesDir) "$(Get-ScheduleId $Name).json"
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    schtasks /delete /tn (Get-ScheduleTaskName $Name) /f 2>&1 | Out-Null   # 任务可能本就不存在
    Write-AuditLog -Action 'schedule' -Items @((Get-ScheduleTaskName $Name)) -Extra @{ op = 'remove' }
    Write-Result -Status ok -Data @{ removed = $true; name = $Name }
}

if ($Action -eq 'run-now') {
    if (-not $Name) { Write-Result -Status error -Error '需要 -Name' }
    try {
        schtasks /run /tn (Get-ScheduleTaskName $Name) 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "schtasks /run 退出码 $LASTEXITCODE" }
        Write-Result -Status ok -Data @{ triggered = $true; note = '已触发（后台执行，稍后可见效果）' }
    } catch {
        Write-Result -Status error -Error "触发失败：$($_.Exception.Message)"
    }
}
