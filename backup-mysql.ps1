# =====================================================================
# 恒聘通 - MySQL 数据库备份脚本
#
# 用途：用 mysqldump 在容器内导出整库，gzip 压缩后用 docker cp 拉出到宿主机，
#       同 uploads 备份一样应用轮转保留策略。
#
# 设计原则：
#   - 凭据从容器内环境变量取，PS 脚本里不出现明文密码
#   - dump 在容器 /tmp 完成后立即 cp 出来并删除容器内副本，避免泄露
#   - --single-transaction --quick：保证大表导出一致性且不撑爆内存
#   - --routines --triggers：把存储过程/触发器一并备份（防漏）
#
# 用法：
#   .\backup-mysql.ps1                          # 默认 C:\hengpintong-backups\mysql
#   .\backup-mysql.ps1 -BackupDir D:\backups
# =====================================================================

[CmdletBinding()]
param(
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { Join-Path $env:BACKUP_DIR 'mysql' } else { 'C:\hengpintong-backups\mysql' }),
    [string]$ContainerName = $(if ($env:MYSQL_CONTAINER_NAME) { $env:MYSQL_CONTAINER_NAME } elseif ($env:COMPOSE_PROJECT_NAME) { "$($env:COMPOSE_PROJECT_NAME)-mysql-1" } else { 'hengpintong-saas-preview-mysql-1' }),
    [int]$RetainDays = 14,
    [int]$RetainMonthlyMonths = 6
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) {
    Write-Host "[backup-mysql] $msg" -ForegroundColor Cyan
}
function Write-OK($msg) {
    Write-Host "[backup-mysql] $msg" -ForegroundColor Green
}
function Write-Warn2($msg) {
    Write-Host "[backup-mysql] $msg" -ForegroundColor Yellow
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

# --- 1. 前置校验 ---
Write-Step "校验 Docker 与 MySQL 容器..."

$projectName = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { 'hengpintong-saas-preview' }
Assert-SaasTarget -ProjectName $projectName
if ($ContainerName -notlike "$projectName-mysql-*") {
    throw "Refusing to operate on MySQL container outside SaaS project: $ContainerName"
}

$dockerCheck = docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $dockerCheck) {
    throw 'Docker 未运行或不可访问。'
}

$containerStatus = docker inspect $ContainerName --format '{{.State.Status}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "MySQL 容器 '$ContainerName' 不存在。请用 -ContainerName 指定。"
}
if ($containerStatus -ne 'running') {
    throw "MySQL 容器状态为 '$containerStatus'，未运行。"
}

# --- 2. 准备目录 ---
if (-not (Test-Path $BackupDir)) {
    Write-Step "创建备份目录: $BackupDir"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dumpName = "mysql-$stamp.sql.gz"
$containerTmp = "/tmp/$dumpName"
$dumpPath = Join-Path $BackupDir $dumpName

# --- 3. 容器内 dump ---
Write-Step "在容器内执行 mysqldump（凭据从容器环境变量取，不在脚本里出现明文）..."
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# 整段命令用单引号包裹 -> PowerShell 不展开 $，所有 $VAR 都让 sh 自己解析
$dumpCmd = 'mysqldump --single-transaction --quick --routines --triggers ' +
           '-u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" 2>/tmp/dump.err | gzip > ' + $containerTmp +
           '; ec=$?; if [ $ec -ne 0 ]; then cat /tmp/dump.err >&2; rm -f ' + $containerTmp + '; exit $ec; fi'

docker exec $ContainerName sh -c $dumpCmd 2>&1 | ForEach-Object {
    if ($_) { Write-Host "  $_" -ForegroundColor DarkYellow }
}

if ($LASTEXITCODE -ne 0) {
    throw "mysqldump 失败，退出码 $LASTEXITCODE"
}

# --- 4. 拷贝出来并清理容器内副本 ---
Write-Step "从容器拷出 dump 文件..."
docker cp "${ContainerName}:${containerTmp}" $dumpPath 2>&1 | ForEach-Object {
    if ($_) { Write-Host "  $_" -ForegroundColor DarkGray }
}
if ($LASTEXITCODE -ne 0) {
    throw "docker cp 失败"
}

docker exec $ContainerName rm -f $containerTmp 2>$null | Out-Null

$sw.Stop()

if (-not (Test-Path $dumpPath)) {
    throw "备份完成但宿主机找不到文件：$dumpPath"
}

$sizeMB = [math]::Round((Get-Item $dumpPath).Length / 1MB, 2)
Write-OK ("dump 完成: {0} ({1} MB, 耗时 {2:N1}s)" -f $dumpName, $sizeMB, $sw.Elapsed.TotalSeconds)

# --- 5. 轮转 ---
Write-Step "应用轮转策略 (保留近 $RetainDays 天 + 每月1号 $RetainMonthlyMonths 个月)..."

$now = Get-Date
$cutoffDaily = $now.AddDays(-$RetainDays)
$cutoffMonthly = $now.AddMonths(-$RetainMonthlyMonths)
$removed = 0
$kept = 0

Get-ChildItem -Path $BackupDir -Filter 'mysql-*.sql.gz' -File | ForEach-Object {
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
