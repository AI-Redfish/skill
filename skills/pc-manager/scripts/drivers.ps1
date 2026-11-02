<#
drivers.ps1 — 旧驱动清理（DriverStore\FileRepository 中设备不再使用的驱动包）

复刻 grclean drivers.ts。判定「在用」（两条依据，保守优先）：
  1. Win32_PnPSignedDriver.InfName —— 所有已绑定设备的驱动 inf 名集合
  2. Get-WindowsDriver -Online —— 驱动包发布名(oemNN.inf)与原始名映射
     （失败回退 pnputil /enum-drivers 文本解析）
  仅 old_confirmed（同 inf 存在更新版本）与 recommended（无设备绑定）可清理；
  删除走 pnputil /delete-driver <oemNN.inf> /force（需管理员）；
  无法解析发布名的目录只展示体积不提供删除。采集失败一律「视为在用」。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File drivers.ps1 -Action scan
  powershell -NoProfile -ExecutionPolicy Bypass -File drivers.ps1 -Action delete -Published oem12.inf [-Force]

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [ValidateSet('scan', 'delete')][string]$Action = 'scan',
    [string]$Published = '',
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot\common.psm1 -Force -DisableNameChecking 

$repo = Join-Path $env:WINDIR 'System32\DriverStore\FileRepository'

# 版本号比较（>0: a 更新）
function Compare-Version { param([string]$A, [string]$B)
    if (-not $A -or -not $B) { return 0 }
    $pa = $A -split '\.' | ForEach-Object { [int]($_ -replace '\D', '0') }
    $pb = $B -split '\.' | ForEach-Object { [int]($_ -replace '\D', '0') }
    $n = [math]::Max($pa.Count, $pb.Count)
    for ($i = 0; $i -lt $n; $i++) {
        $x = 0; if ($i -lt $pa.Count) { $x = $pa[$i] }
        $y = 0; if ($i -lt $pb.Count) { $y = $pb[$i] }
        if ($x -ne $y) { return ($x - $y) }
    }
    return 0
}

if ($Action -eq 'scan') {
    # 1) 在用 inf 集合 + 设备聚合（WMI，普通权限）
    $usedInfs = [System.Collections.Generic.HashSet[string]]::new()
    $byInf = @{}
    try {
        foreach ($d in (Get-CimInstance Win32_PnPSignedDriver -ErrorAction Stop | Where-Object { $_.InfName })) {
            $inf = "$($d.InfName)".ToLower()
            [void]$usedInfs.Add($inf)
            if (-not $byInf.ContainsKey($inf)) {
                $byInf[$inf] = @{ count = 0; active = 0; provider = ''; version = ''; className = '' }
            }
            $r = $byInf[$inf]
            $r.count++
            if ("$($d.Status)".ToUpper() -eq 'OK') { $r.active++ }
            if (-not $r.provider -and $d.Manufacturer) { $r.provider = "$($d.Manufacturer)" }
            if (-not $r.version -and $d.DriverVersion) { $r.version = "$($d.DriverVersion)" }
            if (-not $r.className -and $d.DriverClass) { $r.className = "$($d.DriverClass)" }
        }
        Write-Log "WMI 在用 inf: $($usedInfs.Count)"
    } catch { Write-Log "WMI 采集失败：$($_.Exception.Message)（所有项将视为在用）" }

    # 2) 发布名映射（Get-WindowsDriver 优先，pnputil 回退）
    $meta = @{}   # 原始 inf 基名(小写) → @{published;provider;version;className}
    $got = $false
    try {
        foreach ($p in (Get-WindowsDriver -Online -ErrorAction Stop)) {
            $pub = "$($p.Driver)".ToLower()
            $base = [System.IO.Path]::GetFileName("$($p.OriginalFileName)").ToLower()
            if ($pub -and $base -and -not $meta.ContainsKey($base)) {
                $meta[$base] = @{ published = $pub; provider = "$($p.ProviderName)"; version = "$($p.Version)"; className = "$($p.ClassName)" }
            }
        }
        $got = ($meta.Count -gt 0)
    } catch { }
    if (-not $got) {
        try {
            $cur = $null
            foreach ($line in (& pnputil /enum-drivers 2>$null)) {
                if ($line -match '^Published Name:\s*(.+)$') {
                    if ($cur -and $cur.pub -and $cur.orig) {
                        $base = [System.IO.Path]::GetFileName($cur.orig).ToLower()
                        if ($base -and -not $meta.ContainsKey($base)) {
                            $meta[$base] = @{ published = $cur.pub.ToLower(); provider = $cur.provider; version = $cur.version; className = $cur.className }
                        }
                    }
                    $cur = @{ pub = $Matches[1].Trim(); orig = ''; provider = ''; version = ''; className = '' }
                } elseif ($cur) {
                    if ($line -match '^Original Name:\s*(.+)$') { $cur.orig = $Matches[1].Trim() }
                    elseif ($line -match '^Original Inf Name:\s*(.+)$') { $cur.orig = $Matches[1].Trim() }
                    elseif ($line -match '^Provider Name:\s*(.+)$') { $cur.provider = $Matches[1].Trim() }
                    elseif ($line -match '^Class Name:\s*(.+)$') { $cur.className = $Matches[1].Trim() }
                    elseif ($line -match '^Driver Version:\s*(.+)') { $cur.version = ($Matches[1].Trim() -replace '^\S+\s+', '') }
                }
            }
        } catch { }
    }
    Write-Log "发布名映射: $($meta.Count) 条"

    # 3) 扫描 FileRepository 目录，按同 inf 最高版本判定
    $items = [System.Collections.Generic.List[object]]::new()
    foreach ($d in (Get-ChildItem -LiteralPath $repo -Directory -ErrorAction SilentlyContinue)) {
        # 目录名形如 nv_disp.inf_amd64_xxxx → 原始 inf 基名
        $base = ($d.Name -split '_')[0].ToLower()
        if (-not $base.EndsWith('.inf')) { continue }
        $infs = @(Get-ChildItem -LiteralPath $d.FullName -Filter *.inf -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
        $m = $meta[$base]
        $ver = ''
        if ($m) { $ver = $m.version }
        if (-not $ver -and $byInf[$base]) { $ver = $byInf[$base].version }

        $status = 'unknown'; $reason = '信息不足，视为在用'
        $devCount = 0
        if ($byInf[$base]) { $devCount = $byInf[$base].count }

        # 同 inf 是否存在更新版本的其它目录
        $newerExists = $false
        if ($ver) {
            foreach ($d2 in (Get-ChildItem -LiteralPath $repo -Directory -ErrorAction SilentlyContinue)) {
                if ($d2.Name -eq $d.Name) { continue }
                $base2 = ($d2.Name -split '_')[0].ToLower()
                if ($base2 -ne $base) { continue }
                $m2 = $meta[$base2]
                if ($m2 -and (Compare-Version -A $m2.version -B $ver) -gt 0) { $newerExists = $true; break }
            }
        }

        if ($usedInfs.Contains($base)) {
            $status = 'in_use'; $reason = "有设备正在使用（$devCount 个设备）"
            if ($newerExists) { $status = 'old_confirmed'; $reason = '存在更新版本且旧版仍被部分设备使用' }
        } elseif ($newerExists) {
            $status = 'old_confirmed'; $reason = '无设备绑定且存在更新版本'
        } elseif ($meta.Count -gt 0 -and $got) {
            $status = 'recommended'; $reason = '无设备绑定，无更新版本（需人工确认）'
        }

        $items.Add([PSCustomObject]@{
            id = 'drv:' + (New-CandidateId -Path $d.FullName).Substring(0, 16)
            name = $d.Name; path = $d.FullName
            size = Get-DirSize -Path $d.FullName -MaxFiles 20000
            infs = $infs; original_name = $base
            published = $(if ($m) { $m.published } else { $null })
            provider = $(if ($m) { $m.provider } else { '' })
            version = $ver; class_name = $(if ($m) { $m.className } else { '' })
            device_count = $devCount
            status = $status; reason = $reason
            candidate = ($status -eq 'old_confirmed' -or $status -eq 'recommended')
            actionable = (($status -eq 'old_confirmed' -or $status -eq 'recommended') -and $m)
        })
    }

    $candidates = @($items | Where-Object candidate)
    $sessionFile = Save-Session -Name 'drivers' -Candidates $items
    Write-Result -Status ok -Data ([ordered]@{
        count = $items.Count; candidate_count = $candidates.Count
        candidate_bytes = [int64](($candidates | Measure-Object -Property size -Sum).Sum)
        session = $sessionFile; items = $items
        note = '删除需管理员；仅 actionable 项（已解析发布名）可经 delete -Published oemNN.inf 清理'
    })
}

if ($Action -eq 'delete') {
    if (-not $Published) { Write-Result -Status error -Error '需要 -Published <oemNN.inf>（从 scan 结果取）' }
    if ($Published -notmatch '^oem\d+\.inf$') { Write-Result -Status error -Error "发布名非法：$Published（应形如 oem12.inf）" }
    if (-not $Force) { Write-Result -Status error -Error '删除驱动不可逆，需加 -Force 显式确认' }
    if (-not (Test-Admin)) { Write-Result -Status error -Error 'pnputil 删除驱动需要管理员权限运行' }
    try {
        $out = pnputil /delete-driver $Published /force 2>&1 | Out-String
        Write-AuditLog -Action 'drivers' -Items @($Published) -Extra @{ op = 'delete' }
        Write-Result -Status ok -Data @{ published = $Published; output = $out }
    } catch {
        Write-Result -Status error -Error "删除失败：$($_.Exception.Message)"
    }
}
