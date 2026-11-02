<#
installer.ps1 — 安装包清理（下载目录里的孤立安装包/压缩包）

复刻 grclean installer.ts。判定规则（避免误伤日常文档）：
  扩展名 ∈ exe/msi/iso/zip/rar/7z/cab/msix/appx 且
  （文件名含 setup/install/driver/安装包/驱动/绿色版/portable 特征，或体积 ≥10MB）
  系统盘扫用户下载类目录（深度3）；其他盘扫盘根（深度8）——安装包可能在任意位置。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File installer.ps1 -Action scan [-MinMb 0] [-MinDays 0] [-Drive ''|all|D]
  powershell -NoProfile -ExecutionPolicy Bypass -File installer.ps1 -Action delete -Session <会话> -Ids id1,id2 [-Purge]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete')][string]$Action = 'scan',
    [int]$MinMb = 0,
    [int]$MinDays = 0,
    [string]$Drive = '',
    [string]$Session = '',
    [string]$Ids = '',
    [switch]$Purge
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$Exts = @('.exe', '.msi', '.iso', '.zip', '.rar', '.7z', '.cab', '.msix', '.appx')
$NameHints = @('setup', 'install', 'uninstall', 'driver', '安装包', '驱动', '绿色版', 'portable')
$BigEnough = 10MB

function Test-InstallerLike {
    param([string]$Name, [long]$Size, [int]$MinMbParam)
    $lower = $Name.ToLower()
    foreach ($h in $NameHints) { if ($lower.Contains($h)) { return $true } }
    if ($MinMbParam -gt 0) { return ($Size -ge $BigEnough) }
    return $true
}

function Get-InstallerRoots {
    param([string]$DriveArg)
    $sys = Get-SystemDriveLetter
    $downloadDirs = @("$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop", "$env:USERPROFILE\Documents",
                      "$env:USERPROFILE\OneDrive\桌面", "$env:USERPROFILE\OneDrive\文档",
                      "$env:USERPROFILE\Downloads\Programs") |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $roots = @()
    $d = $DriveArg.Trim()
    if ($d -and $d -ne 'all') {
        $up = $d.ToUpper().Substring(0, 1)
        if ($up -eq $sys) { $roots = @($downloadDirs | ForEach-Object { @{ root = $_; deep = 3 } }) }
        else { $roots = @(@{ root = "$up`:\"; deep = 8 }) }
    } elseif ($d -eq 'all') {
        $roots = @($downloadDirs | ForEach-Object { @{ root = $_; deep = 3 } })
        foreach ($l in (Get-DriveLetters)) {
            if ($l -ne $sys) { $roots += @{ root = "$l`:\"; deep = 8 } }
        }
    } else {
        $roots = @($downloadDirs | ForEach-Object { @{ root = $_; deep = 3 } })
    }
    return $roots
}

if ($Action -eq 'scan') {
    $minBytes = [Math]::Max($MinMb, 0) * 1MB
    $cutoff = if ($MinDays -gt 0) { (Get-Date).AddDays(-$MinDays) } else { $null }
    $items = [System.Collections.Generic.List[object]]::new()
    $scanned = 0

    foreach ($r in (Get-InstallerRoots -DriveArg $Drive)) {
        Write-Log "扫描 $($r.root)（深度 $($r.deep)）"
        foreach ($f in (Get-ChildItem -LiteralPath $r.root -Recurse -File -Force -Depth $r.deep -ErrorAction SilentlyContinue)) {
            $scanned++
            if ($Exts -notcontains $f.Extension.ToLower()) { continue }
            if ($f.Length -lt $minBytes) { continue }
            if ($cutoff -and $f.LastWriteTime -gt $cutoff) { continue }
            if (-not (Test-InstallerLike -Name $f.Name -Size $f.Length -MinMbParam $MinMb)) { continue }
            $items.Add([PSCustomObject]@{
                id = ('ins:' + (New-CandidateId -Path $f.FullName).Substring(0, 16))
                path = $f.FullName; size = $f.Length
                mtime = $f.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
                days = Get-FileAgeDays -FileInfo $f
                ext = $f.Extension.TrimStart('.').ToLower()
            })
        }
    }

    $items = @($items | Sort-Object size -Descending)
    $total = ($items | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    $sessionFile = Save-Session -Name 'installer' -Candidates $items
    Write-Result -Status ok -Data ([ordered]@{
        scanned = $scanned; count = $items.Count; total_bytes = [int64]$total
        session = $sessionFile; items = $items
    })
}

if ($Action -eq 'delete') {
    if (-not $Session) { Write-Result -Status error -Error 'delete 需要 -Session' }
    try { $sess = Load-Session -Path $Session } catch { Write-Result -Status error -Error $_.Exception.Message }
    if (-not $Ids) { Write-Result -Status error -Error '需要 -Ids <id,...>' }
    $idList = $Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $targets = @($sess.candidates | Where-Object { $idList -contains $_.id })

    $deleted = 0; $deletedBytes = [int64]0
    $skipped = [System.Collections.Generic.List[object]]::new()
    $errors  = [System.Collections.Generic.List[string]]::new()
    $audit = [System.Collections.Generic.List[string]]::new()

    foreach ($t in $targets) {
        try {
            if (Test-ProtectedPath -Path $t.path) {
                $skipped.Add([PSCustomObject]@{ path = $t.path; reason = '受保护路径，已拦截' }); continue
            }
            $f = Get-Item -LiteralPath $t.path -ErrorAction SilentlyContinue
            if (-not $f -or $f.PSIsContainer) { $skipped.Add([PSCustomObject]@{ path = $t.path; reason = '非文件或已不存在' }); continue }
            if ($Purge) { Remove-ItemPurge -Path $t.path } else { Move-ToRecycleBinSafe -Path $t.path }
            $deleted++; $deletedBytes += $f.Length; $audit.Add($t.path)
        } catch {
            if (Test-BusyError -ErrorRecord $_) {
                $skipped.Add([PSCustomObject]@{ path = $t.path; reason = '使用中或无权访问，已跳过' })
            } else { $errors.Add("$($t.path): $($_.Exception.Message)") }
        }
    }

    if ($audit.Count -gt 0) {
        $act = 'trash'; if ($Purge) { $act = 'purge' }
        Write-AuditLog -Action $act -Items $audit -Extra @{ module = 'installer' }
    }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; deleted_bytes = $deletedBytes
        skipped_count = $skipped.Count; error_count = $errors.Count
        skipped = $skipped; errors = $errors
    })
}
