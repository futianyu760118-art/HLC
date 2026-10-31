# =====================================================================
# 恒聘通 - 简历附件卷备份脚本
#
# 用途：把本地 backend-python/uploads 目录（bind mount 源）打包为 .tar.gz，
#       归档到宿主机指定目录，并执行轮转保留策略。
#
# 设计原则：
#   - 直接读取本地目录，无需 Docker 运行
#   - 用一次性 alpine 容器跑 tar（如 Docker 可用），或 PowerShell 7 内置 Compress-Archive
#   - 默认保留：近 14 天每日 + 每月 1 号的快照保留 6 个月
#   - 失败抛错并退出码非 0，便于任务计划程序识别
#
# 用法：
#   .\backup-uploads.ps1                          # 默认目录 C:\hengpintong-backups\uploads
#   .\backup-uploads.ps1 -BackupDir D:\backups    # 指定目录
#   $env:BACKUP_DIR='D:\backups'; .\backup-uploads.ps1
# =====================================================================

[CmdletBinding()]
param(
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { Join-Path $env:BACKUP_DIR 'uploads' } else { 'C:\hengpintong-backups\uploads' }),
    [string]$SourceDir = $(Join-Path $PSScriptRoot 'backend-python' 'uploads'),
    [int]$RetainDays = 14,
    [int]$RetainMonthlyMonths = 6
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) {
    Write-Host "[backup-uploads] $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "[backup-uploads] $msg" -ForegroundColor Green
}

function Write-Warn2($msg) {
    Write-Host "[backup-uploads] $msg" -ForegroundColor Yellow
}

# --- 1. 前置校验 ---
Write-Step "校验源目录: $SourceDir"

if (-not (Test-Path $SourceDir)) {
    throw "uploads 源目录不存在: $SourceDir"
}
$fileCount = (Get-ChildItem -Path $SourceDir -File -Recurse | Measure-Object).Count
if ($fileCount -eq 0) {
    Write-Warn2 "源目录为空，跳过本次备份。"
    return
}
Write-Step "源目录包含 $fileCount 个文件"

# --- 2. 准备备份目录 ---
if (-not (Test-Path $BackupDir)) {
    Write-Step "创建备份目录: $BackupDir"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$archiveName = "uploads-$stamp.tar.gz"
$archivePath = Join-Path $BackupDir $archiveName

# --- 3. 执行备份 ---
Write-Step "打包 '$SourceDir' -> $archivePath"
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# 尝试用 Docker alpine 容器跑 tar（压缩率更好），回退到 PowerShell tar
$useDocker = $false
$dockerCheck = docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -eq 0 -and $dockerCheck) {
    $useDocker = $true
}

if ($useDocker) {
    $srcMount = ($SourceDir -replace '\\', '/') + ':/source:ro'
    $dstMount = ($BackupDir -replace '\\', '/') + ':/backup'
    docker run --rm -v "$srcMount" -v "$dstMount" alpine tar czf "/backup/$archiveName" -C /source . 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path $archivePath) { Remove-Item $archivePath -ErrorAction SilentlyContinue }
        throw "tar 打包失败，退出码 $LASTEXITCODE"
    }
} else {
    # Fallback: 用系统 tar（Windows 10+ 自带）
    Write-Step "Docker 不可用，使用系统 tar..."
    tar -czf $archivePath -C $SourceDir . 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path $archivePath) { Remove-Item $archivePath -ErrorAction SilentlyContinue }
        throw "tar 打包失败，退出码 $LASTEXITCODE"
    }
}

$sw.Stop()

if (-not (Test-Path $archivePath)) {
    throw "备份完成但找不到归档文件：$archivePath"
}

$sizeMB = [math]::Round((Get-Item $archivePath).Length / 1MB, 2)
Write-OK ("备份完成: {0} ({1} MB, 耗时 {2:N1}s)" -f $archiveName, $sizeMB, $sw.Elapsed.TotalSeconds)

# --- 4. 轮转策略 ---
Write-Step "应用轮转策略 (保留近 $RetainDays 天 + 每月1号 $RetainMonthlyMonths 个月)..."

$now = Get-Date
$cutoffDaily = $now.AddDays(-$RetainDays)
$cutoffMonthly = $now.AddMonths(-$RetainMonthlyMonths)
$removed = 0
$kept = 0

Get-ChildItem -Path $BackupDir -Filter 'uploads-*.tar.gz' -File | ForEach-Object {
    $mtime = $_.LastWriteTime
    $isRecent = $mtime -ge $cutoffDaily
    $isMonthlyKeeper = ($mtime.Day -eq 1) -and ($mtime -ge $cutoffMonthly)

    if ($isRecent -or $isMonthlyKeeper) {
        $kept++
    } else {
        try {
            Remove-Item $_.FullName -Force
            $removed++
            Write-Host "  [pruned] $($_.Name) ($($mtime.ToString('yyyy-MM-dd')))" -ForegroundColor DarkGray
        } catch {
            Write-Warn2 "无法删除 $($_.Name): $_"
        }
    }
}

Write-OK ("轮转完成: 保留 {0} 份，清理 {1} 份" -f $kept, $removed)
Write-OK "全部完成 ✓"
