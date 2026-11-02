<#
logs.ps1 — 无用日志清理（应用日志 / 临时日志 / 崩溃转储与 WER 报告）

复刻 grclean logs.ts。三组：
  app   应用日志（%LOCALAPPDATA% / %APPDATA% 下 *.log；其他盘扫盘根深度8）
  temp  临时日志（%TEMP% 下 *.log）
  crash 崩溃转储/错误报告（CrashDumps *.dmp + WER 报告目录整体计体积）
系统关键日志不在扫描范围（根仅限用户级目录，Windows 目录由保护防线二次拦截）。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File logs.ps1 -Action scan [-MinDays 0] [-Drive ''|all|D]
  powershell -NoProfile -ExecutionPolicy Bypass -File logs.ps1 -Action delete -Session <会话> -Ids id1,id2 [-Purge]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete')][string]$Action = 'scan',
    [int]$MinDays = 0,
    [string]$Drive = '',
    [string]$Session = '',
    [string]$Ids = '',
    [switch]$Purge
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$DriveIgnore = '\\(\$Recycle\.Bin|System Volume Information|Windows|WinSxS|Recovery|\$WinREAgent)\\'

function Get-LogRoots {
    param([string]$DriveArg)
    $sys = Get-SystemDriveLetter
    $roots = @()
    $d = $DriveArg.Trim()
    if ($d -and $d -ne 'all') {
        $up = $d.ToUpper() -replace '[^A-Z]', ''
        if (-not $up) { return $roots }
        if ($up -eq $sys) {
            foreach ($r in @($env:LOCALAPPDATA, $env:APPDATA, $env:TEMP)) {
                if ($r -and (Test-Path -LiteralPath $r)) {
                    $g = 'app'; if ($r -eq $env:TEMP) { $g = 'temp' }
                    $roots += @{ root = $r; group = $g; deep = 6 }
                }
            }
        } elseif (Test-Path -LiteralPath "$up`:\") {
            $roots += @{ root = "$up`:\"; group = 'app'; deep = 8 }
        }
        return $roots
    }
    foreach ($r in @($env:LOCALAPPDATA, $env:APPDATA)) {
        if ($r -and (Test-Path -LiteralPath $r)) { $roots += @{ root = $r; group = 'app'; deep = 6 } }
    }
    if ($env:TEMP -and (Test-Path -LiteralPath $env:TEMP)) { $roots += @{ root = $env:TEMP; group = 'temp'; deep = 6 } }
    if ($d -eq 'all') {
        foreach ($l in (Get-DriveLetters)) {
            if ($l -ne $sys -and (Test-Path -LiteralPath "$l`:\")) { $roots += @{ root = "$l`:\"; group = 'app'; deep = 8 } }
        }
    }
    return $roots
}

function Get-CrashRoots {
    return @(
        @{ root = (Join-Path $env:LOCALAPPDATA 'CrashDumps'); label = '崩溃转储' },
        @{ root = (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER\ReportArchive'); label = 'WER 归档' },
        @{ root = (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER\ReportQueue'); label = 'WER 队列' }
    ) | Where-Object { Test-Path -LiteralPath $_.root }
}

if ($Action -eq 'scan') {
    $cutoff = $null
    if ($MinDays -gt 0) { $cutoff = (Get-Date).AddDays(-$MinDays) }
    $items = [System.Collections.Generic.List[object]]::new()
    $scanned = 0

    foreach ($r in (Get-LogRoots -DriveArg $Drive)) {
        Write-Log "扫描 $($r.root)（$($r.group)，深度 $($r.deep)）"
        foreach ($f in (Get-ChildItem -LiteralPath $r.root -Recurse -File -Force -Depth $r.deep -ErrorAction SilentlyContinue |
                        Where-Object { $_.FullName -notmatch $DriveIgnore })) {
            if ($f.Extension.ToLower() -ne '.log') { continue }
            $scanned++
            if ($f.Length -eq 0) { continue }
            if ($cutoff -and $f.LastWriteTime -gt $cutoff) { continue }
            $items.Add([PSCustomObject]@{
                id = ('log:' + (New-CandidateId -Path $f.FullName).Substring(0, 16))
                group = $r.group; name = $f.Name; path = $f.FullName; size = $f.Length
                mtime = $f.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
            })
        }
    }

    # 崩溃转储 + WER 报告目录（按目录整体统计；对应 logs.ts 第2段）
    $dv = ''
    if ($Drive) { $dv = $Drive.ToUpper() -replace '[^A-Z]', '' }
    foreach ($c in (Get-CrashRoots)) {
        if ($dv -and $dv -ne 'ALL' -and -not $c.root.ToUpper().StartsWith("$dv`:")) { continue }
        foreach ($f in (Get-ChildItem -LiteralPath $c.root -Recurse -File -Filter *.dmp -Force -Depth 4 -ErrorAction SilentlyContinue)) {
            $scanned++
            if ($cutoff -and $f.LastWriteTime -gt $cutoff) { continue }
            $items.Add([PSCustomObject]@{
                id = ('log:' + (New-CandidateId -Path $f.FullName).Substring(0, 16))
                group = 'crash'; name = $f.Name; path = $f.FullName; size = $f.Length
                mtime = $f.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
            })
        }
        foreach ($d in (Get-ChildItem -LiteralPath $c.root -Directory -Force -ErrorAction SilentlyContinue)) {
            $size = Get-DirSize -Path $d.FullName -MaxFiles 5000
            if ($size -le 0) { continue }
            $st = Get-Item -LiteralPath $d.FullName -ErrorAction SilentlyContinue
            if ($cutoff -and $st -and $st.LastWriteTime -gt $cutoff) { continue }
            $items.Add([PSCustomObject]@{
                id = ('log:' + (New-CandidateId -Path $d.FullName).Substring(0, 16))
                group = 'crash'; name = "$($c.label) · $($d.Name)"; path = $d.FullName; size = $size
                mtime = $(if ($st) { $st.LastWriteTime.ToString('yyyy-MM-dd HH:mm') } else { '' })
            })
        }
    }

    $total = ($items | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    $sessionFile = Save-Session -Name 'logs' -Candidates $items
    Write-Result -Status ok -Data ([ordered]@{
        scanned = $scanned; count = $items.Count; total_bytes = [int64]$total
        by_group = @{
            app = @($items | Where-Object group -eq 'app' | Measure-Object -Property size -Sum).Sum
            temp = @($items | Where-Object group -eq 'temp' | Measure-Object -Property size -Sum).Sum
            crash = @($items | Where-Object group -eq 'crash' | Measure-Object -Property size -Sum).Sum
        }
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
        # 展开待删条目（crash 组是目录，需展开为文件清单；对应 logs.ts expandFiles）
        $paths = @()
        if (Test-Path -LiteralPath $t.path -PathType Container) {
            $paths = @(Get-ChildItem -LiteralPath $t.path -Recurse -File -Force -ErrorAction SilentlyContinue |
                       Select-Object -First 5000 | ForEach-Object { $_.FullName })
            if ($paths.Count -eq 0) { $paths = @($t.path) }   # 空目录整删
        } else { $paths = @($t.path) }

        foreach ($p in $paths) {
            try {
                if (Test-ProtectedPath -Path $p) {
                    $skipped.Add([PSCustomObject]@{ path = $p; reason = '受保护路径（系统日志），已拦截' }); continue
                }
                $f = Get-Item -LiteralPath $p -ErrorAction SilentlyContinue
                if (-not $f) { continue }
                if ($Purge) { Remove-ItemPurge -Path $p } else { Move-ToRecycleBinSafe -Path $p }
                $deleted++; $deletedBytes += $f.Length; $audit.Add($p)
            } catch {
                if (Test-BusyError -ErrorRecord $_) {
                    $skipped.Add([PSCustomObject]@{ path = $p; reason = '使用中或无权访问，已跳过' })
                } else { $errors.Add("$($p): $($_.Exception.Message)") }
            }
        }
    }

    if ($audit.Count -gt 0) {
        $act = 'trash'; if ($Purge) { $act = 'purge' }
        Write-AuditLog -Action $act -Items $audit -Extra @{ module = 'logs' }
    }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; deleted_bytes = $deletedBytes
        skipped_count = $skipped.Count; error_count = $errors.Count
        skipped = $skipped; errors = $errors
    })
}
