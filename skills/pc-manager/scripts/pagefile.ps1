<#
pagefile.ps1 — 虚拟内存（页面文件）可视化与优化

复刻 grclean pagefile.ts。
  查看：系统托管/自定义、初始/最大、所在盘、物理内存、实际占用
  建议：≤8GB 取 1.5 倍 / 8–16GB 取 1.25 倍 / ≥16GB 取 1 倍；最大封顶 32GB
  设置：写 PagingFiles 注册表（MultiString）；只改页面文件本身，变更后需重启生效

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File pagefile.ps1 -Action info
  powershell -NoProfile -ExecutionPolicy Bypass -File pagefile.ps1 -Action targets
  powershell -NoProfile -ExecutionPolicy Bypass -File pagefile.ps1 -Action apply -Mode auto|custom|move [-DriveLetter D] [-InitialMb 8192] [-MaxMb 16384]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'info',
    [string]$Mode = '',
    [string]$DriveLetter = '',
    [int]$InitialMb = 0,
    [int]$MaxMb = 0
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

$MaxCapMb = 32768

function Get-Suggest { param([int]$RamMb)
    $gb = $RamMb / 1024
    $factor = 1.0; $reason = ''
    if ($gb -le 8) { $factor = 1.5; $reason = "物理内存 $([math]::Round($gb,1)) GB（≤8GB），建议取 1.5 倍" }
    elseif ($gb -lt 16) { $factor = 1.25; $reason = "物理内存 $([math]::Round($gb,1)) GB（8–16GB），建议取 1–1.5 倍，此处取 1.25 倍" }
    else { $factor = 1.0; $reason = "物理内存 $([math]::Round($gb,1)) GB（≥16GB），建议取 1 倍即可" }
    $initial = [math]::Max(1024, [int][math]::Round($RamMb * $factor / 256) * 256)
    $max = [math]::Min($MaxCapMb, [int][math]::Round($initial * 1.5 / 256) * 256)
    return @{ initial = $initial; max = $max; reason = "$reason；最大值封顶 $($MaxCapMb/1024) GB 避免浪费" }
}

if ($Action -eq 'info') {
    $mm = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
    $rawList = @()
    $p = Get-ItemProperty -Path $mm -Name PagingFiles -ErrorAction SilentlyContinue
    if ($p -and $p.PagingFiles) { $rawList = @($p.PagingFiles) }
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $auto = $false; $ramMb = 0
    if ($cs) {
        $auto = [bool]$cs.AutomaticManagedPagefile
        $ramMb = [int][math]::Round($cs.TotalPhysicalMemory / 1MB)
    }
    $usage = @{}
    foreach ($u in (Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue)) {
        if ($u.Name) { $usage["$($u.Name)".ToUpper()] = [int]$u.AllocatedBaseSize }
    }
    $files = [System.Collections.Generic.List[object]]::new()
    foreach ($line in $rawList) {
        $s = "$line"
        if (-not $s.Trim()) { continue }
        $parts = $s -split '\s+'
        $drv = ''
        if ($parts[0] -match '^([A-Za-z]):') { $drv = $Matches[1].ToUpper() }
        $init = 0; $maxv = 0
        if ($parts.Count -ge 3) { $init = [int]$parts[1]; $maxv = [int]$parts[2] }
        $used = 0
        foreach ($k in $usage.Keys) { if ($k.StartsWith("$drv`:")) { $used = $usage[$k] } }
        $files.Add([PSCustomObject]@{ drive = $drv; initial_mb = $init; max_mb = $maxv; used_mb = $used })
    }
    $sug = Get-Suggest -RamMb $ramMb
    Write-Result -Status ok -Data ([ordered]@{
        auto_managed = $auto; ram_mb = $ramMb; raw = ($rawList -join ' | ')
        files = $files
        suggest_initial_mb = $sug.initial; suggest_max_mb = $sug.max; suggest_reason = $sug.reason
    })
}

if ($Action -eq 'targets') {
    $sys = "$((Get-SystemDriveLetter)):"
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($v in (Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' })) {
        $l = "$($v.DriveLetter)"
        if ("$l`:" -eq $sys) { continue }
        if ("$($v.FileSystem)" -ne 'NTFS') { continue }
        $out.Add([PSCustomObject]@{ letter = $l.ToUpper(); free_bytes = [int64]$v.SizeRemaining; total_bytes = [int64]$v.Size })
    }
    Write-Result -Status ok -Data @{ targets = $out }
}

if ($Action -eq 'apply') {
    if ($Mode -notin @('auto', 'custom', 'move')) { Write-Result -Status error -Error 'Mode 必须为 auto | custom | move' }
    $L = $DriveLetter.Replace(':', '').ToUpper()
    if (($Mode -eq 'custom' -or $Mode -eq 'move') -and $L -notmatch '^[A-Z]$') {
        Write-Result -Status error -Error '目标盘符无效（custom/move 需单个字母）'
    }
    if ($Mode -eq 'custom') {
        if ($InitialMb -lt 16 -or $MaxMb -lt $InitialMb) {
            Write-Result -Status error -Error '自定义大小无效（初始需 ≥16MB，最大不小于初始）'
        }
    }
    $value = ''
    if ($Mode -eq 'auto') { $value = 'C:\pagefile.sys 0 0' }
    elseif ($Mode -eq 'custom') { $value = "$L`:\pagefile.sys $InitialMb $MaxMb" }
    else { $value = "$L`:\pagefile.sys 0 0" }
    try {
        $mm = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
        Set-ItemProperty -Path $mm -Name PagingFiles -Value @($value) -Type MultiString -Force -ErrorAction Stop
        $label = ''
        if ($Mode -eq 'auto') { $label = '已设为系统托管（系统盘）' }
        elseif ($Mode -eq 'custom') { $label = "已设为 $L`: 固定 $InitialMb-$MaxMb MB" }
        else { $label = "已迁移到 $L`: 并由系统托管" }
        Write-AuditLog -Action 'pagefile' -Items @($value)
        Write-Result -Status ok -Data @{ done = $true; value = $value; message = "$label。重启后生效，请保存工作后重启" }
    } catch {
        Write-Result -Status error -Error "写入失败（可能需要管理员）：$($_.Exception.Message)"
    }
}
