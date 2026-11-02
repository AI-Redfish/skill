<#
bigfile.ps1 — 大文件分析（找出磁盘上最大的文件，仅分析不删除）

复刻 grclean bigfile.ts：用户数据目录（中英文目录名适配）或全盘/指定盘扫描，
按体积降序列出 ≥ MinMb 的大文件；深度限制 8 防止陷入深层系统目录。
删除动作由 AI 引导用户确认后用 recycle.ps1 移入回收站（复用保护防线）。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File bigfile.ps1 -MinMb 200 [-Scope user|all] [-Drive D] [-Top 100]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [int]$MinMb = 200,
    [ValidateSet('user', 'all')][string]$Scope = 'user',
    [string]$Drive = '',
    [int]$Top = 200,
    [int]$Depth = 8
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$minBytes = [Math]::Max($MinMb, 0) * 1MB

# 扫描根（对应 bigfile.ts roots 决策）
$roots = @()
if ($Drive) {
    $roots = @("$($Drive.ToUpper()):\")
} elseif ($Scope -eq 'all') {
    $roots = @(Get-DriveLetters) | ForEach-Object { "$_`:\" }
} else {
    foreach ($pair in @(@('Desktop','桌面'),@('Documents','文档'),@('Downloads','下载'),
                        @('Pictures','图片'),@('Videos','视频'),@('Music','音乐'))) {
        foreach ($n in $pair) {
            $p = Join-Path $env:USERPROFILE $n
            if (Test-Path -LiteralPath $p) { $roots += $p; break }
        }
    }
}

Write-Log "扫描根: $($roots -join ', ')（≥ ${MinMb}MB，深度 $Depth）"
$files = [System.Collections.Generic.List[object]]::new()
$scanned = 0

foreach ($root in $roots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    # Get-ChildItem -Depth 限制递归深度（PS5 支持）
    foreach ($f in (Get-ChildItem -LiteralPath $root -Recurse -File -Force -Depth $Depth -ErrorAction SilentlyContinue)) {
        $scanned++
        if (($scanned % 2000) -eq 0) { Write-Log "已扫描 $scanned" }
        if ($f.Length -lt $minBytes) { continue }
        $files.Add([PSCustomObject]@{
            id = New-CandidateId -Path $f.FullName
            path = $f.FullName; size = $f.Length
            mtime = $f.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
        })
    }
}

$files = @($files | Sort-Object size -Descending | Select-Object -First $Top)
$total = ($files | Measure-Object -Property size -Sum).Sum
if ($null -eq $total) { $total = 0 }
$sessionFile = Save-Session -Name 'bigfile' -Candidates $files
Write-Result -Status ok -Data ([ordered]@{
    scanned = $scanned; count = $files.Count; total_bytes = [int64]$total
    session = $sessionFile; files = $files
})
