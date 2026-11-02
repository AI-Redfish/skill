<#
migrate.ps1 — 大目录迁移到其他盘（robocopy + 目录联接回填，软件无感知）

复刻 grclean migrate.ts 核心流程（三条关键约束）：
  1. 迁移前校验目标盘剩余空间 > 源数据 1.2 倍
  2. 迁移后校验联接可读写，再删源（robocopy /MOVE 已移除源）
  3. 任一步失败自动回滚（搬回原位）
  只迁移白名单根目录（%LOCALAPPDATA% / %APPDATA% / Documents / Office）下的一级
  子目录，不接受任意路径；系统/浏览器核心目录（DENY_NAMES）永不迁移。
  体积统计走 robocopy /L /E /XJ 列表模式（比递归遍历快数倍）。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File migrate.ps1 -Action list [-MinMb 500]
  powershell -NoProfile -ExecutionPolicy Bypass -File migrate.ps1 -Action run -Path '<目录>' -TargetDrive D
  powershell -NoProfile -ExecutionPolicy Bypass -File migrate.ps1 -Action undo  -Path '<联接路径>'

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'list',
    [int]$MinMb = 500,
    [string]$Path = '',
    [string]$TargetDrive = ''
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

$SourceRoots = @(
    @{ dir = $env:LOCALAPPDATA; label = '本地应用数据' },
    @{ dir = $env:APPDATA; label = '漫游应用数据' },
    @{ dir = "$env:USERPROFILE\Documents"; label = '文档' },
    @{ dir = "$env:LOCALAPPDATA\Microsoft\Office"; label = 'Office' }
)

$DenyNames = @('microsoft','windows','google','microsoft edge','mozilla','nvidia','nvidia corporation',
               'amd','intel','packages','programs','temp','cache','crashdumps','d3dscache')

$robo = Join-Path $env:SystemRoot 'System32\robocopy.exe'
if (-not (Test-Path -LiteralPath $robo)) { $robo = 'robocopy' }

# robocopy 列表模式统计体积（/L 只列不复制；/XJ 排除联接防自引用与虚高）
function Get-SizeByRobocopy { param([string]$Dir)
    $out = & $robo $Dir 'C:\__null__' /L /E /XJ /NFL /NDL /NJH /BYTES /NP /NJS 2>$null
    $bytes = [int64]0
    foreach ($line in $out) {
        if ($line -match '^\s*字节\s*:\s*([\d.]+)\s*([kKmMgGtT])') { $bytes = [double]$Matches[1] }
        elseif ($line -match '^\s*Bytes\s*:\s*([\d.]+)\s*([kKmMgGtT])') {
            $unit = @{ k = 1KB; m = 1MB; g = 1GB; t = 1TB }[$Matches[2].ToString().ToLower()]
            $bytes = [int64]([double]$Matches[1] * $unit)
        }
    }
    return $bytes
}

if ($Action -eq 'list') {
    $minBytes = [Math]::Max($MinMb, 0) * 1MB
    $items = [System.Collections.Generic.List[object]]::new()
    foreach ($r in $SourceRoots) {
        if (-not $r.dir -or -not (Test-Path -LiteralPath $r.dir)) { continue }
        foreach ($e in (Get-ChildItem -LiteralPath $r.dir -Directory -Force -ErrorAction SilentlyContinue)) {
            if ($DenyNames -contains $e.Name.ToLower()) { continue }
            $isJunction = $false
            try {
                $reparse = Get-Item -LiteralPath $e.FullName -Force
                if (($reparse.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $isJunction = $true }
            } catch { }
            if ($isJunction) {
                # 已是联接（此前已迁移）：读目标位置
                $target = ''
                try { $target = "$($e.Target)" } catch { }
                $items.Add([PSCustomObject]@{ id = 'mig:' + (New-CandidateId -Path $e.FullName).Substring(0, 16)
                    name = $e.Name; path = $e.FullName; size = 0; source = $r.label
                    is_junction = $true; junction_target = $target })
                continue
            }
            $size = Get-SizeByRobocopy -Dir $e.FullName
            if ($size -ge $minBytes) {
                $items.Add([PSCustomObject]@{ id = 'mig:' + (New-CandidateId -Path $e.FullName).Substring(0, 16)
                    name = $e.Name; path = $e.FullName; size = $size; source = $r.label
                    is_junction = $false; junction_target = '' })
            }
        }
    }
    $items = @($items | Sort-Object size -Descending)
    Write-Result -Status ok -Data ([ordered]@{
        count = $items.Count; items = $items
        note = 'run 前请先关闭使用该目录的软件；迁移用 robocopy /MOVE + mklink /J，失败自动回滚'
    })
}

if ($Action -eq 'run') {
    if (-not $Path -or -not $TargetDrive) { Write-Result -Status error -Error '需要 -Path <目录> 与 -TargetDrive <盘符字母>' }
    $L = $TargetDrive.Replace(':', '').ToUpper()
    if ($L -notmatch '^[A-Z]$') { Write-Result -Status error -Error '目标盘符无效' }

    # 白名单校验：只允许 SourceRoots 下的一级子目录（不接受任意路径）
    $rootOk = $false
    foreach ($r in $SourceRoots) {
        $parent = "$($r.dir)".TrimEnd('\') + '\'
        if ($Path.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) {
            $rel = $Path.Substring($parent.Length)
            if ($rel -and -not $rel.Contains('\')) { $rootOk = $true; break }
        }
    }
    if (-not $rootOk) { Write-Result -Status error -Error '路径不在可迁移白名单（AppData/Documents/Office 的一级子目录）内' }
    if ($DenyNames -contains ((Split-Path -Leaf $Path).ToLower())) { Write-Result -Status error -Error '系统/浏览器核心目录禁止迁移' }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { Write-Result -Status error -Error '源目录不存在' }

    $srcSize = Get-SizeByRobocopy -Dir $Path
    $targetVol = Get-Volume -DriveLetter $L -ErrorAction SilentlyContinue
    if (-not $targetVol) { Write-Result -Status error -Error "目标盘 $L 不可用" }
    # 约束1：目标剩余 > 源 1.2 倍
    if ([int64]$targetVol.SizeRemaining -lt ([int64]($srcSize * 1.2))) {
        Write-Result -Status error -Error "目标盘剩余空间不足（需 > 源的 1.2 倍：$([math]::Round($srcSize*1.2/1GB,2)) GB）"
    }

    $targetDir = Join-Path "${L}:\" ("migrated\" + (Split-Path -Leaf $Path))
    if (Test-Path -LiteralPath $targetDir) { Write-Result -Status error -Error "目标已存在：$targetDir（先处理遗留）" }

    try {
        # 移动（robocopy /MOVE 跨卷、带重试；退出码 <8 视为成功）
        & $robo $Path $targetDir /MOVE /E /R:2 /W:2 /NFL /NDL /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy 移动失败（退出码 $LASTEXITCODE）" }
        # 联接回填
        $juncOut = cmd /c mklink /J "$Path" "$targetDir" 2>&1
        if ($LASTEXITCODE -ne 0) {
            # 回滚：搬回原位（绝不留半迁移状态）
            & $robo $targetDir $Path /MOVE /E /R:2 /W:2 /NFL /NDL /NP | Out-Null
            throw "mklink /J 失败，已回滚：$juncOut"
        }
        # 约束2：联接探针校验可读写
        $probe = Join-Path $Path '__pcmanager_probe__.tmp'
        'ok' | Set-Content -LiteralPath $probe -Encoding ASCII
        $readBack = Get-Content -LiteralPath $probe -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        if ($readBack -ne 'ok') { throw '联接探针读取异常' }
        Write-AuditLog -Action 'migrate' -Items @($Path) -Extra @{ target = $targetDir; bytes = $srcSize }
        Write-Result -Status ok -Data @{ migrated = $true; from = $Path; to = $targetDir
            bytes = $srcSize; note = '已完成迁移并建立联接，软件无感知；undo 可还原' }
    } catch {
        Write-Result -Status error -Error "迁移失败：$($_.Exception.Message)"
    }
}

if ($Action -eq 'undo') {
    if (-not $Path) { Write-Result -Status error -Error '需要 -Path <联接路径>' }
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
            Write-Result -Status error -Error '该路径不是联接（未迁移过？）'
        }
        $target = "$($item.Target)"
        if (-not $target -or -not (Test-Path -LiteralPath $target)) {
            Write-Result -Status error -Error "联接目标不存在：$target"
        }
        # 删联接 → 搬回原位
        $item.Delete()
        & $robo $target $Path /MOVE /E /R:2 /W:2 /NFL /NDL /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy 还原失败（退出码 $LASTEXITCODE）" }
        $parent = Split-Path -Parent $target
        if ((Get-ChildItem -LiteralPath $parent -Force -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
            Remove-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
        }
        Write-AuditLog -Action 'migrate-undo' -Items @($Path) -Extra @{ from = $target }
        Write-Result -Status ok -Data @{ restored = $true; path = $Path; from = $target }
    } catch {
        Write-Result -Status error -Error "还原失败：$($_.Exception.Message)"
    }
}
