# =====================================================================
# 恒聘通 - 备份编排脚本
#
# 用途：一次性调用 uploads、minio 和 mysql 三个备份脚本，并写一份合并日志。
#       这是给 Windows 任务计划程序定时跑的"对外接口"。
#
# 用法：
#   .\backup-all.ps1
#   .\backup-all.ps1 -BackupDir D:\backups
#
# 任务计划程序注册（PowerShell 管理员）：
#   见 HRM_UPGRADE_NOTES.md「灾备 / 数据持久化」一节
#
# 退出码：0=全部成功，1=任一步骤失败
# =====================================================================

[CmdletBinding()]
param(
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { $env:BACKUP_DIR } else { 'C:\hengpintong-backups' })
)

# 注意：本脚本不用 $ErrorActionPreference='Stop'，因为我们要让两步都尝试跑完，
# 任一失败都记录但不互相影响。最终用 $hadError 汇总。

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $BackupDir 'logs'
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path $logDir "backup-all-$stamp.log"

# 把后续所有输出同时写到控制台和日志文件
Start-Transcript -Path $logFile -Append | Out-Null

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " 恒聘通 - 定时备份 (started $stamp)" -ForegroundColor Cyan
Write-Host " 备份根目录: $BackupDir" -ForegroundColor Cyan
Write-Host " Compose project: $env:COMPOSE_PROJECT_NAME" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

$totalSw = [System.Diagnostics.Stopwatch]::StartNew()
$hadError = $false

# --- uploads ---
Write-Host ""
Write-Host ">>> 步骤 1/3: uploads 本地目录" -ForegroundColor Yellow
try {
    & (Join-Path $scriptDir 'backup-uploads.ps1') -BackupDir (Join-Path $BackupDir 'uploads')
    if ($LASTEXITCODE -ne 0) { throw "backup-uploads.ps1 退出码 $LASTEXITCODE" }
} catch {
    Write-Host "[FAIL] uploads 备份失败: $_" -ForegroundColor Red
    $hadError = $true
}

# --- minio ---
Write-Host ""
Write-Host ">>> 步骤 2/3: MinIO 对象存储" -ForegroundColor Yellow
try {
    & (Join-Path $scriptDir 'backup-minio.ps1') -BackupDir (Join-Path $BackupDir 'minio')
    if ($LASTEXITCODE -ne 0) { throw "backup-minio.ps1 退出码 $LASTEXITCODE" }
} catch {
    Write-Host "[FAIL] MinIO 备份失败: $_" -ForegroundColor Red
    $hadError = $true
}

# --- mysql ---
Write-Host ""
Write-Host ">>> 步骤 3/3: MySQL" -ForegroundColor Yellow
try {
    & (Join-Path $scriptDir 'backup-mysql.ps1') -BackupDir (Join-Path $BackupDir 'mysql')
    if ($LASTEXITCODE -ne 0) { throw "backup-mysql.ps1 退出码 $LASTEXITCODE" }
} catch {
    Write-Host "[FAIL] MySQL 备份失败: $_" -ForegroundColor Red
    $hadError = $true
}

$totalSw.Stop()

# --- 汇总 ---
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
if ($hadError) {
    Write-Host " 完成（部分失败），耗时 $([math]::Round($totalSw.Elapsed.TotalSeconds, 1)) 秒" -ForegroundColor Red
    Write-Host " 日志: $logFile" -ForegroundColor Red
    Write-Host "================================================" -ForegroundColor Cyan
    Stop-Transcript | Out-Null
    # 同时清理一下旧日志，保留 30 天
    Get-ChildItem $logDir -Filter 'backup-all-*.log' -File |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host " 全部成功 ✓ 耗时 $([math]::Round($totalSw.Elapsed.TotalSeconds, 1)) 秒" -ForegroundColor Green
Write-Host " 日志: $logFile" -ForegroundColor Green

# 简单容量统计
$uploadsTotal = (Get-ChildItem (Join-Path $BackupDir 'uploads') -Filter '*.tar.gz' -File -ErrorAction SilentlyContinue |
                 Measure-Object Length -Sum).Sum
$minioTotal = (Get-ChildItem (Join-Path $BackupDir 'minio') -Filter '*.tar.gz' -File -ErrorAction SilentlyContinue |
               Measure-Object Length -Sum).Sum
$mysqlTotal = (Get-ChildItem (Join-Path $BackupDir 'mysql') -Filter '*.sql.gz' -File -ErrorAction SilentlyContinue |
               Measure-Object Length -Sum).Sum
if ($uploadsTotal) { Write-Host (" uploads 累计占用: {0:N1} MB" -f ($uploadsTotal/1MB)) -ForegroundColor DarkGray }
if ($minioTotal)   { Write-Host (" minio   累计占用: {0:N1} MB" -f ($minioTotal/1MB))   -ForegroundColor DarkGray }
if ($mysqlTotal)   { Write-Host (" mysql   累计占用: {0:N1} MB" -f ($mysqlTotal/1MB))   -ForegroundColor DarkGray }
Write-Host "================================================" -ForegroundColor Cyan

Stop-Transcript | Out-Null

# 清理 30 天前的日志
Get-ChildItem $logDir -Filter 'backup-all-*.log' -File |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit 0
