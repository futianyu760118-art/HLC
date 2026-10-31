# =====================================================================
# Dev uploads sync from production
#
# Purpose: After dev container rebuild, sync missing resume files from prod
#          Usage: .\sync-uploads-from-prod.ps1 [-Backup]
# =====================================================================

[CmdletBinding()]
param(
    [string]$ProdDir = "",
    [string]$DevDir = "",
    [string]$BackupDir = "D:\dev-uploads-backup",
    [switch]$Backup
)

# Resolve prod dir: explicit param > env var > default path
if (-not $ProdDir) {
    $ProdDir = $env:PROD_UPLOADS_DIR
    if (-not $ProdDir) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $ProdDir = Join-Path $desktop 'backend-python\uploads'
        # Fallback: scan desktop for the project
        if (-not (Test-Path $ProdDir)) {
            $candidates = Get-ChildItem -Path $desktop -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'backend-python\uploads') }
            if ($candidates) { $ProdDir = Join-Path $candidates[0].FullName 'backend-python\uploads' }
        }
    }
}
if (-not $DevDir) { $DevDir = Join-Path $PSScriptRoot 'backend-python\uploads' }

$ErrorActionPreference = 'Stop'

function W-Step($m) { Write-Host "[sync] $m" -ForegroundColor Cyan }
function W-OK($m)   { Write-Host "[sync] $m" -ForegroundColor Green }
function W-Warn($m) { Write-Host "[sync] $m" -ForegroundColor Yellow }

# --- 1. Validate ---
W-Step "Prod: $ProdDir"
if (-not (Test-Path $ProdDir)) {
    W-Warn "Prod uploads dir not found, skipping"
    return
}
if (-not (Test-Path $DevDir)) {
    New-Item -ItemType Directory -Path $DevDir -Force | Out-Null
}

$prodFiles = Get-ChildItem -Path $ProdDir -File -Recurse
$devFiles  = Get-ChildItem -Path $DevDir -File -Recurse -ErrorAction SilentlyContinue
W-Step "Prod: $($prodFiles.Count) files | Dev: $($devFiles.Count) files"

# --- 2. Optional backup ---
if ($Backup) {
    if (-not (Test-Path $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $archive = Join-Path $BackupDir "dev-uploads-$stamp.tar.gz"
    W-Step "Backing up dev uploads -> $archive"
    tar -czf $archive -C $DevDir . 2>&1 | ForEach-Object { Write-Host "  $_" }
    if (Test-Path $archive) {
        $sizeMB = [math]::Round((Get-Item $archive).Length / 1MB, 2)
        W-OK "Backup done: $sizeMB MB"
    }
    Get-ChildItem -Path $BackupDir -Filter 'dev-uploads-*.tar.gz' -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 7 |
        ForEach-Object { Remove-Item $_.FullName -Force; W-Warn "Pruned: $($_.Name)" }
}

# --- 3. Sync (copy only missing files) ---
$copied = 0
$skipped = 0
foreach ($pf in $prodFiles) {
    $relPath = $pf.FullName.Substring($ProdDir.Length).TrimStart('\','/')
    $destPath = Join-Path $DevDir $relPath
    if (Test-Path $destPath) {
        $skipped++
    } else {
        $destParent = Split-Path $destPath -Parent
        if (-not (Test-Path $destParent)) {
            New-Item -ItemType Directory -Path $destParent -Force | Out-Null
        }
        Copy-Item $pf.FullName $destPath -Force
        $copied++
    }
}

W-OK "Sync done: +$copied new, =$skipped existing"

# --- 4. Consistency check ---
$devAfter = (Get-ChildItem -Path $DevDir -File -Recurse).Count
if ($devAfter -ge $prodFiles.Count) {
    W-OK "OK: dev $devAfter >= prod $($prodFiles.Count)"
} else {
    W-Warn "WARN: dev ($devAfter) < prod ($($prodFiles.Count)), check needed"
}
