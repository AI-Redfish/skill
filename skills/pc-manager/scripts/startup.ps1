<#
startup.ps1 — 启动项管理（注册表 Run / 启动文件夹 / 计划任务三源）

复刻 grclean startup.ts。
  采集源：HKCU/HKLM(64+32位) 的 Run/RunOnce；用户+所有用户启动文件夹 .lnk；
          schtasks 非 \Microsoft\ 任务
  禁用机制（可逆、不丢数据）：注册表值名 / .lnk 文件名追加 .grdisabled 后缀；
          计划任务用 schtasks /change /disable
  id 编码 reg|hive|sub|name / folder|路径 / task|名称，操作时后端反查。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File startup.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File startup.ps1 -Action disable -Id '<id>'
  powershell -NoProfile -ExecutionPolicy Bypass -File startup.ps1 -Action enable  -Id '<id>'

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('list', 'enable', 'disable')][string]$Action = 'list',
    [string]$Id = ''
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 
$DisabledSuffix = '.grdisabled'

$RunTargets = @(
    @{ h = 'HKCU'; s = 'Software\Microsoft\Windows\CurrentVersion\Run' }
    @{ h = 'HKCU'; s = 'Software\Microsoft\Windows\CurrentVersion\RunOnce' }
    @{ h = 'HKLM'; s = 'Software\Microsoft\Windows\CurrentVersion\Run' }
    @{ h = 'HKLM'; s = 'Software\Microsoft\Windows\CurrentVersion\RunOnce' }
    @{ h = 'HKLM'; s = 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run' }
    @{ h = 'HKLM'; s = 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce' }
)

function Get-StartupEntries {
    $out = [System.Collections.Generic.List[object]]::new()

    # 1) 注册表 Run/RunOnce
    foreach ($t in $RunTargets) {
        $full = "$($t.h):\$($t.s)"
        $props = Get-ItemProperty -Path $full -ErrorAction SilentlyContinue
        if (-not $props) { continue }
        foreach ($p in $props.PSObject.Properties) {
            if ($p.Name -like 'PS*') { continue }
            $disabled = $p.Name.EndsWith($DisabledSuffix)
            $display = $p.Name
            if ($disabled) { $display = $p.Name.Substring(0, $p.Name.Length - $DisabledSuffix.Length) }
            $out.Add([PSCustomObject]@{
                id = "reg|$($t.h)|$($t.s)|$($p.Name)"; name = $display
                command = "$($p.Value)"; location = "$($t.h): $($t.s)"
                source = 'registry'; enabled = (-not $disabled)
            })
        }
    }

    # 2) 启动文件夹（当前用户 + 所有用户）
    $folders = @()
    if ($env:APPDATA) { $folders += Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup' }
    if ($env:ProgramData) { $folders += Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Startup' }
    foreach ($d in $folders) {
        foreach ($f in (Get-ChildItem -LiteralPath $d -Force -ErrorAction SilentlyContinue)) {
            if ($f.Name.EndsWith('.lnk' + $DisabledSuffix)) {
                $stem = $f.Name.Substring(0, $f.Name.Length - ('.lnk' + $DisabledSuffix).Length)
                $out.Add([PSCustomObject]@{ id = "folder|$($f.FullName)"; name = $stem; command = $f.FullName; location = '启动文件夹'; source = 'folder'; enabled = $false })
            } elseif ($f.Name.EndsWith('.lnk')) {
                $out.Add([PSCustomObject]@{ id = "folder|$($f.FullName)"; name = $f.BaseName; command = $f.FullName; location = '启动文件夹'; source = 'folder'; enabled = $true })
            }
        }
    }

    # 3) 计划任务（best-effort，过滤系统任务）
    $csv = schtasks /query /fo CSV /nh 2>$null
    foreach ($line in ($csv -split "`r?`n")) {
        if (-not $line.Trim()) { continue }
        # 简单 CSV 解析（schtasks 字段不含引号内逗号时可靠；复杂行容忍失败）
        $cols = $line.Trim('"') -split '","'
        if ($cols.Count -lt 3) { continue }
        $name = $cols[0].Trim()
        if (-not $name -or $name.ToLower().Contains('\microsoft\')) { continue }
        $status = $cols[2].Trim()
        $out.Add([PSCustomObject]@{
            id = "task|$name"; name = $name.TrimStart('\'); command = $name
            location = '任务计划程序'; source = 'task'
            enabled = (-not $status.ToLower().Contains('disabled'))
        })
    }
    return $out
}

if ($Action -eq 'list') {
    $entries = Get-StartupEntries
    $sessionFile = Save-Session -Name 'startup' -Candidates $entries
    Write-Result -Status ok -Data ([ordered]@{
        count = $entries.Count
        enabled_count = @($entries | Where-Object enabled).Count
        session = $sessionFile; entries = $entries
    })
}

if ($Action -in @('enable', 'disable')) {
    if (-not $Id) { Write-Result -Status error -Error "需要 -Id（从 list 结果取）" }
    $wantEnabled = ($Action -eq 'enable')
    try {
        if ($Id.StartsWith('reg|')) {
            $parts = $Id -split '\|', 4
            $hive = $parts[1]; $sub = $parts[2]; $name = $parts[3]
            $isDisabled = $name.EndsWith($DisabledSuffix)
            $targetDisabled = -not $wantEnabled
            if ($isDisabled -ne $targetDisabled) {
                $newName = $name
                if ($targetDisabled) { $newName = $name + $DisabledSuffix }
                else { $newName = $name.Substring(0, $name.Length - $DisabledSuffix.Length) }
                Rename-ItemProperty -Path "$($hive):\$($sub)" -Name $name -NewName $newName -ErrorAction Stop
            }
        } elseif ($Id.StartsWith('folder|')) {
            $p = $Id.Substring('folder|'.Length)
            $isDisabled = $p.EndsWith($DisabledSuffix)
            $targetDisabled = -not $wantEnabled
            if ($isDisabled -ne $targetDisabled) {
                $target = $p
                if ($targetDisabled) { $target = $p + $DisabledSuffix }
                else { $target = $p.Substring(0, $p.Length - $DisabledSuffix.Length) }
                Rename-Item -LiteralPath $p -NewName ([System.IO.Path]::GetFileName($target)) -ErrorAction Stop
            }
        } elseif ($Id.StartsWith('task|')) {
            $name = $Id.Substring('task|'.Length)
            $verb = '/disable'; if ($wantEnabled) { $verb = '/enable' }
            schtasks /change /tn $name $verb | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "schtasks 退出码 $LASTEXITCODE（任务名含特殊字符或需管理员）" }
        } else {
            Write-Result -Status error -Error '无法识别的启动项 id'
        }
        Write-AuditLog -Action 'startup' -Items @($Id) -Extra @{ op = $Action }
        Write-Result -Status ok -Data @{ id = $Id; action = $Action; done = $true }
    } catch {
        Write-Result -Status error -Error "启动项操作失败：$($_.Exception.Message)"
    }
}
