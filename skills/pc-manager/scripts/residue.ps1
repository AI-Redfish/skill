<#
residue.ps1 — 卸载残留检测（软件卸载后留下的空壳目录）

复刻 grclean residue.ts。判定逻辑（宁漏报不误报）：
  1. 从卸载注册表汇总「确实还装着」的程序名/厂商/安装目录名 → 白名单词元
  2. 扫 Program Files / Program Files (x86) / AppData\Local / AppData\Roaming 的一级子目录
  3. 词元匹配不到 + 体积≥阈值 + 长期未动(默认60天) 才列为残留候选
  4. 系统/厂商/运行时目录硬编码排除；采集失败时全部视为在用（不误报）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File residue.ps1 -Action scan [-MinMb 10] [-MinDays 60]
  powershell -NoProfile -ExecutionPolicy Bypass -File residue.ps1 -Action delete -Session <会话> -Ids id1,id2 [-Purge]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete')][string]$Action = 'scan',
    [int]$MinMb = 10,
    [int]$MinDays = 60,
    [string]$Session = '',
    [string]$Ids = '',
    [switch]$Purge
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$DenyNames = @('microsoft','microsoft shared','windows','windowsapps','windows defender','windows nt',
               'windows media player','windows photo viewer','windows portable devices','windows sidebar',
               'common files','internet explorer','nvidia','nvidia corporation','amd','intel','realtek',
               'packages','temp','cache','crashdumps','desktop','programs','appdata','default','public',
               'all users','nodejs','python','git','java','adobe')

function Get-Norm {
    param([string]$Text)
    return ($Text.ToLower() -replace '[^a-z0-9一-龥]', '')
}

# 从卸载注册表取在装程序词元（对应 residue.ts installedTokens；采集失败返回空集合=全部视为在用）
function Get-InstalledTokens {
    $tokens = [System.Collections.Generic.HashSet[string]]::new()
    try {
        $roots = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                   'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                   'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')
        foreach ($root in $roots) {
            if (-not (Test-Path $root)) { continue }
            foreach ($k in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
                $p = Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction SilentlyContinue
                if (-not $p -or -not $p.DisplayName) { continue }
                [void]$tokens.Add((Get-Norm $p.DisplayName))
                if ($p.Publisher) { [void]$tokens.Add((Get-Norm $p.Publisher)) }
                if ($p.InstallLocation) {
                    $parts = @("$($p.InstallLocation)" -split '[\\/]' | Where-Object { $_ })
                    if ($parts.Count -gt 0) { [void]$tokens.Add((Get-Norm $parts[-1])) }
                }
            }
        }
    } catch { return [System.Collections.Generic.HashSet[string]]::new() }
    return $tokens
}

function Test-MatchesInstalled {
    param([string]$DirName, $Tokens)
    if ($Tokens.Count -eq 0) { return $true }   # 采集失败 → 保守认为在用
    $n = Get-Norm $DirName
    if (-not $n) { return $true }
    foreach ($t in $Tokens) {
        if (-not $t) { continue }
        if ($t -eq $n) { return $true }
        if ($t.Length -ge 4 -and $n.Contains($t)) { return $true }
        if ($n.Length -ge 4 -and $t.Contains($n)) { return $true }
    }
    return $false
}

if ($Action -eq 'scan') {
    $minBytes = [Math]::Max($MinMb, 0) * 1MB
    $cutoff = (Get-Date).AddDays(-[Math]::Max($MinDays, 0))
    $tokens = Get-InstalledTokens
    Write-Log "在装程序词元: $($tokens.Count) 个"

    $roots = @(
        @{ dir = $env:ProgramFiles; label = 'Program Files' },
        @{ dir = ${env:ProgramFiles(x86)}; label = 'Program Files (x86)' },
        @{ dir = $env:LOCALAPPDATA; label = 'AppData\Local' },
        @{ dir = $env:APPDATA; label = 'AppData\Roaming' }
    ) | Where-Object { $_.dir -and (Test-Path -LiteralPath $_.dir) }

    $items = [System.Collections.Generic.List[object]]::new()
    foreach ($r in $roots) {
        foreach ($e in (Get-ChildItem -LiteralPath $r.dir -Directory -Force -ErrorAction SilentlyContinue)) {
            $lower = $e.Name.ToLower()
            if ($DenyNames -contains $lower) { continue }
            if ($lower.StartsWith('microsoft')) { continue }
            if ($e.LastWriteTime -gt $cutoff) { continue }         # 仍在写入 = 软件还在用
            if (Test-MatchesInstalled -DirName $e.Name -Tokens $tokens) { continue }
            $size = Get-DirSize -Path $e.FullName -MaxFiles 20000
            if ($size -lt $minBytes) { continue }
            $items.Add([PSCustomObject]@{
                id = ('res:' + (New-CandidateId -Path $e.FullName).Substring(0, 16))
                name = $e.Name; path = $e.FullName; size = $size
                mtime = $e.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
                days = Get-FileAgeDays -FileInfo $e; source = $r.label
            })
        }
    }

    $items = @($items | Sort-Object size -Descending)
    $total = ($items | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    $sessionFile = Save-Session -Name 'residue' -Candidates $items
    Write-Result -Status ok -Data ([ordered]@{
        count = $items.Count; total_bytes = [int64]$total
        session = $sessionFile; items = $items
        hint = '残留判定为启发式（在装白名单反查+60天未动），删除前请逐条确认；默认不勾选'
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
            $d = Get-Item -LiteralPath $t.path -Force -ErrorAction SilentlyContinue
            if (-not $d -or -not $d.PSIsContainer) { $skipped.Add([PSCustomObject]@{ path = $t.path; reason = '目录已不存在' }); continue }
            if ($Purge) { Remove-ItemPurge -Path $t.path } else { Move-ToRecycleBinSafe -Path $t.path }
            $deleted++; $deletedBytes += $t.size; $audit.Add($t.path)
        } catch {
            if (Test-BusyError -ErrorRecord $_) {
                $skipped.Add([PSCustomObject]@{ path = $t.path; reason = '使用中或无权访问，已跳过' })
            } else { $errors.Add("$($t.path): $($_.Exception.Message)") }
        }
    }

    if ($audit.Count -gt 0) {
        $act = 'trash'; if ($Purge) { $act = 'purge' }
        Write-AuditLog -Action $act -Items $audit -Extra @{ module = 'residue' }
    }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; deleted_bytes = $deletedBytes
        skipped_count = $skipped.Count; error_count = $errors.Count
        skipped = $skipped; errors = $errors
    })
}
