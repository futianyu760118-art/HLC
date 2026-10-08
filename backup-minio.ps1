# =====================================================================
# 恒聘通 - MinIO 对象存储备份脚本
#
# 用途：把 docker-compose 的 minio-data volume 打包为 .tar.gz。
#       这只读取 volume，不停止容器，不修改线上数据。
#
# 用法：
#   .\backup-minio.ps1
#   .\backup-minio.ps1 -BackupDir D:\backups\minio
#   .\backup-minio.ps1 -VolumeName hengpintong-saas-preview_minio-data
# =====================================================================

[CmdletBinding()]
param(
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { Join-Path $env:BACKUP_DIR 'minio' } else { 'C:\hengpintong-backups\minio' }),
    [string]$VolumeName = $(if ($env:MINIO_VOLUME_NAME) { $env:MINIO_VOLUME_NAME } elseif ($env:COMPOSE_PROJECT_NAME) { "$($env:COMPOSE_PROJECT_NAME)_minio-data" } else { 'hengpintong-saas-preview_minio-data' }),
    [int]$RetainDays = 14,
    [int]$RetainMonthlyMonths = 6
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) {
    Write-Host "[backup-minio] $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "[backup-minio] $msg" -ForegroundColor Green
}

function Write-Warn2($msg) {
    Write-Host "[backup-minio] $msg" -ForegroundColor Yellow
}
function Assert-SaasTarget {
    param([string]$ProjectName, [string]$Port)
    if ($ProjectName -ne 'hengpintong-saas-preview') {
        throw "Refusing to operate on non-SaaS project: $ProjectName"
    }
    if ($Port -and $Port -ne '18280') {
        throw "Refusing to operate on non-SaaS port: $Port"
    }
}

Write-Step "校验 Docker 和 MinIO volume: $VolumeName"

$projectName = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { 'hengpintong-saas-preview' }
Assert-SaasTarget -ProjectName $projectName
if ($VolumeName -ne "${projectName}_minio-data") {
    throw "Refusing to operate on MinIO volume outside SaaS project: $VolumeName"
}

$dockerCheck = docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $dockerCheck) {
    throw "Docker 不可用，无法备份 MinIO volume"
}

$volumeExists = docker volume ls --format '{{.Name}}' | Where-Object { $_ -eq $VolumeName }
if (-not $volumeExists) {
    throw "找不到 MinIO volume: $VolumeName。可通过 -VolumeName 指定实际名称。"
}

if (-not (Test-Path $BackupDir)) {
    Write-Step "创建备份目录: $BackupDir"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$archiveName = "minio-$stamp.tar.gz"
$archivePath = Join-Path $BackupDir $archiveName

Write-Step "打包 volume '$VolumeName' -> $archivePath"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$dstMount = ($BackupDir -replace '\\', '/') + ':/backup'
docker run --rm -v "${VolumeName}:/source:ro" -v "$dstMount" alpine tar czf "/backup/$archiveName" -C /source . 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $archivePath) { Remove-Item $archivePath -ErrorAction SilentlyContinue }
    throw "MinIO volume 打包失败，退出码 $LASTEXITCODE"
}
$sw.Stop()

if (-not (Test-Path $archivePath)) {
    throw "备份完成但找不到归档文件：$archivePath"
}

$sizeMB = [math]::Round((Get-Item $archivePath).Length / 1MB, 2)
Write-OK ("备份完成: {0} ({1} MB, 耗时 {2:N1}s)" -f $archiveName, $sizeMB, $sw.Elapsed.TotalSeconds)

Write-Step "应用轮转策略 (保留近 $RetainDays 天 + 每月1号 $RetainMonthlyMonths 个月)..."
$now = Get-Date
$cutoffDaily = $now.AddDays(-$RetainDays)
$cutoffMonthly = $now.AddMonths(-$RetainMonthlyMonths)
$removed = 0
$kept = 0

Get-ChildItem -Path $BackupDir -Filter 'minio-*.tar.gz' -File | ForEach-Object {
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
Write-OK "全部完成"
