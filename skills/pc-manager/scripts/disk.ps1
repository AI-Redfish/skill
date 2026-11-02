<#
disk.ps1 — 磁盘信息 / SMART 健康 / 物理磁盘清单

复刻 grclean disk.ts。数据源：
  逻辑卷: Get-Volume → Get-Partition → Get-Disk（介质类型/型号/健康状态/文件系统）
  Trim: fsutil behavior query DisableDeleteNotify
  SMART: Get-Disk.HealthStatus（普通权限）+ Get-StorageReliabilityCounter（温度/通电/
         磨损，需管理员）+ root\wmi 故障预测（需管理员）
  物理盘: Get-PhysicalDisk 聚合各盘符/容量/总线/序列号
任一项失败降级 unknown，不影响其他项。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File disk.ps1 -Action list [-Drive C]
  powershell -NoProfile -ExecutionPolicy Bypass -File disk.ps1 -Action smart -DeviceId 0
  powershell -NoProfile -ExecutionPolicy Bypass -File disk.ps1 -Action physical

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'list',
    [string]$Drive = '',
    [int]$DeviceId = 0
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$sysLetter = Get-SystemDriveLetter

function Get-TrimState {
    try {
        $nums = @((fsutil behavior query DisableDeleteNotify) | ForEach-Object { ($_ -replace '[^0-9]', '') } | Where-Object { $_ })
        if ($nums.Count -gt 0) { return ($nums[-1] -eq '0') }
    } catch { }
    return $null
}

if ($Action -eq 'list') {
    $vols = [System.Collections.Generic.List[object]]::new()
    $trim = Get-TrimState
    foreach ($v in (Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter })) {
        $letter = "$($v.DriveLetter)".ToUpper()
        $part = $v | Get-Partition -ErrorAction SilentlyContinue | Select-Object -First 1
        $disk = $part | Get-Disk -ErrorAction SilentlyContinue
        $smart = $null
        if ($disk) { $smart = ("$($disk.HealthStatus)" -eq 'Healthy') }
        $type = 'Unknown'
        if ($disk) {
            $mt = "$($disk.MediaType)".ToUpper()
            if ($mt -eq 'SSD' -or $mt -eq 'HDD') { $type = $mt }
        }
        # 健康标签（对应 disk.ts healthyLabel）
        $healthy = '健康'
        if ($smart -eq $false) { $healthy = '危险' }
        elseif ($type -eq 'SSD' -and $trim -eq $false) { $healthy = '关注' }
        elseif ("$($v.FileSystem)" -and "$($v.FileSystem)" -ne 'NTFS') { $healthy = '关注' }
        elseif ($null -eq $smart -and $type -eq 'Unknown') { $healthy = '关注' }
        $vols.Add([PSCustomObject]@{
            letter = $letter; label = "$($v.FileSystemLabel)"; file_system = "$($v.FileSystem)"
            total_bytes = [int64]$v.Size; free_bytes = [int64]$v.SizeRemaining
            type = $type; model = "$($disk.Model)"
            smart_ok = $smart; trim_enabled = $trim; healthy = $healthy
            system = ($letter -eq $sysLetter)
        })
    }
    Write-Result -Status ok -Data @{ volumes = $vols }
}

if ($Action -eq 'smart') {
    $rows = [System.Collections.Generic.List[object]]::new()
    $admin = Test-Admin
    try { $pd = Get-PhysicalDisk -DeviceId $DeviceId -ErrorAction Stop } catch { $pd = $null }
    $disk = $pd | Get-Disk -ErrorAction SilentlyContinue | Select-Object -First 1

    $health = $null
    if ($disk) { $health = "$($disk.HealthStatus)" }
    $healthText = @{ healthy = '健康'; warning = '警告'; unhealthy = '危险'; degraded = '危险' }
    $hk = ''
    if ($health) { $hk = $health.Trim().ToLower() }
    $rows.Add([PSCustomObject]@{
        label = '磁盘健康'; value = $healthText[$hk]
        ok = $(if ($hk -eq 'healthy') { $true } elseif ($hk) { $false } else { $null })
    })

    $trim = Get-TrimState
    $rows.Add([PSCustomObject]@{
        label = 'Trim 状态'
        value = $(if ($null -eq $trim) { '未知' } elseif ($trim) { '已启用' } else { '未启用' })
        ok = $trim
    })

    # 可靠性计数器（温度开尔文→摄氏；磨损→剩余寿命；需管理员）
    $relOk = $true; $rel = $null
    try { if ($pd) { $rel = $pd | Get-StorageReliabilityCounter -ErrorAction Stop } } catch { $relOk = $false }
    $unavail = if ($admin) { '不支持' } else { '需管理员权限' }

    if ($relOk -and $null -ne $rel.Wear -and $rel.Wear -ge 0 -and $rel.Wear -le 100) {
        $life = [math]::Max(0, [math]::Min(100, [int](100 - $rel.Wear)))
        $rows.Add([PSCustomObject]@{ label='剩余寿命'; value="$life%"; ok=($life -ge 80) })
    } elseif ($relOk) { $rows.Add([PSCustomObject]@{ label='剩余寿命'; value='未知'; ok=$null }) }
    else { $rows.Add([PSCustomObject]@{ label='剩余寿命'; value=$unavail; ok=$null }) }

    # 故障预测（root\wmi；独立 try）
    $predOk = $true; $predict = $null
    try {
        $p = Get-CimInstance -Namespace root\wmi -ClassName MSStorageDriver_FailurePredictStatus -ErrorAction Stop | Select-Object -First 1
        if ($p) { $predict = [bool]$p.PredictFailure }
    } catch { $predOk = $false }
    if ($predOk -and $predict -eq $true) {
        $rows.Add([PSCustomObject]@{ label='重映射扇区'; value='存在故障预警'; ok=$false })
    } elseif ($predOk -and $predict -eq $false -and $null -ne $rel.ReadErrorsTotal) {
        $rows.Add([PSCustomObject]@{ label='重映射扇区'; value="0（读取错误 $($rel.ReadErrorsTotal)）"; ok=($rel.ReadErrorsTotal -eq 0) })
    } elseif ($predOk) { $rows.Add([PSCustomObject]@{ label='重映射扇区'; value='未知'; ok=$null }) }
    else { $rows.Add([PSCustomObject]@{ label='重映射扇区'; value=$(if ($admin) { '不支持' } else { '需管理员权限' }); ok=$null }) }

    if ($relOk -and $rel.Temperature -gt 0) {
        $c = [int][math]::Round($rel.Temperature - 273.15)
        $rows.Add([PSCustomObject]@{ label='温度'; value="${c}℃"; ok=($c -le 55) })
    } elseif ($relOk) { $rows.Add([PSCustomObject]@{ label='温度'; value='未知'; ok=$null }) }
    else { $rows.Add([PSCustomObject]@{ label='温度'; value=$unavail; ok=$null }) }

    if ($relOk -and $rel.PowerOnHours -gt 0) {
        $y = [math]::Round($rel.PowerOnHours / 8760, 1)
        $rows.Add([PSCustomObject]@{ label='通电时长'; value="$($rel.PowerOnHours) 小时（约 $y 年）"; ok=$null })
    } elseif ($relOk) { $rows.Add([PSCustomObject]@{ label='通电时长'; value='未知'; ok=$null }) }
    else { $rows.Add([PSCustomObject]@{ label='通电时长'; value=$unavail; ok=$null }) }

    Write-Result -Status ok -Data @{ device_id = $DeviceId; admin = $admin; rows = $rows }
}

if ($Action -eq 'physical') {
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($pd in (Get-PhysicalDisk -ErrorAction SilentlyContinue)) {
        $letters = @(); $total = [int64]0; $free = [int64]0; $health = $null
        foreach ($dk in ($pd | Get-Disk -ErrorAction SilentlyContinue)) {
            if ($null -eq $health) { $health = "$($dk.HealthStatus)" }
            foreach ($pt in ($dk | Get-Partition -ErrorAction SilentlyContinue)) {
                $vol = $pt | Get-Volume -ErrorAction SilentlyContinue
                if ($vol -and $vol.DriveLetter) {
                    $l = "$($vol.DriveLetter)"
                    if ($letters -notcontains $l) { $letters += $l }
                    $total += [int64]$vol.Size; $free += [int64]$vol.SizeRemaining
                }
            }
        }
        $mt = "$($pd.MediaType)".ToUpper()
        $type = 'Unknown'; if ($mt -eq 'SSD' -or $mt -eq 'HDD') { $type = $mt }
        $out.Add([PSCustomObject]@{
            device_id = [int]$pd.DeviceId
            model = $(if ($pd.FriendlyName) { "$($pd.FriendlyName)" } else { "$($pd.Model)" })
            type = $type; serial = "$($pd.SerialNumber)"; firmware = "$($pd.FirmwareVersion)"
            bus_type = "$($pd.BusType)"; size_bytes = [int64]$pd.Size
            letters = @($letters | Sort-Object); total_bytes = $total; free_bytes = $free
            health = $health; is_system = ($letters -contains $sysLetter)
        })
    }
    Write-Result -Status ok -Data @{ disks = $out }
}
