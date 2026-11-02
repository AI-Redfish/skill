<#
sysinfo.ps1 — 系统信息采集（概览卡片数据源）

复刻 grclean sysinfo.ts。Node 能拿的直接用（此处 PowerShell 等价），
操作系统显示名与物理核心数走 CIM，失败降级。

用法:
  powershell -NoProfile -ExecutionPolicy Bypass -File sysinfo.ps1

退出码: 0=ok 1=error。stdout 只输出 JSON 信封。
#>
$ErrorActionPreference = 'Continue'
Import-Module $PSScriptRoot/common.psm1 -Force -DisableNameChecking

$osName = ''
$cores = 0
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $osName = ("$($os.Caption)" -replace '^Microsoft\s*', '').Trim() + " ($($os.Version))"
    if ($cpu) { $cores = [int]$cpu.NumberOfCores }
} catch { }
if (-not $osName) { $osName = "Windows $([Environment]::OSVersion.Version)" }

$cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
$cpuInfo = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
$threads = [Environment]::ProcessorCount
if (-not $cores) { $cores = $threads }

$memTotalGB = 0; $memFreeGB = 0
if ($cs) {
    $memTotalGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    try {
        $os2 = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        $memFreeGB = [math]::Round($os2.FreePhysicalMemory * 1KB / 1GB, 1)
    } catch { }
}

Write-Result -Status ok -Data ([ordered]@{
    os = $osName
    arch = $env:PROCESSOR_ARCHITECTURE
    processor = $(if ($cpuInfo) { "$($cpuInfo.Name)".Trim() } else { '—' })
    cpu_cores = $cores; cpu_threads = $threads
    cpu_ghz = $(if ($cpuInfo) { [math]::Round($cpuInfo.MaxClockSpeed / 1000, 2) } else { 0 })
    mem_total_gb = $memTotalGB; mem_free_gb = $memFreeGB
    computer_name = $env:COMPUTERNAME; user = $env:USERNAME
    updated_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
})
