<#
recycle.ps1 — 回收站管理（列举 / 恢复信息 / 彻底删除）+ 通用移入回收站

复刻 grclean recycle.ts / trash-bin.ts。
  枚举：按当前用户 SID 定位各盘 $Recycle.Bin\<SID>，解析 $I 二进制信息文件
        （原始路径/删除时间；version 2 布局），体积与资源管理器口径一致
  删除：条目已在回收站内，删除即永久；先清只读属性，带重试；
        提权运行时对顽固条目 takeown+icacls 恢复后重试
  trash：把任意文件/目录移入回收站（供其他模块/AI 引导复用的安全删除入口）

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File recycle.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File recycle.ps1 -Action delete -Session <会话> [-Ids id,...]
  powershell -NoProfile -ExecutionPolicy Bypass -File recycle.ps1 -Action trash -Path '<文件或目录>'

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'list',
    [string]$Session = '',
    [string]$Ids = '',
    [string]$Path = ''
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

if ($Action -eq 'list') {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $entries = [System.Collections.Generic.List[object]]::new()
    foreach ($d in (Get-DriveLetters)) {
        $rb = "$d`:\`$Recycle.Bin\$sid"
        if (-not (Test-Path -LiteralPath $rb)) { continue }
        $rs = Get-ChildItem -LiteralPath $rb -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '$R*' }
        foreach ($r in $rs) {
            $ip = Join-Path $rb ('$I' + $r.Name.Substring(2))
            $size = [int64]$r.Length
            if ($r.PSIsContainer) {
                $sum = (Get-ChildItem -LiteralPath $r.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
                        Measure-Object -Property Length -Sum).Sum
                if ($sum) { $size = [int64]$sum }
            }
            $originalPath = $r.FullName; $deletedAt = ''
            if (Test-Path -LiteralPath $ip) {
                try {
                    $bytes = [System.IO.File]::ReadAllBytes($ip)
                    if ($bytes.Length -ge 28) {
                        $sizeFromI = [BitConverter]::ToInt64($bytes, 8)
                        if ($sizeFromI -gt 0 -and -not $r.PSIsContainer) { $size = [int64]$sizeFromI }
                        $ft = [BitConverter]::ToInt64($bytes, 16)
                        if ($ft -gt 0) { $deletedAt = [DateTime]::FromFileTime($ft).ToString('yyyy-MM-dd HH:mm') }
                        # version 2：偏移24-27为路径长度；旧版路径从24开始
                        $ver = [BitConverter]::ToInt32($bytes, 0)
                        $pstart = 28
                        if ($ver -ne 2) { $pstart = 24 }
                        $plen = $bytes.Length - $pstart
                        while ($plen -gt 2 -and [BitConverter]::ToUInt16($bytes, $pstart + $plen - 2) -eq 0) { $plen -= 2 }
                        if ($plen -gt 0) { $originalPath = [System.Text.Encoding]::Unicode.GetString($bytes, $pstart, $plen) }
                    }
                } catch { }
            }
            $name = $r.Name
            try { $name = Split-Path -Leaf $originalPath } catch { }
            $entries.Add([PSCustomObject]@{
                id = 'rec:' + (New-CandidateId -Path $r.FullName).Substring(0, 16)
                r_path = $r.FullName; i_path = $ip
                name = $name; original_path = $originalPath; size = $size; deleted_at = $deletedAt; drive = $d
            })
        }
    }
    # 过滤 .lnk（回收站内快捷方式清理无收益且常因占用失败）
    $entries = @($entries | Where-Object { -not $_.name.ToLower().EndsWith('.lnk') })
    $sessionFile = Save-Session -Name 'recycle' -Candidates $entries
    $total = ($entries | Measure-Object -Property size -Sum).Sum
    if ($null -eq $total) { $total = 0 }
    Write-Result -Status ok -Data ([ordered]@{
        count = $entries.Count; total_bytes = [int64]$total
        session = $sessionFile; entries = $entries
    })
}

if ($Action -eq 'delete') {
    if (-not $Session) { Write-Result -Status error -Error 'delete 需要 -Session（list 返回）' }
    try { $sess = Load-Session -Path $Session } catch { Write-Result -Status error -Error $_.Exception.Message }
    $all = @($sess.candidates)
    if ($Ids) {
        $idList = $Ids -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $targets = @($all | Where-Object { $idList -contains $_.id })
    } else { $targets = $all }

    $deleted = 0; $deletedBytes = [int64]0
    $errors  = [System.Collections.Generic.List[string]]::new()
    $audit = [System.Collections.Generic.List[string]]::new()
    $elevated = Test-Admin

    foreach ($t in $targets) {
        $err = $null
        # 先清只读属性（回收站项常见，否则 EPERM），带重试
        foreach ($p in @($t.r_path, $t.i_path)) {
            if (-not $p) { continue }
            try {
                Set-ItemProperty -LiteralPath $p -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop
            } catch {
                $err = $_
                # 顽固拒绝访问 + 已提权：精确到该文件恢复 ACL 后重试一次
                if ($elevated -and "$($_.Exception.Message)" -match '拒绝访问|access is denied') {
                    takeown /f "$p" /a 2>&1 | Out-Null
                    icacls "$p" /grant '*S-1-5-32-544:(F)' /q 2>&1 | Out-Null
                    try { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop; $err = $null } catch { $err = $_ }
                }
            }
        }
        $gone = -not (Test-Path -LiteralPath $t.r_path -ErrorAction SilentlyContinue)
        if ($gone) { $deleted++; $deletedBytes += $t.size; $audit.Add($t.r_path) }
        elseif ($err) { $errors.Add("$($t.r_path): $($err.Exception.Message)") }
    }

    if ($audit.Count -gt 0) { Write-AuditLog -Action 'recycle-purge' -Items $audit }
    Write-Result -Status ok -Data ([ordered]@{
        deleted_count = $deleted; deleted_bytes = $deletedBytes
        error_count = $errors.Count; errors = $errors
    })
}

if ($Action -eq 'trash') {
    if (-not $Path) { Write-Result -Status error -Error 'trash 需要 -Path' }
    if (Test-ProtectedPath -Path $Path) { Write-Result -Status error -Error '受保护路径，已拦截' }
    try {
        if (-not (Test-Path -LiteralPath $Path)) { Write-Result -Status error -Error '路径不存在' }
        Move-ToRecycleBinSafe -Path $Path
        Write-AuditLog -Action 'trash' -Items @($Path)
        Write-Result -Status ok -Data @{ moved = $true; path = $Path }
    } catch {
        Write-Result -Status error -Error "移入回收站失败：$($_.Exception.Message)"
    }
}
