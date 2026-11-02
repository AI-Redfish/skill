<#
junk.ps1 — 垃圾清理（系统/浏览器缓存 + 14 项增强清理）

复刻 grclean junk.ts / junk_extra.ts / rules.ts。

规则模型（与 grclean 一致）：
  内置规则: 用户临时文件(>7天) / Edge / Chrome / Firefox 缓存(>7天)
  增强清理项(14): 各带风险等级 safe(默认勾选)/caution(不默认)/danger(不默认+删需 -Force)
    danger 项: Windows.old / Windows 更新清理 / 内存转储（不可逆）
    caution 项: 回收站（走 recycle.ps1 处理，此处仅提示）
  系统级项(位于 C:\Windows 等保护前缀下)删除时按「项声明根目录」放行，防越权。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File junk.ps1 -Action scan [-ExtraIds a,b] [-Json]
  powershell -NoProfile -ExecutionPolicy Bypass -File junk.ps1 -Action delete -Session <会话文件> [-Ids id1,id2 | -Recommended] [-Purge] [-Force]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封 {status,data[,error]}，日志进 stderr。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete', 'list')][string]$Action = 'scan',
    [string[]]$ExtraIds = @(),          # 增强项 id（空=仅内置规则）
    [string]$Session = '',              # delete: scan 返回的会话文件
    [string]$Ids = '',                  # delete: 逗号分隔的候选 id
    [switch]$Recommended,               # delete: 删除全部 safe 级默认项
    [switch]$Purge,                     # 永久删除（默认回收站）
    [switch]$Force                      # danger 级二次确认
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

# ---------- 内置规则（对应 rules.ts builtinJunkRules） ----------
function Get-BuiltinRules {
    $rules = [System.Collections.Generic.List[object]]::new()
    $rules.Add([PSCustomObject]@{ id='user_temp'; name='用户临时文件'; category='临时文件'; max_age_days=7; dirs=@($env:TEMP) })
    $local = $env:LOCALAPPDATA
    if ($local) {
        $rules.Add([PSCustomObject]@{ id='edge_cache';   name='Edge 缓存';    category='浏览器缓存'; max_age_days=7; dirs=@((Join-Path $local 'Microsoft\Edge\User Data\Default\Cache')) })
        $rules.Add([PSCustomObject]@{ id='chrome_cache'; name='Chrome 缓存';  category='浏览器缓存'; max_age_days=7; dirs=@((Join-Path $local 'Google\Chrome\User Data\Default\Cache')) })
        $rules.Add([PSCustomObject]@{ id='firefox_cache';name='Firefox 缓存'; category='浏览器缓存'; max_age_days=7; dirs=@((Join-Path $local 'Mozilla\Firefox\Profiles')) })
    }
    return $rules
}

# ---------- 增强清理项目录（对应 junk_extra.ts；含风险分级与声明根目录） ----------
function Get-ExtraItems {
    $items = @(
        @{ id='downloaded_program_files'; name='下载的程序文件';      level='safe';   recommend=$true;  max_age=0; patterns=@('%SystemRoot%\Downloaded Program Files\**\*') }
        @{ id='inet_temp';                name='Internet 临时文件';   level='safe';   recommend=$true;  max_age=0; patterns=@('%LOCALAPPDATA%\Microsoft\Windows\INetCache\**\*','%LOCALAPPDATA%\Microsoft\Windows\INetCookies\**\*') }
        @{ id='windows_error_report';     name='Windows 错误报告';    level='safe';   recommend=$true;  max_age=0; patterns=@('%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue\**\*','%PROGRAMDATA%\Microsoft\Windows\WER\**\*') }
        @{ id='dx_shader_cache';          name='DirectX 着色器缓存';  level='safe';   recommend=$true;  max_age=0; patterns=@('%LOCALAPPDATA%\D3DSCache\**\*') }
        @{ id='delivery_optimization';    name='传递优化文件';         level='safe';   recommend=$true;  max_age=0; patterns=@('%SystemRoot%\SoftwareDistribution\DeliveryOptimization\**\*','%SystemRoot%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\**\*') }
        @{ id='temp_files';               name='临时文件(系统)';      level='safe';   recommend=$true;  max_age=3; patterns=@('%TEMP%\**\*','%SystemRoot%\Temp\**\*') }
        @{ id='thumbnails';               name='缩略图缓存';           level='safe';   recommend=$true;  max_age=0; patterns=@('%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db') }
        @{ id='windows_upgrade_logs';     name='Windows 升级日志';    level='safe';   recommend=$true;  max_age=0; patterns=@('%SystemRoot%\Panther\**\*') }
        @{ id='temp_windows_install';     name='临时 Windows 安装文件'; level='safe';  recommend=$true;  max_age=0; patterns=@('%SystemDrive%\$WINDOWS.~BT\**\*','%SystemDrive%\$WINDOWS.~WS\**\*') }
        @{ id='user_error_report';        name='用户错误报告归档';     level='safe';   recommend=$true;  max_age=0; patterns=@('%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive\**\*') }
        @{ id='windows_old';              name='以前的 Windows 安装';  level='danger'; recommend=$false; max_age=0; patterns=@('%SystemDrive%\Windows.old\**\*') }
        @{ id='windows_update_cleanup';   name='Windows 更新清理';    level='danger'; recommend=$false; max_age=0; patterns=@('%SystemRoot%\SoftwareDistribution\Download\**\*') }
        @{ id='memory_dump';              name='系统错误内存转储';     level='danger'; recommend=$false; max_age=0; patterns=@('%SystemRoot%\Minidump\**\*','%SystemRoot%\MEMORY.DMP') }
        @{ id='recycle_bin';              name='回收站';               level='caution';recommend=$false; max_age=0; patterns=@(); special='recycle_bin' }
    )
    return $items
}

# 取 glob 模式的声明根目录（删除期越权校验用；对应 junk_extra.ts patternRoot）
function Get-PatternRoot {
    param([string]$Pattern)
    $norm = (Expand-EnvString $Pattern).Replace('\', '/').ToLower()
    $kept = @()
    foreach ($seg in ($norm -split '/')) {
        if ($seg -match '[*?]') { break }
        if ($seg) { $kept += $seg }
    }
    return ($kept -join '/')
}

# ---------- 扫描 ----------
if ($Action -eq 'list') {
    Write-Result -Status ok -Data @{ builtin = Get-BuiltinRules; extras = Get-ExtraItems }
}

if ($Action -eq 'scan') {
    $candidates = [System.Collections.Generic.List[object]]::new()
    $lockProne = '\.(tmp|temp|lock|partial)(\.|$)'
    $markerFiles = @('desktop.ini', 'thumbs.db', 'ehthumbs.db', 'ehthumbs_vista.db')

    function Add-FilesUnder {
        param([string[]]$RootDirs, [string]$RuleId, [string]$Category, [int]$MaxAgeDays, [string]$Level, [bool]$Recommend)
        foreach ($root in $RootDirs) {
            if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
            $files = Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue
            foreach ($f in $files) {
                # 预过滤链（对应 junk.ts 扫描期跳过逻辑）
                if (Test-WindowsRiskyFile -Path $f.FullName) { continue }
                if ($markerFiles -contains $f.Name.ToLower()) { continue }
                if ($f.Extension.ToLower() -eq '.lnk') { continue }
                $base = $f.Name.ToLower()
                if (($base -match $lockProne -or $base.EndsWith('~')) -and
                    -not (Test-Path -LiteralPath $f.FullName -PathType Leaf -ErrorAction SilentlyContinue)) { continue }
                $age = Get-FileAgeDays -FileInfo $f
                if ($MaxAgeDays -gt 0 -and $age -lt $MaxAgeDays) { continue }
                $candidates.Add([PSCustomObject]@{
                    id = New-CandidateId -Path $f.FullName; path = $f.FullName; size = $f.Length
                    category = $Category; rule_id = $RuleId; level = $Level; recommend = $Recommend
                })
            }
        }
    }

    # 1) 内置规则（用户空间，全部 safe）
    foreach ($r in (Get-BuiltinRules)) {
        Add-FilesUnder -RootDirs @($r.dirs) -RuleId $r.id -Category $r.category -MaxAgeDays $r.max_age_days -Level 'safe' -Recommend $true
    }

    # 2) 增强清理项（用户勾选）
    $notes = @()
    foreach ($id in $ExtraIds) {
        $item = Get-ExtraItems | Where-Object { $_.id -eq $id }
        if (-not $item) { continue }
        if ($item.special -eq 'recycle_bin') { $notes += '回收站为特殊项，请使用 recycle.ps1'; continue }
        foreach ($pat in $item.patterns) {
            $expanded = Expand-EnvString $pat
            $rootPart = $expanded -replace '(?<!\\)(\*\*?[^\\]*|[^\\]*[*?][^\\]*)(\\.*)?$',''   # 截到首个通配段
            $rootPart = $rootPart.TrimEnd('\')
            Add-FilesUnder -RootDirs @($rootPart) -RuleId "extra:$($item.id)" -Category $item.name -MaxAgeDays $item.max_age -Level $item.level -Recommend ([bool]$item.recommend)
        }
    }

    $sessionFile = Save-Session -Name 'junk' -Candidates $candidates
    $total = ($candidates | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    $sumOf = { param($lv) $s = @($candidates | Where-Object level -eq $lv | Measure-Object -Property size -Sum).Sum; if ($null -eq $s) { 0 } else { $s } }
    Write-Result -Status ok -Data ([ordered]@{
        count = $candidates.Count; total_bytes = [int64]$total
        by_level = @{
            safe    = & $sumOf 'safe'
            caution = & $sumOf 'caution'
            danger  = & $sumOf 'danger'
        }
        session = $sessionFile; notes = $notes; candidates = $candidates
    })
}

# ---------- 删除（会话 id 反查 + 执行期二次防线） ----------
if ($Action -eq 'delete') {
    if (-not $Session) { Write-Result -Status error -Error 'delete 需要 -Session <scan 返回的会话文件>' }
    try { $sess = Load-Session -Path $Session } catch { Write-Result -Status error -Error $_.Exception.Message }

    $all = @($sess.candidates)
    $toDelete = @()
    if ($Ids) {
        $idList = $Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $toDelete = @($all | Where-Object { $idList -contains $_.id })
        $missing = @($idList | Where-Object { $_ -notin @($all.id) })
        if ($missing.Count) { Write-Log "以下 id 不在会话内（已忽略）：$($missing -join ', ')" }
    } elseif ($Recommended) {
        $toDelete = @($all | Where-Object { $_.recommend -and $_.level -eq 'safe' })
    } else {
        Write-Result -Status error -Error '需要 -Ids <id,...> 或 -Recommended 之一'
    }

    # danger 级必须 -Force（对应 grclean 强确认）
    $danger = @($toDelete | Where-Object level -eq 'danger')
    if ($danger.Count -and -not $Force) {
        Write-Result -Status error -Error "包含 $($danger.Count) 个 danger 级文件（不可逆），需加 -Force 显式确认"
    }

    $deleted = 0; $deletedBytes = [int64]0
    $skipped = [System.Collections.Generic.List[object]]::new()
    $errors  = [System.Collections.Generic.List[string]]::new()

    # 系统级放行前缀：本次勾选项声明的根目录（双重校验之第二重）
    $allow = @()
    foreach ($id in $ExtraIds) {
        $item = Get-ExtraItems | Where-Object { $_.id -eq $id }
        if ($item) { foreach ($p in $item.patterns) { $allow += (Get-PatternRoot $p) } }
    }

    foreach ($c in $toDelete) {
        try {
            if (Test-ProtectedPath -Path $c.path -AllowSystemPrefixes $allow) {
                $skipped.Add([PSCustomObject]@{ path = $c.path; reason = '受保护路径，已拦截' }); continue
            }
            $f = Get-Item -LiteralPath $c.path -Force -ErrorAction SilentlyContinue
            if (-not $f) { $skipped.Add([PSCustomObject]@{ path = $c.path; reason = '已不存在' }); continue }
            if ($f.PSIsContainer) { $skipped.Add([PSCustomObject]@{ path = $c.path; reason = 'junk 仅删文件，目录跳过' }); continue }
            if ($Purge) { Remove-ItemPurge -Path $c.path } else { Move-ToRecycleBinSafe -Path $c.path }
            $deleted++; $deletedBytes += $f.Length
        } catch {
            if (Test-BusyError -ErrorRecord $_) {
                $skipped.Add([PSCustomObject]@{ path = $c.path; reason = '使用中或无权访问，已跳过' })
            } else { $errors.Add("$($c.path): $($_.Exception.Message)") }
        }
    }

    if ($deleted -gt 0) {
        $auditAction = 'trash'
        if ($Purge) { $auditAction = 'purge' }
        Write-AuditLog -Action $auditAction -Items @($toDelete | ForEach-Object { $_.path })
    }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; deleted_bytes = $deletedBytes
        skipped_count = $skipped.Count; error_count = $errors.Count
        skipped = $skipped; errors = $errors
    })
}
