# =====================================================================
# 恒聘通 - 注册 / 卸载每日定时备份任务
#
# 用途：在 Windows 任务计划程序里注册或卸载 'HengpintongDailyBackup' 任务。
#       需要管理员权限。脚本会自动检测并提示。
#
# 用法：
#   .\setup-scheduled-backup.ps1                  # 注册（默认凌晨 3:00）
#   .\setup-scheduled-backup.ps1 -RunAt '02:30'   # 指定时间
#   .\setup-scheduled-backup.ps1 -Unregister      # 卸载
#   .\setup-scheduled-backup.ps1 -TestRun         # 注册后立即跑一次验证
# =====================================================================

[CmdletBinding()]
param(
    [string]$TaskName = 'HengpintongDailyBackup',
    [string]$RunAt = '03:00',
    [switch]$Unregister,
    [switch]$TestRun
)

$ErrorActionPreference = 'Stop'

# --- 管理员权限自检 ---
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "[NEED ADMIN] 当前不是管理员身份，无法注册任务计划。" -ForegroundColor Red
    Write-Host ""
    Write-Host "请按以下任一方式以管理员身份重跑：" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  方式 A (推荐) - 在当前窗口提升执行：" -ForegroundColor Cyan
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($Unregister) { $argList += '-Unregister' }
    if ($TestRun)    { $argList += '-TestRun' }
    if ($RunAt -ne '03:00') { $argList += @('-RunAt', $RunAt) }
    if ($TaskName -ne 'HengpintongDailyBackup') { $argList += @('-TaskName', $TaskName) }
    $cmdString = 'Start-Process pwsh -Verb RunAs -ArgumentList ' +
                 (($argList | ForEach-Object { "'$_'" }) -join ',')
    Write-Host "    $cmdString" -ForegroundColor White
    Write-Host ""
    Write-Host "  方式 B - 在开始菜单搜 'pwsh'，右键 -> 以管理员身份运行 -> cd 到本目录 -> 重新执行本脚本" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

$scriptDir = Split-Path -Parent $PSCommandPath
$backupScript = Join-Path $scriptDir 'backup-all.ps1'

if (-not (Test-Path $backupScript)) {
    throw "找不到 backup-all.ps1，预期路径: $backupScript"
}

# --- 卸载分支 ---
if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "[INFO] 任务 '$TaskName' 不存在，无需卸载。" -ForegroundColor Yellow
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] 任务 '$TaskName' 已卸载。" -ForegroundColor Green
    exit 0
}

# --- pwsh 路径 ---
$pwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshPath) {
    $pwshPath = 'C:\Program Files\PowerShell\7\pwsh.exe'
    if (-not (Test-Path $pwshPath)) {
        throw '找不到 pwsh.exe（PowerShell 7）。请先安装：winget install Microsoft.PowerShell'
    }
}

Write-Host "[INFO] 使用 PowerShell: $pwshPath" -ForegroundColor Cyan
Write-Host "[INFO] 备份脚本: $backupScript" -ForegroundColor Cyan
Write-Host "[INFO] 执行时间: 每日 $RunAt" -ForegroundColor Cyan

# --- 如已存在则先删除 ---
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] 检测到同名任务，先卸载旧的..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# --- 构造 Action / Trigger / Settings ---
$action = New-ScheduledTaskAction `
    -Execute $pwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backupScript`"" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At $RunAt

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# 以当前登录账户的交互会话运行。
# 注意：Docker Desktop 通常依赖当前用户会话；S4U/服务账户模式下可能访问不到 Docker daemon。
# 因此这里使用 Interactive，要求服务器保持该用户登录状态。
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description '恒聘通每日备份 uploads 卷 + MySQL；详见 HRM_UPGRADE_NOTES.md 灾备小节' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal | Out-Null

Write-Host ""
Write-Host "[OK] 任务 '$TaskName' 注册成功 ✓" -ForegroundColor Green
Write-Host ""

# --- 显示任务信息 ---
$task = Get-ScheduledTask -TaskName $TaskName
$info = $task | Get-ScheduledTaskInfo
Write-Host "任务详情：" -ForegroundColor Cyan
Write-Host ("  状态:         {0}" -f $task.State)
Write-Host ("  下次运行:     {0}" -f $info.NextRunTime)
Write-Host ("  执行用户:     {0}" -f $task.Principal.UserId)
Write-Host ("  运行权限:     {0}" -f $task.Principal.RunLevel)

# --- 立即试跑（可选）---
if ($TestRun) {
    Write-Host ""
    Write-Host "[TEST] 立即触发一次任务以验证..." -ForegroundColor Yellow
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $afterTest = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
    Write-Host ("[TEST] 上次运行时间: {0}, 上次结果代码: 0x{1:X}" -f $afterTest.LastRunTime, $afterTest.LastTaskResult) -ForegroundColor Cyan
    Write-Host "[TEST] 任务已在后台异步运行，几秒后查看 C:\hengpintong-backups\logs\ 下最新日志即可。" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "管理命令：" -ForegroundColor Cyan
Write-Host "  查看状态:  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo" -ForegroundColor White
Write-Host "  手动触发:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
Write-Host "  卸载任务:  .\setup-scheduled-backup.ps1 -Unregister" -ForegroundColor White
Write-Host ""
