<#
slim.ps1 — C 盘瘦身向导（只统计体积出方案；执行按项白名单操作固定路径）

复刻 grclean slim.ts。方案项（风险分级，danger 需 -Force）：
  hibernation   关闭休眠删除 hiberfil.sys（powercfg -h off，可逆 powercfg -h on）  safe
  windows_old   删除 Windows.old（不可逆，需管理员，Takeown+icacls 后删）           danger
  update_cache  清空 SoftwareDistribution\Download（需管理员）                      safe
  delivery_opt  清空 SoftwareDistribution\DeliveryOptimization（需管理员）          safe
  temp_install  清空 %WINDIR%\Temp 过期内容（需管理员）                             safe
  social/bigfiles 仅预估体积并提示跳转 social.ps1 / bigfile.ps1 处理（不越权删除）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File slim.ps1 -Action plan
  powershell -NoProfile -ExecutionPolicy Bypass -File slim.ps1 -Action run -Kinds hibernation,update_cache [-Force]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('plan', 'run')][string]$Action = 'plan',
    [string]$Kinds = '',
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$sysDrive = (Get-SystemDriveLetter) + ':'
$winDir = $env:WINDIR
if (-not $winDir) { $winDir = Join-Path $sysDrive 'Windows' }

function Test-PathSafe { param([string]$P) try { return (Test-Path -LiteralPath $P) } catch { return $false } }

if ($Action -eq 'plan') {
    $items = [System.Collections.Generic.List[object]]::new()

    # 1. 休眠文件（与内存等量，常 8-16GB）
    $hiber = 0
    $hiberFile = Join-Path $sysDrive 'hiberfil.sys'
    if (Test-PathSafe $hiberFile) { $hiber = (Get-Item -LiteralPath $hiberFile -Force -ErrorAction SilentlyContinue).Length }
    if ($hiber -gt 0) {
        $items.Add([PSCustomObject]@{ kind='hibernation'; name='休眠文件 hiberfil.sys'; size=$hiber
            risk='safe'; recommend=$true; actionable=$true
            desc='关闭休眠立即释放与内存等量空间；powercfg -h on 可随时恢复（可逆）' })
    }

    # 2. Windows.old（不可逆）
    $winOld = Join-Path $sysDrive 'Windows.old'
    if (Test-PathSafe $winOld) {
        $items.Add([PSCustomObject]@{ kind='windows_old'; name='旧系统 Windows.old'; size=(Get-DirSize $winOld)
            risk='danger'; recommend=$false; actionable=$true
            desc='升级留下的旧系统，删除后无法回退上一版本（不可逆，需管理员）' })
    }

    # 3-5. 更新缓存 / 传递优化 / Temp（只清内容保留目录本身）
    foreach ($t in @(
        @{ kind='update_cache';  dir = (Join-Path $winDir 'SoftwareDistribution\Download');            name='Windows 更新缓存' },
        @{ kind='delivery_opt';  dir = (Join-Path $winDir 'SoftwareDistribution\DeliveryOptimization'); name='传递优化缓存' },
        @{ kind='temp_install';  dir = (Join-Path $winDir 'Temp');                                       name='Windows 临时安装文件' }
    )) {
        if (Test-PathSafe $t.dir) {
            $sz = Get-DirSize -Path $t.dir -MaxFiles 40000
            if ($sz -gt 0) {
                $items.Add([PSCustomObject]@{ kind=$t.kind; name=$t.name; size=$sz
                    risk='safe'; recommend=$true; actionable=$true; desc='清理后系统按需重建（需管理员）' })
            }
        }
    }

    # 6-7. 社交缓存 / 大文件：只预估（跳转对应模块处理，避免越权）
    try {
        $tempTotal = Get-DirSize -Path $env:TEMP -MaxFiles 20000
        if ($tempTotal -gt 100MB) {
            $items.Add([PSCustomObject]@{ kind='user_temp'; name='用户临时目录'; size=$tempTotal
                risk='safe'; recommend=$true; actionable=$false; goto='junk.ps1'
                desc='由 junk.ps1 按规则（保留最近7天）处理' })
        }
    } catch { }

    $items = @($items | Sort-Object size -Descending)
    $total = ($items | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    Write-Result -Status ok -Data ([ordered]@{
        items = $items; total_bytes = [int64]$total
        safe_bytes = [int64](($items | Where-Object risk -eq 'safe' | Measure-Object -Property size -Sum).Sum)
        note = 'run 时 danger 项（windows_old）需加 -Force；系统目录项需管理员运行'
    })
}

if ($Action -eq 'run') {
    if (-not $Kinds) { Write-Result -Status error -Error '需要 -Kinds kind1,kind2（从 plan 结果取）' }
    $kindList = $Kinds -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }

    if (($kindList -contains 'windows_old') -and -not $Force) {
        Write-Result -Status error -Error 'windows_old 为不可逆操作，需加 -Force 显式确认'
    }

    $results = [System.Collections.Generic.List[object]]::new()
    foreach ($kind in $kindList) {
        try {
            switch ($kind) {
                'hibernation' {
                    powercfg -h off 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) { $results.Add([PSCustomObject]@{ kind=$kind; ok=$true; message='已关闭休眠并删除 hiberfil.sys' }) }
                    else { $results.Add([PSCustomObject]@{ kind=$kind; ok=$false; message='powercfg 失败（需管理员）' }) }
                }
                'windows_old' {
                    $p = Join-Path $sysDrive 'Windows.old'
                    if (-not (Test-PathSafe $p)) { $results.Add([PSCustomObject]@{ kind=$kind; ok=$true; message='Windows.old 不存在，无需处理' }); break }
                    $q = ConvertTo-PsQuote $p
                    takeown /F $p /R /A /D Y 2>&1 | Out-Null
                    icacls $p /grant '*S-1-5-32-544:(OI)(CI)F' /T /Q 2>&1 | Out-Null
                    Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
                    Write-AuditLog -Action 'slim' -Items @($p) -Extra @{ kind = $kind }
                    $results.Add([PSCustomObject]@{ kind=$kind; ok=$true; message='已删除 Windows.old' })
                }
                { $_ -in 'update_cache', 'delivery_opt', 'temp_install' } {
                    $dirMap = @{
                        update_cache = Join-Path $winDir 'SoftwareDistribution\Download'
                        delivery_opt = Join-Path $winDir 'SoftwareDistribution\DeliveryOptimization'
                        temp_install = Join-Path $winDir 'Temp'
                    }
                    $d = $dirMap[$kind]
                    if (-not (Test-PathSafe $d)) { $results.Add([PSCustomObject]@{ kind=$kind; ok=$true; message='目录不存在，无需处理' }); break }
                    # 只清目录内容，保留目录本身（避免破坏系统目录结构）
                    Get-ChildItem -LiteralPath $d -Force -ErrorAction SilentlyContinue |
                        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
                    $left = 0
                    if (Test-PathSafe $d) { $left = Get-DirSize $d }
                    Write-AuditLog -Action 'slim' -Items @($d) -Extra @{ kind = $kind }
                    $msg = '已清理'
                    if ($left -gt 0) { $msg += "（仍有 $([math]::Round($left/1GB,2)) GB 被系统占用，属正常）" }
                    $results.Add([PSCustomObject]@{ kind=$kind; ok=$true; message=$msg })
                }
                default {
                    $results.Add([PSCustomObject]@{ kind=$kind; ok=$false; message='未知或不可直接执行的项（social/bigfiles 请用对应脚本）' })
                }
            }
        } catch {
            $results.Add([PSCustomObject]@{ kind=$kind; ok=$false; message=$_.Exception.Message })
        }
    }
    Write-Result -Status ok -Data @{ results = $results }
}
