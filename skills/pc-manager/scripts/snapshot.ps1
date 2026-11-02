<#
snapshot.ps1 — 磁盘空间快照与对比（回答「这段时间是谁吃掉了我的空间」）

复刻 grclean snapshot.ts。设计：
  快照存 %LOCALAPPDATA%\pc-manager\snapshots\*.json；只记体积数字与相对路径；
  内容 = 各盘容量/剩余 + 系统盘顶层目录（深度1）体积；对比给「各盘增减 + 膨胀目录 Top」。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File snapshot.ps1 -Action take
  powershell -NoProfile -ExecutionPolicy Bypass -File snapshot.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File snapshot.ps1 -Action diff -BaseId <id> -TargetId <id>
  powershell -NoProfile -ExecutionPolicy Bypass -File snapshot.ps1 -Action delete -SnapshotId <id>

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'take',
    [string]$BaseId = '',
    [string]$TargetId = '',
    [string]$SnapshotId = ''
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

function Get-SnapshotDir {
    $dir = Join-Path (Get-PcManagerDir) 'snapshots'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

if ($Action -eq 'take') {
    $sysRoot = "$((Get-SystemDriveLetter)):\"
    $volumes = [System.Collections.Generic.List[object]]::new()
    foreach ($v in (Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' })) {
        $volumes.Add([PSCustomObject]@{
            letter = "$($v.DriveLetter)".ToUpper()
            total_bytes = [int64]$v.Size; free_bytes = [int64]$v.SizeRemaining
        })
    }
    # 系统盘顶层目录体积（深度 1）
    $dirs = [System.Collections.Generic.List[object]]::new()
    foreach ($e in (Get-ChildItem -LiteralPath $sysRoot -Directory -Force -ErrorAction SilentlyContinue)) {
        $dirs.Add([PSCustomObject]@{ path = $e.Name; bytes = Get-DirSize -Path $e.FullName -MaxFiles 40000 })
    }
    $dirs = @($dirs | Sort-Object bytes -Descending)
    $now = Get-Date
    $id = $now.ToString('yyyy-MM-ddTHH-mm-ss')
    $snap = [PSCustomObject]@{
        id = $id; ts = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
        time = $now.ToString('yyyy-MM-dd HH:mm:ss')
        volumes = $volumes; dirs = $dirs
    }
    $file = Join-Path (Get-SnapshotDir) "$id.json"
    $snap | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $file -Encoding UTF8
    Write-Result -Status ok -Data @{ id = $id; file = $file; volumes = $volumes.Count; top_dirs = $dirs }
}

if ($Action -eq 'list') {
    $list = @(Get-ChildItem -LiteralPath (Get-SnapshotDir) -Filter *.json -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $s = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                [PSCustomObject]@{ id = $s.id; time = $s.time; ts = $s.ts; file = $_.FullName }
            } catch { }
        } | Sort-Object ts -Descending)
    Write-Result -Status ok -Data @{ snapshots = $list }
}

if ($Action -eq 'diff') {
    if (-not $BaseId -or -not $TargetId) { Write-Result -Status error -Error '需要 -BaseId 与 -TargetId（list 取，Base 较早）' }
    $all = @(Get-ChildItem -LiteralPath (Get-SnapshotDir) -Filter *.json | ForEach-Object {
        try { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    })
    $base = $all | Where-Object id -eq $BaseId | Select-Object -First 1
    $target = $all | Where-Object id -eq $TargetId | Select-Object -First 1
    if (-not $base -or -not $target) { Write-Result -Status error -Error '快照 id 不存在' }

    $vols = [System.Collections.Generic.List[object]]::new()
    $letters = @($base.volumes.letter) + @($target.volumes.letter) | Select-Object -Unique
    foreach ($l in $letters) {
        $b = $base.volumes | Where-Object letter -eq $l | Select-Object -First 1
        $t = $target.volumes | Where-Object letter -eq $l | Select-Object -First 1
        if (-not $b -or -not $t) { continue }
        $vols.Add([PSCustomObject]@{
            letter = $l
            used_before = ($b.total_bytes - $b.free_bytes); used_after = ($t.total_bytes - $t.free_bytes)
            delta = (($t.total_bytes - $t.free_bytes) - ($b.total_bytes - $b.free_bytes))
        })
    }
    $vols = @($vols | Sort-Object delta -Descending)

    $beforeMap = @{}
    foreach ($d in $base.dirs) { $beforeMap[$d.path] = $d.bytes }
    $dirs = [System.Collections.Generic.List[object]]::new()
    foreach ($d in $target.dirs) {
        $before = 0; $isNew = $true
        if ($beforeMap.ContainsKey($d.path)) { $before = $beforeMap[$d.path]; $isNew = $false }
        $dirs.Add([PSCustomObject]@{ path = $d.path; before = $before; after = $d.bytes; delta = ($d.bytes - $before); is_new = $isNew })
    }
    $dirs = @($dirs | Sort-Object delta -Descending)
    $days = [math]::Max(0, [math]::Round(($target.ts - $base.ts) / 86400000))

    Write-Result -Status ok -Data ([ordered]@{
        base = $base.id; target = $target.id; days = $days
        volumes = $vols; dirs = $dirs
        total_delta = (($dirs | Measure-Object -Property delta -Sum).Sum)
    })
}

if ($Action -eq 'delete') {
    if (-not $SnapshotId) { Write-Result -Status error -Error '需要 -SnapshotId' }
    $safe = $SnapshotId -replace '[^A-Za-z0-9._-]', ''
    $file = Join-Path (Get-SnapshotDir) "$safe.json"
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force; Write-Result -Status ok -Data @{ deleted = $true; id = $safe } }
    else { Write-Result -Status error -Error '快照不存在' }
}
