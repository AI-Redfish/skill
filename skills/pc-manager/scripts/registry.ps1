<#
registry.ps1 — 注册表清理（只检测「判定明确」的失效项，绝不激进）

复刻 grclean registry.ts。四类（环境变量先展开再判定，避免 %windir% 误判）：
  1. 卸载残留：Uninstall 条目的卸载程序/安装目录已不存在
  2. 无效启动项：Run/RunOnce 指向的 exe 已不存在（msiexec 跳过）
  3. 丢失的共享 DLL：SharedDLLs 登记的文件已不存在
  4. 无效应用路径：App Paths 登记的 exe 已不存在
安全约束：不碰 HKLM\SYSTEM、不检测服务项与文件关联；删除前自采快照备份
（备份失败整体中止）；删除前二次校验（项仍存在 + 目标仍不存在）；支持从备份恢复。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File registry.ps1 -Action scan
  powershell -NoProfile -ExecutionPolicy Bypass -File registry.ps1 -Action delete -Session <会话> [-Ids id,...]
  powershell -NoProfile -ExecutionPolicy Bypass -File registry.ps1 -Action backups
  powershell -NoProfile -ExecutionPolicy Bypass -File registry.ps1 -Action restore -BackupFile <备份.json>

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete', 'backups', 'restore')][string]$Action = 'scan',
    [string]$Session = '',
    [string]$Ids = '',
    [string]$BackupFile = ''
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

function Get-BackupDir {
    $dir = Join-Path (Get-PcManagerDir) 'registry-backup'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

# 从命令行提取 exe 路径（引号感知；未加引号时逐段累加找第一个真实存在的 .exe）
# 复刻 registry.ts Get-ExeFromCommand 的防误判逻辑（"C:\Program" 不当路径）
function Get-ExeFromCommand {
    param([string]$Cmd)
    if (-not $Cmd -or -not $Cmd.Trim()) { return '' }
    $s = $Cmd.Trim()
    if ($s.StartsWith('"')) {
        $idx = $s.IndexOf('"', 1)
        if ($idx -le 1) { return '' }
        return $s.Substring(1, $idx - 1)
    }
    $parts = $s -split '\s+'
    for ($i = 1; $i -le $parts.Count; $i++) {
        $cand = ($parts[0..($i - 1)] -join ' ')
        if ($cand -match '\.exe$' -and (Test-Path -LiteralPath $cand -ErrorAction SilentlyContinue)) { return $cand }
    }
    if ($s -match '.+?\.exe') { return $Matches[0].Trim() }
    return ''
}

function Test-TargetGone {
    param([string]$Path)
    if (-not $Path -or -not $Path.Trim()) { return $false }
    if ($Path -notmatch '^[a-zA-Z]:') { return $false }
    $full = [Environment]::ExpandEnvironmentVariables($Path)
    if (-not $full.Trim()) { return $false }
    return (-not (Test-Path -LiteralPath $full -ErrorAction SilentlyContinue))
}

# ---------- 扫描（一次遍历完成四类检测） ----------
if ($Action -eq 'scan') {
    $found = [System.Collections.Generic.List[object]]::new()

    # 1) 卸载残留
    foreach ($root in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
        foreach ($k in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
            $p = Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction SilentlyContinue
            if (-not $p -or -not "$($p.DisplayName)".Trim()) { continue }
            $target = ''
            $us = "$($p.UninstallString)"
            if ($us -and $us -notmatch 'msiexec') {
                $exe = Get-ExeFromCommand -Cmd $us
                if (Test-TargetGone -Path $exe) { $target = $exe }
            }
            if (-not $target -and "$($p.InstallLocation)") {
                if (Test-TargetGone -Path "$($p.InstallLocation)") { $target = "$($p.InstallLocation)" }
            }
            if ($target) {
                $found.Add([PSCustomObject]@{
                    category = '卸载残留'; key_path = $root; name = $k.PSChildName
                    kind = 'key'; target = $target; detail = "$($p.DisplayName)"
                })
            }
        }
    }

    # 2) 无效启动项
    foreach ($root in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
                        'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
                        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
                        'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
                        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run')) {
        $props = Get-ItemProperty -Path $root -ErrorAction SilentlyContinue
        if (-not $props) { continue }
        foreach ($pr in $props.PSObject.Properties) {
            if ($pr.Name -like 'PS*') { continue }
            $cmd = "$($pr.Value)"
            if (-not $cmd.Trim() -or $cmd -match 'msiexec') { continue }
            $exe = Get-ExeFromCommand -Cmd $cmd
            if (Test-TargetGone -Path $exe) {
                $found.Add([PSCustomObject]@{
                    category = '无效启动项'; key_path = $root; name = $pr.Name
                    kind = 'value'; target = $exe; detail = $cmd
                })
            }
        }
    }

    # 3) 丢失的共享 DLL
    $sd = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDLLs'
    $props = Get-ItemProperty -Path $sd -ErrorAction SilentlyContinue
    if ($props) {
        foreach ($pr in $props.PSObject.Properties) {
            if ($pr.Name -like 'PS*') { continue }
            if (Test-TargetGone -Path $pr.Name) {
                $found.Add([PSCustomObject]@{
                    category = '丢失的共享DLL'; key_path = $sd; name = $pr.Name
                    kind = 'value'; target = $pr.Name; detail = $pr.Name
                })
            }
        }
    }

    # 4) 无效应用路径
    foreach ($root in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths',
                        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths')) {
        foreach ($k in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
            $rk = Get-Item -LiteralPath $k.PSPath -ErrorAction SilentlyContinue
            if (-not $rk) { continue }
            $def = "$($rk.GetValue(''))".Trim()
            if (-not $def) { continue }
            $exe = $def.Replace('"', '').Trim()
            if (Test-TargetGone -Path $exe) {
                $found.Add([PSCustomObject]@{
                    category = '无效应用路径'; key_path = $root; name = $k.PSChildName
                    kind = 'key'; target = $exe; detail = $def
                })
            }
        }
    }

    $items = @($found | ForEach-Object {
        $e = $_
        $e | Add-Member -NotePropertyName id -NotePropertyValue ('reg:' + (New-CandidateId "$($e.key_path)|$($e.name)").Substring(0, 16)) -Force
        $e
    })
    $sessionFile = Save-Session -Name 'registry' -Candidates $items
    Write-Result -Status ok -Data ([ordered]@{
        count = $items.Count; session = $sessionFile; items = $items
        by_category = @{
            uninstall = @($items | Where-Object category -eq '卸载残留').Count
            run = @($items | Where-Object category -eq '无效启动项').Count
            dll = @($items | Where-Object category -eq '丢失的共享DLL').Count
            appPaths = @($items | Where-Object category -eq '无效应用路径').Count
        }
    })
}

# ---------- 删除（先备份→再二次校验→再删；备份失败整体中止） ----------
if ($Action -eq 'delete') {
    if (-not $Session) { Write-Result -Status error -Error 'delete 需要 -Session' }
    try { $sess = Load-Session -Path $Session } catch { Write-Result -Status error -Error $_.Exception.Message }
    $all = @($sess.candidates)
    if ($Ids) {
        $idList = $Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $targets = @($all | Where-Object { $idList -contains $_.id })
    } else { $targets = $all }

    # 1) 备份（自采快照；kind=key 时读取子键全部值）
    $backupItems = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($e in $targets) {
            if ($e.kind -eq 'value') {
                $k = Get-Item -LiteralPath $e.key_path -ErrorAction SilentlyContinue
                $type = $null; $data = $null
                if ($k) {
                    try { $type = "$($k.GetValueKind($e.name))" } catch { }
                    if ($type -and $type -ne 'Binary') { $data = "$($k.GetValue($e.name))" }
                }
                $backupItems.Add([PSCustomObject]@{ kind = 'value'; key_path = $e.key_path; name = $e.name; type = $type; data = $data; category = $e.category; target = $e.target })
            } else {
                $full = "$($e.key_path)\$($e.name)"
                $vals = @()
                $k = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
                if ($k) {
                    foreach ($n in $k.GetValueNames()) {
                        if (-not $n) { continue }
                        $t = ''
                        try { $t = "$($k.GetValueKind($n))" } catch { continue }
                        if ($t -eq 'Binary') { continue }
                        $vals += [PSCustomObject]@{ name = $n; type = $t; data = "$($k.GetValue($n))" }
                    }
                }
                $backupItems.Add([PSCustomObject]@{ kind = 'key'; key_path = $e.key_path; name = $e.name; values = $vals; category = $e.category; target = $e.target })
            }
        }
        $backupPath = Join-Path (Get-BackupDir) ("backup-{0}.json" -f ((Get-Date).ToString('yyyy-MM-ddTHH-mm-ss').Replace(':', '-')))
        @{ created_at = (Get-Date).ToString('o'); items = $backupItems } |
            ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $backupPath -Encoding UTF8
    } catch {
        Write-Result -Status error -Error "备份失败，已中止删除（不会改动注册表）：$($_.Exception.Message)"
    }

    # 2) 逐项二次校验 + 删除
    $deleted = 0
    $skipped = [System.Collections.Generic.List[object]]::new()
    $errors  = [System.Collections.Generic.List[string]]::new()
    foreach ($e in $targets) {
        try {
            $full = "$($e.key_path)\$($e.name)"
            $exists = $false
            if ($e.kind -eq 'value') {
                $p = Get-ItemProperty -LiteralPath $e.key_path -ErrorAction SilentlyContinue
                if ($p -and ($p.PSObject.Properties.Name -contains $e.name)) { $exists = $true }
            } else { $exists = Test-Path -LiteralPath $full }
            if (-not $exists) { $skipped.Add([PSCustomObject]@{ name = $e.name; reason = '该项已不存在，跳过' }); continue }

            $t = [Environment]::ExpandEnvironmentVariables("$($e.target)")
            if (Test-Path -LiteralPath $t -ErrorAction SilentlyContinue) {
                $skipped.Add([PSCustomObject]@{ name = $e.name; reason = '目标路径已恢复存在，跳过（疑似误判）' }); continue
            }

            if ($e.kind -eq 'value') {
                Remove-ItemProperty -LiteralPath $e.key_path -Name $e.name -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            }
            $deleted++
        } catch { $errors.Add("$($e.key_path)\$($e.name): $($_.Exception.Message)") }
    }

    if ($deleted -gt 0) { Write-AuditLog -Action 'registry' -Items @($targets | ForEach-Object { "$($_.key_path)\$($_.name)" }) -Extra @{ backup = $backupPath } }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; backup_file = $backupPath
        skipped_count = $skipped.Count; error_count = $errors.Count
        skipped = $skipped; errors = $errors
    })
}

if ($Action -eq 'backups') {
    $list = @(Get-ChildItem -LiteralPath (Get-BackupDir) -Filter *.json -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $p = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                [PSCustomObject]@{ file = $_.FullName; created_at = $p.created_at; count = @($p.items).Count }
            } catch { }
        } | Sort-Object created_at -Descending)
    Write-Result -Status ok -Data @{ backups = $list }
}

if ($Action -eq 'restore') {
    if (-not $BackupFile) { Write-Result -Status error -Error 'restore 需要 -BackupFile' }
    try {
        $parsed = Get-Content -LiteralPath $BackupFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $restored = 0; $errs = @()
        foreach ($it in @($parsed.items)) {
            try {
                if ($it.kind -eq 'value') {
                    if (-not $it.type -or $null -eq $it.data) { $errs += "$($it.key_path)\$($it.name): 备份缺少值数据"; continue }
                    if (-not (Test-Path -LiteralPath $it.key_path)) { New-Item -Path $it.key_path -Force | Out-Null }
                    Set-ItemProperty -LiteralPath $it.key_path -Name $it.name -Value "$($it.data)" -Type $it.type -Force
                    $restored++
                } else {
                    $full = "$($it.key_path)\$($it.name)"
                    if (-not (Test-Path -LiteralPath $full)) {
                        New-Item -Path $it.key_path -Name $it.name -Force | Out-Null
                    }
                    foreach ($v in @($it.values)) {
                        Set-ItemProperty -LiteralPath $full -Name $v.name -Value "$($v.data)" -Type $v.type -Force -ErrorAction SilentlyContinue
                    }
                    $restored++
                }
            } catch { $errs += "$($it.key_path)\$($it.name): $($_.Exception.Message)" }
        }
        Write-Result -Status ok -Data @{ restored = $restored; errors = $errs }
    } catch {
        Write-Result -Status error -Error "备份文件无法解析：$($_.Exception.Message)"
    }
}
