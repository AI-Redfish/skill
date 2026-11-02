<#
dup.ps1 — 重复文件查找（三级筛选：大小 → 头尾哈希 → 全量 SHA-256）

复刻 grclean dup.ts。判定链与忽略清单一致：
  1) 按文件大小分组（同大小 ≥2 才继续）
  2) 头 4KB + 尾 4KB 做 SHA-256 预筛（快速排除大小相同内容不同）
  3) 全量 SHA-256 确认（重复判定最终依据）；浪费空间 = size × (count-1)
  忽略: 系统目录 / 回收站 / node_modules / .git / .svn / AppData（扫描既慢又无意义）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File dup.ps1 -MinMb 10 [-Scope user|all|drive:C]
  （删除重复项请把 dup.ps1 的 group 结果交给 files 通用删除：AI 引导用户确认后逐文件处理，
   或用 recycle.ps1 的 -Recycle 参数移入回收站）

退出码: 0=ok 1=error。stdout 只输出 JSON 信封（含重复组明细）。
#>
[CmdletBinding()]
param(
    [int]$MinMb = 10,
    [ValidateSet('user', 'all')][string]$Scope = 'user',   # user=用户数据目录; all=全部盘
    [string]$Drive = '',                                    # 如 'D'：仅扫该盘（优先于 Scope）
    [int]$MaxPerGroup = 0                                   # 0=不限制每组输出文件数
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$HeaderBytes = 4096
$TailBytes = 4096

$TopSkip = @('$recycle.bin','system volume information','windows','winxs','program files',
             'program files (x86)','programdata','recovery','$winreagent','node_modules','.git','.svn','appdata')

function Get-ScanRoots {
    if ($Drive) { return @("$($Drive.ToUpper()):\") }
    if ($Scope -eq 'all') { return @((Get-DriveLetters) | ForEach-Object { "$_`:\" }) }
    # 用户数据目录（英文+中文名适配，对应 bigfile.ts USER_FOLDER_CANDIDATES）
    $base = $env:USERPROFILE
    $out = @()
    foreach ($pair in @(@('Desktop','桌面'),@('Documents','文档'),@('Downloads','下载'),
                        @('Pictures','图片'),@('Videos','视频'),@('Music','音乐'))) {
        foreach ($n in $pair) {
            $p = Join-Path $base $n
            if (Test-Path -LiteralPath $p) { $out += $p; break }
        }
    }
    return $out
}

function Get-HeaderHash {
    param([string]$Path)
    try {
        $fs = [System.IO.File]::OpenRead($Path)
        try {
            $total = $fs.Length
            $buf = [System.Byte[]]::new(0)
            $headLen = [int][math]::Min($HeaderBytes, $total)
            if ($headLen -gt 0) {
                $head = [System.Byte[]]::new($headLen)
                [void]$fs.Read($head, 0, $headLen)
                $buf = $head
            }
            if ($total -gt ($HeaderBytes + $TailBytes)) {
                $tail = [System.Byte[]]::new($TailBytes)
                [void]$fs.Seek(-$TailBytes, [System.IO.SeekOrigin]::End)
                [void]$fs.Read($tail, 0, $TailBytes)
                $buf = $buf + $tail
            }
            $sha = [System.Security.Cryptography.SHA256]::Create()
            try { return ($sha.ComputeHash($buf) | ForEach-Object { $_.ToString('x2') }) -join '' }
            finally { $sha.Dispose() }
        } finally { $fs.Dispose() }
    } catch { return $null }
}

function Get-FullHash {
    param([string]$Path)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $fs = [System.IO.File]::OpenRead($Path)
        try { return ($sha.ComputeHash($fs) | ForEach-Object { $_.ToString('x2') }) -join '' }
        finally { $fs.Dispose(); $sha.Dispose() }
    } catch { return $null }
}

# ---------- 主流程 ----------
$minBytes = [Math]::Max($MinMb, 0) * 1MB
$roots = Get-ScanRoots
Write-Log "扫描根: $($roots -join ', ')（最小 $MinMb MB）"

# 1) 收集文件（顶层跳过系统/缓存目录；深度 ≤16）
$files = [System.Collections.Generic.List[object]]::new()
$scanned = 0
foreach ($root in $roots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $top = Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue
    $subdirs = [System.Collections.Generic.List[string]]::new()
    foreach ($e in $top) {
        if ($e.PSIsContainer) {
            if ($TopSkip -notcontains $e.Name.ToLower()) { $subdirs.Add($e.FullName) }
        } elseif ($e.Length -ge $minBytes -and $e.Length -gt 0) {
            $files.Add([PSCustomObject]@{ path = $e.FullName; size = $e.Length }); $scanned++
        }
    }
    foreach ($sub in $subdirs) {
        foreach ($f in (Get-ChildItem -LiteralPath $sub -Recurse -File -Force -ErrorAction SilentlyContinue |
                        Where-Object { $_.FullName -notmatch '\\(node_modules|\.git|\.svn|\$Recycle\.Bin|System Volume Information|Windows|WinSxS|ProgramData|Program Files( \(x86\))?|AppData)\\' })) {
            $scanned++
            if ($f.Length -ge $minBytes -and $f.Length -gt 0) {
                $files.Add([PSCustomObject]@{ path = $f.FullName; size = $f.Length })
            }
        }
    }
}
Write-Log "收集完成：$($files.Count) 个 ≥${MinMb}MB 文件（共扫描 $scanned）"

# 2) 按大小分组（≥2 继续）
$bySize = @{}
foreach ($f in $files) {
    if (-not $bySize.ContainsKey($f.size)) { $bySize[$f.size] = [System.Collections.Generic.List[object]]::new() }
    $bySize[$f.size].Add($f)
}
$sizeGroups = @($bySize.Values | Where-Object { $_.Count -ge 2 })
Write-Log "大小分组：$($sizeGroups.Count) 组候选"

# 3) 头尾哈希预筛
$byHeader = @{}
$n = 0
foreach ($g in $sizeGroups) {
    foreach ($f in $g) {
        $n++
        if ($n % 50 -eq 0) { Write-Log "头尾哈希预筛 $n" }
        $h = Get-HeaderHash -Path $f.path
        if (-not $h) { continue }
        $key = "$($f.size):$h"
        if (-not $byHeader.ContainsKey($key)) { $byHeader[$key] = [System.Collections.Generic.List[object]]::new() }
        $byHeader[$key].Add($f)
    }
}
$headerGroups = @($byHeader.Values | Where-Object { $_.Count -ge 2 })
Write-Log "头尾哈希后：$($headerGroups.Count) 组候选"

# 4) 全量 SHA-256 确认
$byFull = @{}
$n = 0
foreach ($g in $headerGroups) {
    foreach ($f in $g) {
        $n++
        if ($n % 20 -eq 0) { Write-Log "全量哈希 $n" }
        $h = Get-FullHash -Path $f.path
        if (-not $h) { continue }
        if (-not $byFull.ContainsKey($h)) { $byFull[$h] = [System.Collections.Generic.List[object]]::new() }
        $byFull[$h].Add($f)
    }
}

# 5) 构建重复组（wasted = size × (count-1)，对应 dup.ts）
$groups = [System.Collections.Generic.List[object]]::new()
foreach ($hash in $byFull.Keys) {
    $g = $byFull[$hash]
    if ($g.Count -lt 2) { continue }
    $members = @($g | ForEach-Object {
        $m = [PSCustomObject]@{ id = New-CandidateId -Path $_.path; path = $_.path; size = $_.size; mtime = $_.path }
        $fi = Get-Item -LiteralPath $_.path -ErrorAction SilentlyContinue
        if ($fi) { $m.mtime = $fi.LastWriteTime.ToString('yyyy-MM-dd HH:mm') }
        $m
    } | Sort-Object mtime)   # 最旧在前：通常保留最新、清最旧副本
    if ($MaxPerGroup -gt 0 -and $members.Count -gt $MaxPerGroup) { $members = $members[0..($MaxPerGroup-1)] }
    $groups.Add([PSCustomObject]@{
        group_id = $hash.Substring(0, 16); hash = $hash
        size = $g[0].size; count = $g.Count
        wasted = [int64]($g[0].size * ($g.Count - 1))
        files = $members
    })
}
$groups = @($groups | Sort-Object wasted -Descending)

$totalWasted = ($groups | Measure-Object -Property wasted -Sum).Sum
if ($null -eq $totalWasted) { $totalWasted = 0 }
$sessionFile = Save-Session -Name 'dup' -Candidates ($groups | ForEach-Object { $_.files })
Write-Result -Status ok -Data ([ordered]@{
    scanned = $scanned; group_count = $groups.Count
    wasted_bytes = [int64]$totalWasted; session = $sessionFile; groups = $groups
})
