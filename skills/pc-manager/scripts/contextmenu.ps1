<#
contextmenu.ps1 — 右键菜单管理（增/禁/删 + Win11 经典菜单切换）

复刻 grclean contextmenu.ts。
  扫描 HKCR 六类 shell 谓词（文件/文件夹/桌面背景/驱动器/Folder/所有对象）
  系统内置谓词白名单锁死不可操作；禁用 = 写 LegacyDisable 空串（可逆）；
  删除前 reg export 导出 .reg 备份；改动后需重启资源管理器生效。
  附：「此电脑」外壳图标（NameSpace 扩展）清理；Win11 经典右键菜单切换。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action disable|enable -Id '<id>'
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action delete -Id '<id>'
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action icons          # 外壳图标
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action icons-delete -Id '<id>'
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action classic [-Enabled:$false]
  powershell -NoProfile -ExecutionPolicy Bypass -File contextmenu.ps1 -Action restart-explorer

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'list',
    [string]$Id = '',
    [switch]$Enabled     # classic 动作：-Enabled=恢复经典菜单（默认）；不加=切回 Win11 新菜单
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$Roots = @(
    @{ path = 'Registry::HKEY_CLASSES_ROOT\*\shell'; label = '文件右键' },
    @{ path = 'Registry::HKEY_CLASSES_ROOT\Directory\shell'; label = '文件夹右键' },
    @{ path = 'Registry::HKEY_CLASSES_ROOT\Directory\Background\shell'; label = '桌面/文件夹空白处' },
    @{ path = 'Registry::HKEY_CLASSES_ROOT\Drive\shell'; label = '驱动器右键' },
    @{ path = 'Registry::HKEY_CLASSES_ROOT\Folder\shell'; label = '文件夹（含库）' },
    @{ path = 'Registry::HKEY_CLASSES_ROOT\AllFilesystemObjects\shell'; label = '所有文件系统对象' }
)

$SystemVerbs = @('open','runas','runasuser','edit','print','printto','find','opennewprocess',
                 'opennewwindow','opencontainingfolder','pintostartscreen','pintotaskbar','share',
                 'copyaspath','properties','new','openwith','enqueue','play','preview','mount',
                 'eject','format','restore','cut','copy','paste','delete','rename','link','undelete',
                 'scanwithdefender','windowsdefender')

$IconRoots = @(
    @{ path = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\MyComputer\NameSpace'; label = '此电脑（系统级）' },
    @{ path = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Explorer\MyComputer\NameSpace'; label = '此电脑（32位）' },
    @{ path = 'Registry::HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\MyComputer\NameSpace'; label = '此电脑（当前用户）' }
)

$SystemIconGuids = @('{b4bfcc3a-db2c-424c-b029-7fe99a87c641}','{d3162b92-9365-467a-956b-92703aca08af}',
                     '{088e3905-0323-4b02-9826-5d99428e115f}','{3dfdf296-dbec-4fb4-81d1-6a3438bcf4de}',
                     '{24ad3ad4-a569-4530-98e1-ab02f9417aa8}','{f86fa3ab-70d2-4fc7-9c99-fcbf05467f3a}',
                     '{0db7e03f-fc29-4dc6-9020-76841c354036}')

$ClassicKey = 'Registry::HKEY_CURRENT_USER\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}'

function Get-CtxBackupDir {
    $dir = Join-Path (Get-PcManagerDir) 'ctx-backups'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

function ConvertTo-RegKeyPath {
    param([string]$PsPath)
    $i = $PsPath.IndexOf('Registry::')
    if ($i -ge 0) { return $PsPath.Substring($i + 'Registry::'.Length) }
    return $PsPath
}

function Get-ContextMenuItems {
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($r in $Roots) {
        if (-not (Test-Path -LiteralPath $r.path)) { continue }
        foreach ($k in (Get-ChildItem -LiteralPath $r.path -ErrorAction SilentlyContinue)) {
            $verb = $k.PSChildName
            $label = "$((Get-ItemProperty -LiteralPath $k.PSPath -Name '(default)' -ErrorAction SilentlyContinue).'(default)')"
            $mui = "$((Get-ItemProperty -LiteralPath $k.PSPath -Name 'MUIVerb' -ErrorAction SilentlyContinue).'MUIVerb')"
            $name = $verb; if ($mui) { $name = $mui } elseif ($label) { $name = $label }
            $cmd = ''
            $cmdKey = Join-Path $k.PSPath 'command'
            if (Test-Path -LiteralPath $cmdKey) {
                $cmd = "$((Get-ItemProperty -LiteralPath $cmdKey -Name '(default)' -ErrorAction SilentlyContinue).'(default)')"
            }
            $disabled = $null -ne (Get-ItemProperty -LiteralPath $k.PSPath -Name 'LegacyDisable' -ErrorAction SilentlyContinue)
            $out.Add([PSCustomObject]@{
                id = 'ctx:' + (New-CandidateId -Path $k.PSPath).Substring(0, 16)
                name = $name; verb = $verb; source = $r.label; key = $k.PSPath
                command = $cmd; system = ($SystemVerbs -contains $verb.ToLower()); disabled = $disabled
            })
        }
    }
    return $out
}

function Get-ShellIcons {
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($r in $IconRoots) {
        if (-not (Test-Path -LiteralPath $r.path)) { continue }
        foreach ($k in (Get-ChildItem -LiteralPath $r.path -ErrorAction SilentlyContinue)) {
            $guid = $k.PSChildName
            $name = "$((Get-ItemProperty -LiteralPath $k.PSPath -Name '(default)' -ErrorAction SilentlyContinue).'(default)')"
            $out.Add([PSCustomObject]@{
                id = 'icon:' + (New-CandidateId -Path $k.PSPath).Substring(0, 16)
                name = $name; guid = $guid; source = $r.label; key = $k.PSPath
                system = ($SystemIconGuids -contains $guid.ToLower())
            })
        }
    }
    return $out
}

# ---------- 动作分发 ----------
try {
    switch ($Action) {
        'list' {
            $items = Get-ContextMenuItems
            $sessionFile = Save-Session -Name 'contextmenu' -Candidates $items
            Write-Result -Status ok -Data ([ordered]@{
                count = $items.Count; session = $sessionFile; items = $items
                note = '改动后需执行 restart-explorer 生效（会关闭已打开的文件夹窗口）'
            })
        }
        { $_ -in 'disable', 'enable' } {
            if (-not $Id) { Write-Result -Status error -Error '需要 -Id' }
            $item = Get-ContextMenuItems | Where-Object id -eq $Id
            if (-not $item) { Write-Result -Status error -Error '条目不在当前扫描结果内' }
            if ($item.system) { Write-Result -Status error -Error '系统内置项，禁止操作' }
            if ($Action -eq 'disable') {
                New-ItemProperty -LiteralPath $item.key -Name 'LegacyDisable' -Value '' -PropertyType String -Force | Out-Null
            } else {
                Remove-ItemProperty -LiteralPath $item.key -Name 'LegacyDisable' -Force -ErrorAction SilentlyContinue
            }
            Write-AuditLog -Action 'ctxmenu' -Items @($item.key) -Extra @{ op = $Action }
            Write-Result -Status ok -Data @{ id = $Id; op = $Action; done = $true }
        }
        'delete' {
            if (-not $Id) { Write-Result -Status error -Error '需要 -Id' }
            $item = Get-ContextMenuItems | Where-Object id -eq $Id
            if (-not $item) { Write-Result -Status error -Error '条目不在当前扫描结果内' }
            if ($item.system) { Write-Result -Status error -Error '系统内置项，禁止删除' }
            $regKey = ConvertTo-RegKeyPath -PsPath $item.key
            $bak = Join-Path (Get-CtxBackupDir) "$($item.verb -replace '[^\w.-]', '_')_$(Get-Date -Format yyyyMMddHHmmss).reg"
            reg export $regKey $bak /y | Out-Null     # 导出失败不阻断
            Remove-Item -LiteralPath $item.key -Recurse -Force -ErrorAction Stop
            Write-AuditLog -Action 'ctxmenu' -Items @($item.key) -Extra @{ op = 'delete'; backup = $bak }
            Write-Result -Status ok -Data @{ id = $Id; deleted = $true; backup = $bak }
        }
        'icons' {
            $items = Get-ShellIcons
            $sessionFile = Save-Session -Name 'shell-icons' -Candidates $items
            Write-Result -Status ok -Data @{ count = $items.Count; session = $sessionFile; items = $items }
        }
        'icons-delete' {
            if (-not $Id) { Write-Result -Status error -Error '需要 -Id' }
            $item = Get-ShellIcons | Where-Object id -eq $Id
            if (-not $item) { Write-Result -Status error -Error '条目不在当前扫描结果内' }
            if ($item.system) { Write-Result -Status error -Error '系统内置文件夹，禁止删除' }
            $regKey = ConvertTo-RegKeyPath -PsPath $item.key
            $bak = Join-Path (Get-CtxBackupDir) "icon_$($item.guid -replace '[^\w.-]', '_')_$(Get-Date -Format yyyyMMddHHmmss).reg"
            reg export $regKey $bak /y | Out-Null
            Remove-Item -LiteralPath $item.key -Recurse -Force -ErrorAction Stop
            Write-AuditLog -Action 'ctxmenu-icon' -Items @($item.key) -Extra @{ backup = $bak }
            Write-Result -Status ok -Data @{ id = $Id; deleted = $true; backup = $bak }
        }
        'classic' {
            if ($Enabled) {
                # 恢复经典完整菜单：建 CLSID\InprocServer32 默认空值（仅当前用户，无需管理员）
                $inproc = Join-Path $ClassicKey 'InprocServer32'
                if (-not (Test-Path -LiteralPath $ClassicKey)) { New-Item -Path $ClassicKey -Force | Out-Null }
                if (-not (Test-Path -LiteralPath $inproc)) { New-Item -Path $inproc -Force | Out-Null }
                New-ItemProperty -LiteralPath $inproc -Name '(default)' -Value '' -PropertyType String -Force | Out-Null
                Write-Result -Status ok -Data @{ classic = $true; note = '已恢复经典菜单；重启资源管理器（restart-explorer）或注销后生效' }
            } else {
                Remove-Item -LiteralPath $ClassicKey -Recurse -Force -ErrorAction SilentlyContinue
                Write-Result -Status ok -Data @{ classic = $false; note = '已切回 Win11 新菜单；重启资源管理器后生效' }
            }
        }
        'restart-explorer' {
            Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            if (-not (Get-Process -Name explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
            Write-Result -Status ok -Data @{ restarted = $true; note = '已重启资源管理器（任务栏短暂消失后自动恢复）' }
        }
        default {
            Write-Result -Status error -Error "未知动作：$Action（可用: list/disable/enable/delete/icons/icons-delete/classic/restart-explorer）"
        }
    }
} catch {
    Write-Result -Status error -Error "操作失败（可能需要管理员）：$($_.Exception.Message)"
}
