<#
social.ps1 — 社交软件缓存专清（微信/QQ/钉钉/企微/飞书/微博/抖音/YY/陌陌/Soul/千牛）

复刻 grclean social.ts。

核心设计（与 grclean 一致）：
  四级风险分组（聊天记录永久锁死，绝不提供删除入口）：
    safe    ①临时缓存 Cache/Temp/Log/GPUCache…（默认勾选）
    advise  ②图片缓存 image/thumb/attach…（默认勾选；微信加密图 .dat 属此类）
    caution ③视频/接收文件 video/filerecv/download/emoji…（默认不勾）
    locked  ④聊天记录 .db/.db-wal/.db-shm/.sqlite/.sqlite3（仅展示体积，后端也拒绝删除）
  定位策略：系统盘默认路径 + 每块盘根/Documents/Users\<user>\Documents 跨盘探测 +
    微信 4.x 自定义数据目录（读 %APPDATA%\Tencent\xwechat\config\*.ini 首行父目录）
  DFS 深度 ≤6；命中已知类别目录即成条目不再下钻；backup/all_users/migrate 永不展开。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File social.ps1 -Action scan
  powershell -NoProfile -ExecutionPolicy Bypass -File social.ps1 -Action delete -Session <会话> [-Ids id,...] [-Purge]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete')][string]$Action = 'scan',
    [string]$Session = '',
    [string]$Ids = '',
    [switch]$Purge
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

# ---------- 应用目录（对应 social.ts APPS） ----------
$Apps = @(
    @{ name='微信';    dirs=@("$env:USERPROFILE\Documents\WeChat Files","$env:USERPROFILE\Documents\xwechat_files","$env:USERPROFILE\xwechat_files","$env:APPDATA\Tencent\xwechat\log"); reloc=@('WeChat Files','xwechat_files'); wechat=$true }
    @{ name='QQ';      dirs=@("$env:USERPROFILE\Documents\Tencent Files"); reloc=@('Tencent Files') }
    @{ name='钉钉';    dirs=@("$env:USERPROFILE\Documents\DingTalk"); reloc=@('DingTalk') }
    @{ name='企业微信'; dirs=@("$env:USERPROFILE\Documents\WXWork"); reloc=@('WXWork') }
    @{ name='飞书';    dirs=@("$env:LOCALAPPDATA\Lark\SDK"); reloc=@('Lark') }
    @{ name='微博桌面'; dirs=@("$env:APPDATA\Weibo"); reloc=@('Weibo') }
    @{ name='抖音聊天'; dirs=@("$env:LOCALAPPDATA\Douyin","$env:APPDATA\Douyin"); reloc=@('Douyin') }
    @{ name='YY语音';  dirs=@("$env:APPDATA\YY"); reloc=@('YY') }
    @{ name='陌陌';    dirs=@("$env:APPDATA\Momo"); reloc=@('Momo') }
    @{ name='Soul';    dirs=@("$env:APPDATA\Soul"); reloc=@('Soul') }
    @{ name='千牛';    dirs=@("$env:USERPROFILE\Documents\Qianniu","$env:APPDATA\Qianniu","$env:LOCALAPPDATA\Qianniu"); reloc=@('Qianniu') }
)

# ---------- 风险分级目录名（小写比对；对应 social.ts 四个 Set） ----------
$SafeDirs    = @('cache','caches','cachedata','temp','tmp','gpucache','code cache','blob_storage','session storage','shadercache','crashpad','logs','log')
$AdviseDirs  = @('image','images','pic','pics','thumb','thumbs','thumbnail','thumbnails','media','attach')
$CautionDirs = @('filerecv','file','files','video','videos','download','downloads','customemotions','customemotion','emoji','emotion','sticker','favorite','favorites')
$LockedDirs  = @('msgdb','msgstorage','databases','database','db','dbstorage','message','messages')
$SkipDirs    = @('backup','all_users','migrate')
# 聊天记录库扩展名 —— 任何情况下都不删除（.dat 不在此列：微信加密图片缓存属可清图片缓存）
$LockedExt   = '\.(db|db-wal|db-shm|sqlite|sqlite3)$'

function Get-LevelOfDir {
    param([string]$Name)
    $n = $Name.ToLower()
    if ($LockedDirs -contains $n)  { return 'locked' }
    if ($SafeDirs -contains $n)    { return 'safe' }
    if ($AdviseDirs -contains $n)  { return 'advise' }
    if ($CautionDirs -contains $n) { return 'caution' }
    return $null
}

# 微信 4.x 自定义数据目录（config\*.ini 首行父目录 + xwechat_files；对应 wechatCustomDataRoots）
function Get-WechatCustomRoots {
    $out = @()
    $cfgDir = Join-Path $env:APPDATA 'Tencent\xwechat\config'
    if (-not (Test-Path -LiteralPath $cfgDir)) { return $out }
    foreach ($f in (Get-ChildItem -LiteralPath $cfgDir -Filter *.ini -ErrorAction SilentlyContinue)) {
        try {
            $line = (Get-Content -LiteralPath $f.FullName -Encoding UTF8 -ErrorAction Stop |
                Where-Object { $_.Trim() } | Select-Object -First 1)
            if ($line) { $out += (Join-Path $line.Trim() 'xwechat_files') }
        } catch { }
    }
    return $out | Select-Object -Unique
}

function Get-CrossDriveRoots {
    param($App, [string[]]$Drives, [string]$Sys, [string]$User)
    $out = @()
    foreach ($d in $Drives) {
        if ($d -eq $Sys) { continue }
        foreach ($r in $App.reloc) {
            $out += "$d`:\$r"
            $out += "$d`:\Documents\$r"
            if ($User) { $out += "$d`:\Users\$User\Documents\$r" }
        }
    }
    return $out | Select-Object -Unique
}

# ---------- 扫描 ----------
if ($Action -eq 'scan') {
    $items = [System.Collections.Generic.List[object]]::new()
    $drives = Get-DriveLetters
    $sys = Get-SystemDriveLetter
    $user = $env:USERNAME

    foreach ($app in $Apps) {
        $roots = @($app.dirs | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
        $roots += Get-CrossDriveRoots -App $app -Drives $drives -Sys $sys -User $user |
            Where-Object { Test-Path -LiteralPath $_ }
        if ($app.wechat) { $roots += Get-WechatCustomRoots | Where-Object { Test-Path -LiteralPath $_ } }
        $roots = $roots | Select-Object -Unique

        $lockedSize = [int64]0; $lockedFiles = 0
        $targets = [System.Collections.Generic.List[object]]::new()   # @{dir;level}

        foreach ($root in $roots) {
            # 根目录本身即已知类别（如 Tencent\xwechat\log）→ 整目录成条
            $rootLevel = Get-LevelOfDir -Name (Split-Path -Leaf $root)
            if ($rootLevel -and $rootLevel -ne 'locked') {
                $targets.Add([PSCustomObject]@{ dir = $root; level = $rootLevel }); continue
            }
            # DFS 下钻（深度 ≤6；命中类别成条，未知继续下钻；backup 等永不展开）
            $stack = [System.Collections.Stack]::new(); $stack.Push(@{ dir = $root; depth = 0 })
            while ($stack.Count -gt 0) {
                $cur = $stack.Pop()
                if ($cur.depth -gt 6) { continue }
                $ents = Get-ChildItem -LiteralPath $cur.dir -Force -ErrorAction SilentlyContinue
                foreach ($e in $ents) {
                    if ($e.PSIsContainer) {
                        $n = $e.Name.ToLower()
                        if ($SkipDirs -contains $n) { continue }
                        $lv = Get-LevelOfDir -Name $e.Name
                        if ($lv -eq 'locked') { $targets.Add([PSCustomObject]@{ dir = $e.FullName; level = 'locked' }); continue }
                        if ($null -eq $lv) { $stack.Push(@{ dir = $e.FullName; depth = $cur.depth + 1 }); continue }
                        $targets.Add([PSCustomObject]@{ dir = $e.FullName; level = $lv })
                    } else {
                        if ($e.Name -match $LockedExt) { $lockedSize += $e.Length; $lockedFiles++ }
                    }
                }
            }
        }

        foreach ($t in $targets) {
            $size = [int64]0; $files = 0; $blocked = 0
            $walk = [System.Collections.Stack]::new(); $walk.Push($t.dir)
            while ($walk.Count -gt 0 -and $files -lt 20000) {
                $cur = $walk.Pop()
                foreach ($e in (Get-ChildItem -LiteralPath $cur -Force -ErrorAction SilentlyContinue)) {
                    if ($files -ge 20000) { break }
                    if ($e.PSIsContainer) { $walk.Push($e.FullName) }
                    elseif ($e.Name -match $LockedExt) {
                        if ($t.level -ne 'locked') { $blocked++ } else { $lockedSize += $e.Length; $lockedFiles++ }
                    } else {
                        $size += $e.Length; $files++
                        if ($t.level -eq 'locked') { $lockedSize += $e.Length; $lockedFiles++ }
                    }
                }
            }
            if ($t.level -eq 'locked') { continue }   # 锁定目录并入应用级锁定汇总
            if ($files -gt 0) {
                $items.Add([PSCustomObject]@{
                    id = ('soc:' + (New-CandidateId -Path $t.dir).Substring(0, 16))
                    app = $app.name; level = $t.level; name = Split-Path -Leaf $t.dir
                    path = $t.dir; size = $size; file_count = $files
                    blocked = $blocked     # 目录内聊天记录库数量；>0 时删除走逐文件模式
                    locked = $false
                    recommend = ($t.level -eq 'safe' -or $t.level -eq 'advise')
                })
            }
        }
        # 每款应用的聊天记录汇总为一条 locked 条目（仅展示体积）
        if ($lockedFiles -gt 0) {
            $items.Add([PSCustomObject]@{
                id = 'soc:' + (New-CandidateId -Path "$($app.name)::locked").Substring(0, 16)
                app = $app.name; level = 'locked'; name = '聊天记录数据库'
                path = "$($app.name)（Msg*.db 等，永久锁死）"; size = $lockedSize; file_count = $lockedFiles
                blocked = 0; locked = $true; recommend = $false
            })
        }
    }

    $sessionFile = Save-Session -Name 'social' -Candidates $items
    $total = ($items | Where-Object { -not $_.locked } | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    Write-Result -Status ok -Data ([ordered]@{
        count = $items.Count; cleanable_bytes = [int64]$total
        by_level = @{
            safe = @($items | Where-Object level -eq 'safe' | Measure-Object -Property size -Sum).Sum
            advise = @($items | Where-Object level -eq 'advise' | Measure-Object -Property size -Sum).Sum
            caution = @($items | Where-Object level -eq 'caution' | Measure-Object -Property size -Sum).Sum
            locked = @($items | Where-Object level -eq 'locked' | Measure-Object -Property size -Sum).Sum
        }
        session = $sessionFile; items = $items
    })
}

# ---------- 删除（比通用清理更严：回收站失败不兜底直删；锁定级机制性拒绝） ----------
if ($Action -eq 'delete') {
    if (-not $Session) { Write-Result -Status error -Error 'delete 需要 -Session <scan 返回的会话文件>' }
    try { $sess = Load-Session -Path $Session } catch { Write-Result -Status error -Error $_.Exception.Message }
    $all = @($sess.candidates)
    if (-not $Ids) { Write-Result -Status error -Error '需要 -Ids <id,...>（勾选的条目）' }
    $idList = $Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $targets = @($all | Where-Object { $idList -contains $_.id })

    $deleted = 0; $deletedBytes = [int64]0
    $skipped = [System.Collections.Generic.List[object]]::new()
    $errors  = [System.Collections.Generic.List[string]]::new()
    $audit = [System.Collections.Generic.List[string]]::new()

    foreach ($t in $targets) {
        if ($t.locked -or $t.level -eq 'locked') {
            $skipped.Add([PSCustomObject]@{ path = $t.path; reason = '聊天记录已锁定，禁止清理' }); continue
        }
        try {
            # 整目录快路径：目录内无聊天记录库且不受保护 → 一次回收站操作移走整棵树
            if ([int]$t.blocked -eq 0 -and -not (Test-ProtectedPath -Path $t.path)) {
                if ($Purge) { Remove-ItemPurge -Path $t.path } else { Move-ToRecycleBinSafe -Path $t.path }
                if (-not (Test-Path -LiteralPath $t.path)) {
                    $deleted++; $deletedBytes += $t.size; $audit.Add($t.path); continue
                }
            }
            # 逐文件模式：展开目录，剔除聊天记录库 + 受保护路径（双保险）
            $gone = 0
            foreach ($f in (Get-ChildItem -LiteralPath $t.path -Recurse -File -Force -ErrorAction SilentlyContinue)) {
                if ($f.Name -match $LockedExt) { continue }
                if (Test-ProtectedPath -Path $f.FullName) { continue }
                try {
                    if ($Purge) { Remove-ItemPurge -Path $f.FullName } else { Move-ToRecycleBinSafe -Path $f.FullName }
                    $gone++; $deleted++; $deletedBytes += $f.Length; $audit.Add($f.FullName)
                } catch {
                    if (Test-BusyError -ErrorRecord $_) {
                        $skipped.Add([PSCustomObject]@{ path = $f.FullName; reason = '使用中或无权访问，已跳过' })
                    } else { $errors.Add("$($f.FullName): $($_.Exception.Message)") }
                }
            }
            if ($gone -eq 0 -and -not (Test-Path -LiteralPath $t.path -ErrorAction SilentlyContinue)) {
                $deleted++; $deletedBytes += $t.size
            }
        } catch {
            $errors.Add("$($t.path): $($_.Exception.Message)")
        }
    }

    if ($audit.Count -gt 0) {
        $act = 'trash'; if ($Purge) { $act = 'purge' }
        Write-AuditLog -Action $act -Items $audit -Extra @{ module = 'social' }
    }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; deleted_bytes = $deletedBytes
        skipped_count = $skipped.Count; error_count = $errors.Count
        skipped = $skipped; errors = $errors
    })
}
