<#
uninstall.ps1 — 已安装程序管理（枚举 + 触发原生卸载 + 残留扫描联动）

复刻 grclean uninstall.ts。
  枚举：与「控制面板→程序和功能」同源（HKCU/HKLM64/HKLM32 Uninstall 三视图）；
        过滤无名称/SystemComponent/父组件子项/安全更新补丁
  卸载：id 后端反查注册表重读卸载命令（防注入）；msiexec /I 自动改 /X；
        解析 exe+参数直接 spawn（不加 shell），解析失败才退 cmd /C
        仅启动卸载程序（带 UI），不等待结束、不静默删目录

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1 -Action uninstall -Id 'HKLM|64|<KeyName>' [-Quiet]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('list', 'uninstall')][string]$Action = 'list',
    [string]$Id = '',
    [switch]$Quiet
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

function Get-UninstallKeyPath {
    param([string]$Root, [string]$View)
    if ($Root -eq 'HKLM' -and $View -eq '32') { return 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' }
    return "$($Root):\\Software\Microsoft\Windows\CurrentVersion\Uninstall"
}

function Get-InstalledPrograms {
    $out = [System.Collections.Generic.List[object]]::new()
    $views = @(
        @{ r = 'HKCU'; v = '64' }, @{ r = 'HKLM'; v = '64' }, @{ r = 'HKLM'; v = '32' }
    )
    foreach ($t in $views) {
        $base = Get-UninstallKeyPath -Root $t.r -View $t.v
        if (-not (Test-Path $base)) { continue }
        foreach ($name in (Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object { $_.PSChildName })) {
            $k = Get-ItemProperty -LiteralPath (Join-Path $base $name) -ErrorAction SilentlyContinue
            if (-not $k) { continue }
            $dn = "$($k.DisplayName)".Trim()
            if (-not $dn) { continue }
            if ("$($k.SystemComponent)" -eq '1') { continue }
            if ("$($k.ParentDisplayName)".Trim()) { continue }
            $rt = "$($k.ReleaseType)".ToLower()
            if ($rt -in @('security update', 'update', 'hotfix')) { continue }
            $noRemove = ("$($k.NoRemove)" -eq '1')
            $us = "$($k.UninstallString)"
            # 安装日期归一化（YYYYMMDD → YYYY-MM-DD；异常年份置空）
            $date = ''
            $raw = "$($k.InstallDate)".Trim()
            if ($raw -match '^(\d{4})(\d{2})(\d{2})$') {
                $y = [int]$Matches[1]
                if ($y -ge 1990 -and $y -le ((Get-Date).Year + 1)) { $date = "$($Matches[1])-$($Matches[2])-$($Matches[3])" }
            }
            $out.Add([PSCustomObject]@{
                id = "$($t.r)|$($t.v)|$name"    # 后端反查用，杜绝命令注入
                name = $dn; version = "$($k.DisplayVersion)"; publisher = "$($k.Publisher)"
                install_location = "$($k.InstallLocation)".Trim('"'); install_date = $date
                size_kb = [int64]("$($k.EstimatedSize)" -as [int64])
                uninstall_string = $us
                quiet_uninstall_string = "$($k.QuietUninstallString)"
                can_uninstall = (-not $noRemove -and $us.Trim())
            })
        }
    }
    return @($out | Sort-Object { $_.name.ToLower() })
}

if ($Action -eq 'list') {
    $entries = Get-InstalledPrograms
    $sessionFile = Save-Session -Name 'uninstall' -Candidates $entries
    Write-Result -Status ok -Data ([ordered]@{
        count = $entries.Count; session = $sessionFile; entries = $entries
    })
}

if ($Action -eq 'uninstall') {
    if (-not $Id) { Write-Result -Status error -Error '需要 -Id（从 list 结果取，格式 root|view|keyname）' }
    $parts = $Id -split '\|', 3
    if ($parts.Count -lt 3) { Write-Result -Status error -Error '无法识别的卸载项 id' }
    $root = $parts[0]; $view = $parts[1]; $key = $parts[2]

    # 后端反查：从注册表重新读取卸载命令
    $dir = Get-UninstallKeyPath -Root $root -View $view
    try {
        $k = Get-ItemProperty -LiteralPath (Join-Path $dir $key) -ErrorAction Stop
    } catch { Write-Result -Status error -Error "读取卸载命令失败：$($_.Exception.Message)" }
    $cmd = "$($k.UninstallString)"
    if ($Quiet -and "$($k.QuietUninstallString)".Trim()) { $cmd = "$($k.QuietUninstallString)" }
    if (-not $cmd.Trim()) { Write-Result -Status error -Error '该项没有可用的卸载命令' }

    # MsiExec /I{GUID} → /X{GUID}（修改对话框 → 真卸载）
    $finalCmd = $cmd
    if ($finalCmd.ToLower().Contains('msiexec') -and $finalCmd.ToLower().Contains('/i')) {
        $pos = $finalCmd.ToLower().IndexOf('/i')
        $chars = $finalCmd.ToCharArray()
        if ($pos -ge 0 -and $pos + 1 -lt $chars.Length) { $chars[$pos + 1] = 'X' }
        $finalCmd = -join $chars
    }

    # 解析 exe + 参数（引号感知；对应 uninstall.ts parseCommand）
    $exe = ''; $args = @(); $cur = ''; $inQ = $false
    foreach ($c in $finalCmd.Trim().ToCharArray()) {
        if ($c -eq '"') { $inQ = -not $inQ; continue }
        if ((-not $inQ) -and [char]::IsWhiteSpace($c)) {
            if ($cur) { if (-not $exe) { $exe = $cur } else { $args += $cur }; $cur = '' }
            continue
        }
        $cur += $c
    }
    if ($cur) { if (-not $exe) { $exe = $cur } else { $args += $cur } }

    # 解析可执行文件真实路径（PATH/System32 兜底）
    $resolved = $null
    if ($exe) {
        if ([System.IO.Path]::IsPathRooted($exe) -and (Test-Path -LiteralPath $exe)) { $resolved = $exe }
        elseif (Test-Path -LiteralPath $exe) { $resolved = (Resolve-Path -LiteralPath $exe).Path }
        else {
            $dirs = @($env:Path -split ';') + @((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) | Where-Object { $_ }
            foreach ($d in $dirs) {
                $full = Join-Path $d $exe
                if (Test-Path -LiteralPath $full) { $resolved = $full; break }
            }
        }
    }

    try {
        if ($resolved) {
            Start-Process -FilePath $resolved -ArgumentList $args -WindowStyle Hidden -PassThru -ErrorAction Stop | Out-Null
        } else {
            # 解析不到 exe 才退 cmd /C（兼容含 shell 语法的卸载命令）
            Start-Process -FilePath "$env:ComSpec" -ArgumentList @('/C', $finalCmd) -WindowStyle Hidden -ErrorAction Stop | Out-Null
        }
        Write-AuditLog -Action 'uninstall' -Items @($Id) -Extra @{ command = $finalCmd }
        Write-Result -Status ok -Data @{ launched = $true; id = $Id; command = $finalCmd; note = '已启动原生卸载程序（带界面），请在弹出的窗口中完成卸载' }
    } catch {
        Write-Result -Status error -Error "启动卸载程序失败：$($_.Exception.Message)"
    }
}
