<#
health.ps1 — 一键体检（编排各扫描能力 + 11 因素加权评分）

复刻 grclean health.ts / score.ts。11 因素权重（合计 100）：
  系统盘剩余空间28 容量5 垃圾12 重复8 社交缓存8 注册表4 启动项7
  磁盘健康(Trim/SMART)11 文件系统4K对齐7 更新积压5 可释放系统文件5
等级：≥85优秀 ≥70良好 ≥50一般 ≥30较差 <30危险。
体检为只读编排（不删除任何东西）；子扫描采用「快速口径」避免全盘哈希拖死体检。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File health.ps1 [-Quick]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封（factors + suggestions + stats）。
#>
[CmdletBinding()]
param([switch]$Quick)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

$GB = 1GB

# ---------- 线性插值评分函数（对应 score.ts largerBetter/smallerBetter） ----------
function Get-LargerScore { param([double]$V, [double]$FullAt, [double]$ZeroAt, [int]$Max)
    if ($V -ge $FullAt) { return $Max }
    if ($V -le $ZeroAt) { return 0 }
    return [int][math]::Round($Max * ($V - $ZeroAt) / ($FullAt - $ZeroAt))
}
function Get-SmallerScore { param([double]$V, [double]$FullAt, [double]$ZeroAt, [int]$Max)
    if ($V -le $FullAt) { return $Max }
    if ($V -ge $ZeroAt) { return 0 }
    return [int][math]::Round($Max * ($ZeroAt - $V) / ($ZeroAt - $FullAt))
}

# ---------- 采集 ----------
# 1) 系统盘
$sysLetter = Get-SystemDriveLetter
$vol = Get-Volume -DriveLetter $sysLetter -ErrorAction SilentlyContinue
$part = $vol | Get-Partition -ErrorAction SilentlyContinue | Select-Object -First 1
$disk = $part | Get-Disk -ErrorAction SilentlyContinue
$freeBytes = [int64]0; $totalBytes = [int64]0
if ($vol) { $freeBytes = [int64]$vol.SizeRemaining; $totalBytes = [int64]$vol.Size }
$media = 'Unknown'; if ($disk) { $media = "$($disk.MediaType)" }
$smartOk = $null; if ($disk) { $smartOk = ("$($disk.HealthStatus)" -eq 'Healthy') }
$trimEnabled = $null
try { $t = ((fsutil behavior query DisableDeleteNotify) -replace '[^0-9]', ''); if ($t) { $trimEnabled = ($t -eq '0') } } catch { }

# 2) 垃圾体积（快速口径：%TEMP% + SoftwareDistribution\Download + WER；不动全盘）
$junkBytes = [int64]0
foreach ($p in @($env:TEMP, (Join-Path $env:WINDIR 'SoftwareDistribution\Download'),
                (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER'))) {
    if ($p -and (Test-Path -LiteralPath $p)) { $junkBytes += Get-DirSize -Path $p -MaxFiles 15000 }
}
# 更新积压口径
$updateBacklog = [int64]0
$sdDownload = Join-Path $env:WINDIR 'SoftwareDistribution\Download'
if (Test-Path -LiteralPath $sdDownload) { $updateBacklog = Get-DirSize -Path $sdDownload -MaxFiles 15000 }

# 3) 社交缓存体积（复用 social.ps1 的定位逻辑，best-effort）
$socialBytes = [int64]0
try {
    $socialJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'social.ps1') -Action scan 2>$null |
        Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if ($socialJson) {
        $sj = $socialJson | ConvertFrom-Json
        if ($sj.status -eq 'ok') { $socialBytes = [int64]$sj.data.cleanable_bytes }
    }
} catch { Write-Log "社交缓存统计失败（按 0 计）：$($_.Exception.Message)" }

# 4) 注册表冗余数（快速：仅 Run 失效项 + SharedDLLs 抽样，避免体检拖慢）
$registryCount = 0
try {
    $regJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'registry.ps1') -Action scan 2>$null |
        Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if ($regJson) {
        $rj = $regJson | ConvertFrom-Json
        if ($rj.status -eq 'ok') { $registryCount = [int]$rj.data.count }
    }
} catch { Write-Log "注册表扫描失败（按 0 计）" }

# 5) 启动项数
$startupCount = 0
try {
    $stJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'startup.ps1') -Action list 2>$null |
        Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if ($stJson) {
        $tj = $stJson | ConvertFrom-Json
        if ($tj.status -eq 'ok') { $startupCount = [int]$tj.data.count }
    }
} catch { Write-Log "启动项扫描失败（按 0 计）" }

# 6) 可释放系统文件（休眠 + Windows.old，受控统计）
$releasable = [int64]0
try {
    $hib = Get-Item -LiteralPath (Join-Path "$sysLetter`:" 'hiberfil.sys') -Force -ErrorAction SilentlyContinue
    if ($hib) { $releasable += $hib.Length }
} catch { }
$winOld = Join-Path "$sysLetter`:" 'Windows.old'
if (Test-Path -LiteralPath $winOld) { $releasable += Get-DirSize -Path $winOld -MaxFiles 30000 }

# Quick 模式跳过最耗时的重复文件哈希扫描
$dupBytes = [int64]0
if (-not $Quick) {
    try {
        $dupJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'dup.ps1') -MinMb 50 -Scope user 2>$null |
            Where-Object { $_ -match '^\{' } | Select-Object -Last 1
        if ($dupJson) {
            $dj = $dupJson | ConvertFrom-Json
            if ($dj.status -eq 'ok') { $dupBytes = [int64]$dj.data.wasted_bytes }
        }
    } catch { Write-Log "重复扫描失败（按 0 计）" }
}

# ---------- 评分（11 因素，权重与阈值逐项对齐 score.ts） ----------
$factors = [System.Collections.Generic.List[object]]::new()
$freeGB = $freeBytes / $GB; $totalGB = $totalBytes / $GB
$pct = 0; if ($totalBytes -gt 0) { $pct = $freeBytes / $totalBytes * 100 }
$freeScore = [math]::Min((Get-LargerScore $pct 30 10 28), (Get-LargerScore $freeGB 20 5 28))
$factors.Add([PSCustomObject]@{ key='free';   label='系统盘剩余空间';  weight=28; score=$freeScore; detail="剩余 $([math]::Round($freeGB,1)) GB（$([math]::Round($pct))%）" })
$factors.Add([PSCustomObject]@{ key='cap';    label='系统盘总容量';    weight=5;  score=(Get-LargerScore $totalGB 120 64 5);  detail="$([math]::Round($totalGB)) GB" })
$factors.Add([PSCustomObject]@{ key='junk';   label='垃圾文件体积';    weight=12; score=(Get-SmallerScore ($junkBytes/$GB) 1 15 12); detail="$([math]::Round($junkBytes/$GB,1)) GB" })
$factors.Add([PSCustomObject]@{ key='dup';    label='重复文件体积';    weight=8;  score=(Get-SmallerScore ($dupBytes/$GB) 0.5 10 8); detail="$([math]::Round($dupBytes/$GB,1)) GB$(if ($Quick) { '（快速模式未全量扫描）' })" })
$factors.Add([PSCustomObject]@{ key='social'; label='社交缓存体积';    weight=8;  score=(Get-SmallerScore ($socialBytes/$GB) 1 15 8); detail="$([math]::Round($socialBytes/$GB,1)) GB" })
$factors.Add([PSCustomObject]@{ key='reg';    label='注册表冗余项';    weight=4;  score=(Get-SmallerScore $registryCount 50 500 4); detail="$registryCount 项" })
$factors.Add([PSCustomObject]@{ key='startup';label='启动项数量';      weight=7;  score=(Get-SmallerScore $startupCount 5 20 7); detail="$startupCount 个" })

$diskScore = 11; $diskDetail = '正常'
if ($media -eq 'SSD') {
    if ($trimEnabled -eq $false) { $diskScore = 6; $diskDetail = 'SSD 未开启 Trim' }
    elseif ($trimEnabled -eq $true) { $diskDetail = 'SSD · Trim 已开启' }
} elseif ($media -eq 'HDD') { $diskDetail = 'HDD · 建议定期碎片整理' }
if ($smartOk -eq $false) { $diskScore = 0; $diskDetail = 'SMART 告警' }
elseif ($smartOk -eq $true) { $diskDetail += ' · SMART 正常' }
if ($media -eq 'Unknown') { $diskScore = 9; $diskDetail = '健康（详情未知）' }
$factors.Add([PSCustomObject]@{ key='disk'; label='磁盘健康(Trim/SMART)'; weight=11; score=$diskScore; detail=$diskDetail })

$fs = "$($vol.FileSystem)"
$fsScore = 5; $fsDetail = $fs; if (-not $fsDetail) { $fsDetail = '未知' }
if ($fs -eq 'NTFS') { $fsScore = 6; $fsDetail = 'NTFS' }
elseif ($fs) { $fsScore = 2; $fsDetail = "$fs（非 NTFS）" }
# 4K 对齐探测（需管理员，失败不扣分）
try {
    $offsets = @(Get-Partition -DriveLetter $sysLetter -ErrorAction Stop | ForEach-Object { $_.Offset })
    if ($offsets.Count -gt 0 -and ($offsets[0] % 4096) -eq 0 -and $fs -eq 'NTFS') {
        $fsScore = 7; $fsDetail = 'NTFS · 已 4K 对齐'
    } elseif ($offsets.Count -gt 0 -and ($offsets[0] % 4096) -ne 0) {
        $fsScore = 4; $fsDetail = 'NTFS · 未 4K 对齐'
    }
} catch { }
$factors.Add([PSCustomObject]@{ key='fs'; label='文件系统与4K对齐'; weight=7; score=$fsScore; detail=$fsDetail })

$factors.Add([PSCustomObject]@{ key='upd'; label='更新/临时文件积压'; weight=5; score=(Get-SmallerScore ($updateBacklog/$GB) 2 10 5); detail="$([math]::Round($updateBacklog/$GB,1)) GB" })
$factors.Add([PSCustomObject]@{ key='rel'; label='可释放系统文件';    weight=5; score=(Get-SmallerScore ($releasable/$GB) 1 20 5); detail="$([math]::Round($releasable/$GB,1)) GB" })

$score = ($factors | Measure-Object -Property score -Sum).Sum
$level = '危险'; $color = '#d33333'
if ($score -ge 85) { $level = '优秀'; $color = '#3a9d3a' }
elseif ($score -ge 70) { $level = '良好'; $color = '#5a9bd4' }
elseif ($score -ge 50) { $level = '一般'; $color = '#e6c200' }
elseif ($score -ge 30) { $level = '较差'; $color = '#e08a2b' }

# ---------- 动态建议（低位因素触发针对性建议，对应 score.ts buildSuggestions） ----------
$suggestions = [System.Collections.Generic.List[string]]::new()
foreach ($f in $factors) {
    if ($f.score -lt $f.weight * 0.7) {
        switch ($f.key) {
            'free'    { $suggestions.Add("系统盘剩余空间紧张（$([math]::Round($freeGB,1)) GB），建议清理大文件或将社交缓存迁移到非系统盘") }
            'junk'    { $suggestions.Add("垃圾文件达 $([math]::Round($junkBytes/$GB,1)) GB，建议执行垃圾清理（junk.ps1）") }
            'dup'     { $suggestions.Add("重复文件占用 $([math]::Round($dupBytes/$GB,1)) GB，建议清理重复项（每组保留最新一份，dup.ps1）") }
            'social'  { $suggestions.Add("社交缓存达 $([math]::Round($socialBytes/$GB,1)) GB，建议清理图片/视频类（聊天记录数据库已锁死不可删，social.ps1）") }
            'reg'     { $suggestions.Add("注册表冗余 $registryCount 项，建议执行注册表清理（删除前自动备份，registry.ps1）") }
            'startup' { $suggestions.Add("启动项 $startupCount 个偏多，建议禁用非必要项加快开机（startup.ps1）") }
            'disk'    { $suggestions.Add("磁盘健康异常（$media$(if ($trimEnabled -eq $false) { ' · Trim 未开启' })），建议备份数据并检查 SMART（disk.ps1）") }
            'upd'     { $suggestions.Add("更新/临时文件积压 $([math]::Round($updateBacklog/$GB,1)) GB，建议清理 Windows 更新缓存/传递优化（slim.ps1）") }
            'rel'     { $suggestions.Add("存在可释放系统文件 $([math]::Round($releasable/$GB,1)) GB（休眠/旧 Windows），确认无需回退后清理（slim.ps1）") }
        }
    }
}
if ($suggestions.Count -eq 0) { $suggestions.Add('各项指标健康，无需特别操作；可顺手优化社交缓存与大文件') }

Write-Result -Status ok -Data ([ordered]@{
    score = [int]$score; level = $level; level_color = $color
    factors = $factors; suggestions = $suggestions
    stats = [ordered]@{
        junk_bytes = $junkBytes; social_bytes = $socialBytes; dup_bytes = $dupBytes
        registry_count = $registryCount; startup_count = $startupCount
        system_free_gb = [math]::Round($freeGB, 1); system_total_gb = [math]::Round($totalGB, 1)
        disk_type = $media; quick = [bool]$Quick
        scanned_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    }
})
