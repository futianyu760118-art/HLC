# =====================================================================
# 恒聘通 - 简历附件卷恢复脚本
#
# ⚠️ 警告：本脚本会操作本地 backend-python/uploads 目录！
#         默认是 MERGE 模式（仅补回缺失文件，不删除新增文件），
#         若你要完全替换，请加 -ReplaceAll 显式开启。
#
# 设计原则：
#   - 强制二次输入 "YES" 才会执行
#   - 默认 merge：只把备份里有、目录里没有的文件还原回去，保护后来新上传的简历
#   - 完整替换模式 (-ReplaceAll)：先清空目录再解包，需要再次输入 "REPLACE-ALL"
#   - 操作前先列出归档信息，避免选错文件
#
# 用法：
#   # 1) 列出可用备份
#   .\restore-uploads.ps1 -List
#
#   # 2) merge 模式：从指定备份恢复缺失文件
#   .\restore-uploads.ps1 -ArchivePath C:\hengpintong-backups\uploads\uploads-20260601_030000.tar.gz
#
#   # 3) 完整替换（危险，不可逆）
#   .\restore-uploads.ps1 -ArchivePath ... -ReplaceAll
# =====================================================================

[CmdletBinding()]
param(
    [string]$ArchivePath,
    [string]$TargetDir = $(Join-Path $PSScriptRoot 'backend-python' 'uploads'),
    [string]$BackupDir = $(if ($env:BACKUP_DIR) { Join-Path $env:BACKUP_DIR 'uploads' } else { 'C:\hengpintong-backups\uploads' }),
    [switch]$ReplaceAll,
    [switch]$List
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) {
    Write-Host "[restore] $msg" -ForegroundColor Cyan
}
function Write-OK($msg) {
    Write-Host "[restore] $msg" -ForegroundColor Green
}
function Write-Warn2($msg) {
    Write-Host "[restore] $msg" -ForegroundColor Yellow
}

# --- 列出可用备份 ---
if ($List) {
    if (-not (Test-Path $BackupDir)) {
        Write-Warn2 "备份目录不存在: $BackupDir"
        exit 0
    }
    Write-Host "可用备份（按时间倒序）：" -ForegroundColor Cyan
    Get-ChildItem $BackupDir -Filter 'uploads-*.tar.gz' -File |
        Sort-Object LastWriteTime -Descending |
        Format-Table @{N='归档名';E={$_.Name}},
                     @{N='大小(MB)';E={[math]::Round($_.Length/1MB,2)};Alignment='Right'},
                     @{N='修改时间';E={$_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')}} -AutoSize
    exit 0
}

if (-not $ArchivePath) {
    throw '必须用 -ArchivePath 指定备份归档，或先用 -List 查看可用归档。'
}
if (-not (Test-Path $ArchivePath)) {
    throw "归档文件不存在: $ArchivePath"
}

# --- 前置校验 ---
Write-Step "校验目标目录: $TargetDir"

if (-not (Test-Path $TargetDir)) {
    Write-Step "目标目录不存在，将自动创建: $TargetDir"
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}

# --- 显示信息并请求确认 ---
$archiveItem = Get-Item $ArchivePath
$archiveName = Split-Path -Leaf $ArchivePath
$archiveSize = [math]::Round($archiveItem.Length / 1MB, 2)
$mode = if ($ReplaceAll) { 'REPLACE-ALL (先清空目录再解包)' } else { 'MERGE (仅补回缺失文件)' }

Write-Host ""
Write-Host "================ 恢复操作确认 ================" -ForegroundColor Yellow
Write-Host "归档:    $ArchivePath" -ForegroundColor Yellow
Write-Host "大小:    $archiveSize MB ($($archiveItem.LastWriteTime))" -ForegroundColor Yellow
Write-Host "目标:    $TargetDir" -ForegroundColor Yellow
Write-Host "模式:    $mode" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Yellow

if ($ReplaceAll) {
    Write-Host ""
    Write-Host "⚠️  REPLACE-ALL 模式将先删除目录里的所有文件！" -ForegroundColor Red
    Write-Host "    后续上传的、备份后新加的文件会一并丢失。" -ForegroundColor Red
    $confirm1 = Read-Host "请输入 REPLACE-ALL 继续，其它任何输入将中止"
    if ($confirm1 -ne 'REPLACE-ALL') { Write-Host "已中止。" -ForegroundColor Yellow; exit 0 }
} else {
    Write-Host ""
    $confirm1 = Read-Host "请输入 YES 继续，其它任何输入将中止"
    if ($confirm1 -ne 'YES') { Write-Host "已中止。" -ForegroundColor Yellow; exit 0 }
}

# --- 执行恢复 ---
$sw = [System.Diagnostics.Stopwatch]::StartNew()

if ($ReplaceAll) {
    Write-Step "清空目标目录..."
    Get-ChildItem -Path $TargetDir -Recurse -Force | Remove-Item -Recurse -Force
}

Write-Step "解包归档到目标目录..."
# --keep-old-files (-k): merge 模式时，遇到同名文件保留现有的（不覆盖新数据）
# REPLACE-ALL 模式下目录已空，无需此选项
if ($ReplaceAll) {
    tar -xzf $ArchivePath -C $TargetDir 2>&1 | ForEach-Object { Write-Host "  $_" }
} else {
    tar -xzkf $ArchivePath -C $TargetDir 2>&1 | ForEach-Object { Write-Host "  $_" }
}

if ($LASTEXITCODE -ne 0) {
    throw "tar 解包失败，退出码 $LASTEXITCODE"
}

$sw.Stop()

# --- 统计 ---
$count = (Get-ChildItem -Path $TargetDir -File -Recurse | Measure-Object).Count
Write-OK ("恢复完成，目录内当前文件数: {0} (耗时 {1:N1}s)" -f $count, $sw.Elapsed.TotalSeconds)
Write-Host ""
Write-Host "下一步：刷新前端简历管理页面，重新测试附件下载。" -ForegroundColor Cyan
Write-Host "如果容器正在运行，文件已通过 bind mount 自动生效，无需重启。" -ForegroundColor Cyan
