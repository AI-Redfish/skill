<#
restore.ps1 — 系统还原点管理（保留最近 1 个，清理更早的）

复刻 grclean restore.ts。策略：
  还原点随系统更新累积可达数 GB-数十 GB，但有用的通常只有最近一个；
  只删「更早」的，最近 1 个永不删除（删除前二次校验剩余数量）；
  删除用 vssadmin delete shadows /oldest 逐条删最老，绝不一次清空。
  所有变更操作需管理员；关闭系统保护会删除全部还原点，属高风险（本脚本不提供）。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File restore.ps1 -Action list
  powershell -NoProfile -ExecutionPolicy Bypass -File restore.ps1 -Action delete-oldest -Count 1 [-Force]
  powershell -NoProfile -ExecutionPolicy Bypass -File restore.ps1 -Action create -Description '<描述>'

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
[CmdletBinding()]
param(
    [string]$Action = 'list',
    [int]$Count = 1,
    [string]$Description = 'pc-manager 手动还原点',
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

$TypeMap = @{ 0='应用程序安装';1='应用程序卸载';2='系统还原';3='检查点';4='设备驱动安装';5='备份';6='手动创建';7='系统设置更改';10='设备驱动安装';12='修改设置' }

if ($Action -eq 'list') {
    $points = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($rp in (Get-ComputerRestorePoint -ErrorAction Stop | Sort-Object SequenceNumber)) {
            $typeText = "$($rp.RestorePointType)"
            $typeLabel = $TypeMap[[int]($rp.RestorePointType -as [int])]
            if (-not $typeLabel) { $typeLabel = $typeText }
            $points.Add([PSCustomObject]@{
                seq = $rp.SequenceNumber; description = "$($rp.Description)"
                time = "$($rp.CreationTime)"; type = $typeLabel
            })
        }
    } catch {
        Write-Result -Status error -Error "读取还原点失败（可能需要管理员或系统保护未开启）：$($_.Exception.Message)"
    }
    Write-Result -Status ok -Data ([ordered]@{
        count = $points.Count; points = $points
        note = '策略：保留最近 1 个；delete-oldest 逐条删更早的（需管理员 + -Force）'
    })
}

if ($Action -eq 'delete-oldest') {
    if (-not $Force) { Write-Result -Status error -Error '删除还原点不可逆，需加 -Force 显式确认' }
    if (-not (Test-Admin)) { Write-Result -Status error -Error 'vssadmin 需要管理员权限运行' }
    try {
        # 当前影子副本数（二次校验保证至少保留 1 个）
        $listOut = vssadmin list shadows 2>&1 | Out-String
        $total = ([regex]::Matches($listOut, 'shadow copy at')).Count
        $safe = [math]::Min($Count, $total - 1)   # 至少留 1 个
        if ($safe -le 0) { Write-Result -Status ok -Data @{ deleted = 0; note = '仅剩 1 个（或没有）还原点，按策略不删' } }
        $deleted = 0
        for ($i = 0; $i -lt $safe; $i++) {
            $out = vssadmin delete shadows /oldest /quiet 2>&1 | Out-String
            if ($LASTEXITCODE -eq 0) { $deleted++ } else { break }
        }
        if ($deleted -gt 0) { Write-AuditLog -Action 'restore-point' -Items @('oldest x' + $deleted) -Extra @{ op = 'delete-oldest' } }
        Write-Result -Status ok -Data @{ deleted = $deleted; requested = $Count; kept_at_least = 1 }
    } catch {
        Write-Result -Status error -Error "删除失败：$($_.Exception.Message)"
    }
}

if ($Action -eq 'create') {
    if (-not (Test-Admin)) { Write-Result -Status error -Error '创建还原点需要管理员权限' }
    try {
        Checkpoint-Computer -Description $Description -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop
        Write-AuditLog -Action 'restore-point' -Items @($Description) -Extra @{ op = 'create' }
        Write-Result -Status ok -Data @{ created = $true; description = $Description
            note = '系统 24 小时内默认只允许创建一个还原点（相同的才会被跳过）' }
    } catch {
        Write-Result -Status error -Error "创建失败：$($_.Exception.Message)"
    }
}
