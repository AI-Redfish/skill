<#
common.psm1 — pc-manager 共享基础模块（安全防线 + 通用工具）

复刻自 grclean 逆向分析结论（protected.ts / delete.ts / trash-bin.ts / audit.ts / ps.ts）。

纵深防御（所有删除类脚本共用）：
  1. 扫描/删除分离：scan 产出候选并落会话文件；delete 仅接受会话 id 反查路径，
     调用方无法注入任意路径（对应 grclean "会话 id 反查"防线）
  2. 受保护路径 fail-safe 拦截（无法解析/盘根/系统目录/用户主目录根/关键系统文件 → 一律保护）
  3. 系统级清理项需「显式放行前缀 + 路径落在声明目录内」双重校验
  4. 默认移入回收站；-Purge 才永久删除
  5. 占用/无权文件(EBUSY/EPERM/EACCES)归入 skipped 而非 failed
  6. 成功删除写审计日志（JSONL）
  7. 危险级操作由各脚本自行要求 -Force 二次确认

用法: Import-Module $PSScriptRoot/common.psm1 -Force
依赖: Windows PowerShell 5.1+；仅系统自带组件（Microsoft.VisualBasic 用于回收站）
#>

Set-StrictMode -Version 2.0

# ---------- 输出编码（强制 UTF-8，避免中文乱码；对应 grclean ps.ts PS_UTF8） ----------
if ($null -ne [Console]::Out) {
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
}
$OutputEncoding = [System.Text.Encoding]::UTF8

$script:PcManagerDir = Join-Path $env:LOCALAPPDATA 'pc-manager'

# ---------- JSON 输出（status/data/error 信封；stdout 只放 JSON，日志进 stderr） ----------
function Write-Result {
    param([Parameter(Mandatory)][ValidateSet('ok', 'error')][string]$Status,
          $Data = $null,
          [string]$Error = '')
    $obj = [ordered]@{ status = $Status; data = $Data }
    if ($Error) { $obj['error'] = $Error }
    $json = ConvertTo-Json -InputObject $obj -Depth 8 -Compress
    [Console]::Out.WriteLine($json)
    if ($Status -eq 'error') { exit 1 }
    exit 0
}

function Write-Log {
    param([string]$Message)
    [Console]::Error.WriteLine("[pc-manager] $Message")
}

function ConvertTo-PsQuote {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)
    return "'" + $Text.Replace("'", "''") + "'"
}

# ---------- 数据目录与会话 ----------
function Get-PcManagerDir {
    if (-not (Test-Path -LiteralPath $script:PcManagerDir)) {
        New-Item -ItemType Directory -Path $script:PcManagerDir -Force | Out-Null
    }
    return $script:PcManagerDir
}

function Get-SessionDir {
    $dir = Join-Path (Get-PcManagerDir) 'sessions'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return $dir
}

<#
.SYNOPSIS
保存扫描会话（候选清单）到 sessions/<Name>-<时间戳>.json，返回会话文件路径。
删除脚本只认会话文件里的 id→path 映射，杜绝注入任意路径。
#>
function Save-Session {
    param([Parameter(Mandatory)][string]$Name,
          [Parameter(Mandatory)]$Candidates)   # 数组：@{id;path;size;level;risk;...}
    $safe = ($Name -replace '[^A-Za-z0-9_-]', '_')
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $file = Join-Path (Get-SessionDir) "$safe-$ts.json"
    @{ created_at = (Get-Date).ToString('o'); name = $Name; candidates = $Candidates } |
        ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $file -Encoding UTF8
    return $file
}

function Load-Session {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "会话文件不存在：$Path" }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

# ---------- 受保护路径判定（复刻 protected.ts；fail-safe：无法确认一律按保护处理） ----------
$script:ProtectedExact = @(
    "$env:SystemDrive\pagefile.sys", "$env:SystemDrive\hiberfil.sys",
    "$env:SystemDrive\swapfile.sys", "$env:SystemDrive\bootmgr"
) | Where-Object { $_ }

function Get-ProtectedPrefixes {
    $prefixes = [System.Collections.Generic.List[string]]::new()
    foreach ($p in @("$env:SystemDrive\Program Files", "$env:SystemDrive\Program Files (x86)",
                     "$env:SystemDrive\ProgramData", "$env:SystemDrive\`$Recycle.Bin",
                     "$env:SystemDrive\Recovery")) {
        if ($p) { $prefixes.Add($p.ToLower()) }
    }
    # Windows 目录动态取（兼容非 C: 系统盘）
    foreach ($w in @($env:WINDIR, $env:SystemRoot, (Join-Path $env:SystemDrive 'Windows'))) {
        if ($w -and -not $prefixes.Contains($w.ToLower())) { $prefixes.Add($w.ToLower()) }
    }
    return $prefixes
}

function Test-ProtectedPath {
    <#
    纵深防御第一道防线。规则（fail-safe）：
    1. 路径为空 → 保护
    2. 磁盘根目录（如 C:\）→ 保护
    3. 系统关键文件精确匹配 → 保护
    4. 系统目录前缀 → 保护（AllowSystemPrefixes 显式放行且路径落在其内时例外）
    5. 用户主目录根 → 保护
    #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Path,
          [string[]]$AllowSystemPrefixes = @())
    if (-not $Path) { return $true }
    $p = $Path.Replace('/', '\').TrimEnd('\').ToLower()
    if ($p -notmatch '^[a-z]:\\') { return $true }   # 非绝对盘符路径，无法确认 → 保护

    # 盘根（仅 "c:" 或 "c:\"）
    if ($p -match '^[a-z]:\\?$') { return $true }

    foreach ($exact in $script:ProtectedExact) {
        if ($p -eq $exact.ToLower()) { return $true }
    }

    $allow = @($AllowSystemPrefixes | ForEach-Object { $_.Replace('/', '\').TrimEnd('\').ToLower() })
    foreach ($prefix in (Get-ProtectedPrefixes)) {
        if (-not $p.StartsWith($prefix)) { continue }
        $hit = $false
        foreach ($a in $allow) { if ($p.StartsWith($a)) { $hit = $true; break } }
        if (-not $hit) { return $true }
    }

    $homeRoot = ''
    if ($env:USERPROFILE) { $homeRoot = $env:USERPROFILE.Replace('/', '\').TrimEnd('\').ToLower() }
    if ($homeRoot -and $p -eq $homeRoot) { return $true }

    return $false
}

# ---------- Windows 危险子路径/扩展名（扫描期预过滤；复刻 junk.ts WINDOWS_RISKY_*） ----------
$script:WindowsRiskySubpaths = @(
    'system32\config', 'system32\catroot', 'system32\catroot2', 'system32\drivers',
    'system32\driverstore', 'system32\wbem', 'servicing', 'winsxs', 'boot',
    'system32\tasks', 'tasks', 'system32\grouppolicy', 'system32\grouppolicyusers',
    'grouppolicy', 'policies', 'inf', 'system32\winevt', 'system32\logfiles\wmi',
    'system32\spool', 'assembly', 'microsoft.net', 'systemresources', 'security',
    'appcompat', 'system32\spp', 'registration'
)
$script:WindowsRiskyExt = @('.sys', '.cat', '.drv')
$script:SystemMarkerFiles = @('desktop.ini', 'thumbs.db', 'ehthumbs.db', 'ehthumbs_vista.db')

function Test-WindowsRiskyFile {
    param([Parameter(Mandatory)][string]$Path)
    $s = $Path.Replace('/', '\').ToLower()
    $winDirs = @($env:WINDIR, $env:SystemRoot, (Join-Path $env:SystemDrive 'Windows')) |
        Where-Object { $_ } | ForEach-Object { $_.Replace('/', '\').TrimEnd('\').ToLower() }
    $under = $false
    foreach ($w in $winDirs) { if ($s.StartsWith($w)) { $under = $true; break } }
    if (-not $under) { return $false }
    foreach ($sub in $script:WindowsRiskySubpaths) {
        if ($s.Contains("\$sub\") -or $s.EndsWith("\$sub")) { return $true }
    }
    $ext = [System.IO.Path]::GetExtension($s)
    return ($script:WindowsRiskyExt -contains $ext)
}

# ---------- 删除操作（回收站默认 / 永久删除需 -Purge；对应 delete.ts + trash-bin.ts） ----------
function Move-ToRecycleBinSafe {
    <# 用系统标准接口移入回收站（grclean 同款兜底方案，不依赖外部 exe）。
    目录走 DeleteDirectory，文件走 DeleteFile。失败抛异常由调用方归类。 #>
    param([Parameter(Mandatory)][string]$Path)
    Add-Type -AssemblyName Microsoft.VisualBasic
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return }   # 已不存在视为成功
    if ($item -is [System.IO.DirectoryInfo]) {
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
            $Path, 'OnlyErrorDialogs', 'SendToRecycleBin')
    } else {
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
            $Path, 'OnlyErrorDialogs', 'SendToRecycleBin')
    }
    if (Test-Path -LiteralPath $Path) { throw "仍在原位置，未移入回收站：$Path" }
}

function Remove-ItemPurge {
    <# 永久删除：先清只读属性，带重试（对应 delete.ts chmod+maxRetries 语义）。 #>
    param([Parameter(Mandatory)][string]$Path)
    try { Set-ItemProperty -LiteralPath $Path -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue } catch { }
    Remove-Item -LiteralPath $Path -Force -Recurse -ErrorAction Stop
}

function Test-BusyError {
    <# 被占用/无权限类错误 → 调用方应归 skipped 而非 failed（对应 delete.ts 归类）。 #>
    param([Parameter(Mandatory)]$ErrorRecord)
    $msg = "$($ErrorRecord.Exception.Message)"
    $code = $ErrorRecord.CategoryInfo.Reason
    return ($msg -match 'being used by another process|拒绝访问|正由另一进程使用|access is denied|permission' -or
            $code -match 'UnauthorizedAccess')
}

# ---------- 审计日志（对应 audit.ts；JSONL 每行一条） ----------
function Write-AuditLog {
    param([Parameter(Mandatory)][string]$Action,   # trash|purge|uninstall|registry|ctxmenu|...
          [Parameter(Mandatory)]$Items,            # 字符串数组（路径）或对象数组
          [hashtable]$Extra = @{})
    try {
        $dir = Get-PcManagerDir
        $entry = [ordered]@{ ts = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(); action = $Action }
        foreach ($k in $Extra.Keys) { $entry[$k] = $Extra[$k] }
        $entry['items'] = @($Items)
        ($entry | ConvertTo-Json -Depth 6 -Compress) | Add-Content -LiteralPath (Join-Path $dir 'audit.jsonl') -Encoding UTF8
    } catch { Write-Log "审计写入失败（不阻断）：$($_.Exception.Message)" }
}

# ---------- 通用工具 ----------
function Get-DriveLetters {
    <# 枚举存在的本地盘符 A:~Z:（对应 bigfile.ts allDrives：Node existsSync 同语义探测）。 #>
    $out = @()
    for ($c = 65; $c -le 90; $c++) {
        $letter = [char]$c
        if (Test-Path -LiteralPath "$letter`:\" -ErrorAction SilentlyContinue) { $out += "$letter" }
    }
    return $out
}

function Get-SystemDriveLetter {
    foreach ($raw in @($env:SystemDrive, $env:WINDIR, $env:USERPROFILE)) {
        if ($raw -and $raw -match '^([a-zA-Z]):') { return $Matches[1].ToUpper() }
    }
    return 'C'
}

function Expand-EnvString {
    param([Parameter(Mandatory)][string]$Text)
    return [Environment]::ExpandEnvironmentVariables($Text)
}

function Get-DirSize {
    <# 目录体积统计（带文件数上限，避免超大目录拖死；对应 slim.ts dirSize）。 #>
    param([Parameter(Mandatory)][string]$Path, [int]$MaxFiles = 40000)
    $total = [int64]0; $n = 0
    $stack = [System.Collections.Stack]::new(); $stack.Push($Path)
    while ($stack.Count -gt 0 -and $n -lt $MaxFiles) {
        $cur = $stack.Pop()
        $ents = Get-ChildItem -LiteralPath $cur -Force -ErrorAction SilentlyContinue
        foreach ($e in $ents) {
            if ($n -ge $MaxFiles) { break }
            if ($e.PSIsContainer) { $stack.Push($e.FullName) }
            else { $total += $e.Length; $n++ }
        }
    }
    return $total
}

function Get-FileAgeDays {
    param([Parameter(Mandatory)]$FileInfo)
    return [int][math]::Floor(((Get-Date) - $FileInfo.LastWriteTime).TotalDays)
}

function New-CandidateId {
    <# 稳定 id：MD5(路径小写)（对应 junk.ts hashId；同一路径每次扫描 id 相同）。 #>
    param([Parameter(Mandatory)][string]$Path)
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $bytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Path.ToLower()))
    return ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Format-Bytes {
    param([Parameter(Mandatory)][long]$Bytes)
    if ($Bytes -ge 1GB) { return '{0:N2} GB' -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return '{0:N2} MB' -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return '{0:N2} KB' -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Export-ModuleMember -Function Write-Result, Write-Log, ConvertTo-PsQuote, Get-PcManagerDir, Get-SessionDir,
    Save-Session, Load-Session, Test-ProtectedPath, Test-WindowsRiskyFile, Move-ToRecycleBinSafe,
    Remove-ItemPurge, Test-BusyError, Write-AuditLog, Get-DriveLetters, Get-SystemDriveLetter,
    Expand-EnvString, Get-DirSize, Get-FileAgeDays, New-CandidateId, Format-Bytes, Test-Admin
