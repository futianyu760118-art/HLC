# =====================================================================
# Safe backend restart with uploads protection
#
# Replaces direct `docker restart`. Verifies uploads file count before/after.
# If files drop >10%, auto-restores from prod.
#
# Usage:
#   .\safe-restart.ps1              # normal restart with validation
#   .\safe-restart.ps1 -Rebuild     # rebuild image (high risk, syncs prod first)
# =====================================================================

[CmdletBinding()]
param(
    [switch]$Rebuild,
    [string]$UploadsDir = ""
)

if (-not $UploadsDir) { $UploadsDir = Join-Path $PSScriptRoot 'backend-python\uploads' }

$ErrorActionPreference = 'Stop'
$dockerExe = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"

function Count-Files($path) {
    if (Test-Path $path) {
        return (Get-ChildItem -Path $path -File -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count
    }
    return 0
}
function W-Step($m) { Write-Host "[safe-restart] $m" -ForegroundColor Cyan }
function W-OK($m)   { Write-Host "[safe-restart] $m" -ForegroundColor Green }
function W-Err($m)  { Write-Host "[safe-restart] $m" -ForegroundColor Red }
function Get-DotEnvValue([string]$Name, [string]$DefaultValue) {
    $envPath = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path $envPath)) { return $DefaultValue }
    $content = Get-Content -LiteralPath $envPath -Raw
    $match = [regex]::Match($content, "(?m)^\s*$([regex]::Escape($Name))\s*=\s*(.+?)\s*$")
    if (-not $match.Success) { return $DefaultValue }
    return $match.Groups[1].Value.Trim().Trim('"').Trim("'")
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

$projectName = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { Get-DotEnvValue 'COMPOSE_PROJECT_NAME' 'hengpintong-saas-preview' }
$nginxPort = if ($env:NGINX_PORT) { $env:NGINX_PORT } else { Get-DotEnvValue 'NGINX_PORT' '18280' }
Assert-SaasTarget -ProjectName $projectName -Port $nginxPort
$env:COMPOSE_PROJECT_NAME = $projectName
$backendContainer = "$projectName-backend-1"

# --- 1. Snapshot before ---
$before = Count-Files $UploadsDir
W-Step "Before restart: $before files in uploads"

if ($before -eq 0) {
    W-Err "uploads is EMPTY! Files may be lost. Aborting."
    W-Err "Run .\sync-uploads-from-prod.ps1 first to restore from prod."
    exit 1
}

# --- 2. Restart ---
if ($Rebuild) {
    W-Step "Rebuilding backend image (high risk)..."
    W-Step "Auto-syncing prod uploads before rebuild..."
    $syncScript = Join-Path $PSScriptRoot 'sync-uploads-from-prod.ps1'
    & $syncScript -Backup
    Push-Location $PSScriptRoot
    & $dockerExe compose -p $projectName build backend 2>&1 | ForEach-Object { Write-Host "  $_" }
    Pop-Location
}

W-Step "Restarting backend container..."
& $dockerExe restart $backendContainer 2>&1 | ForEach-Object { Write-Host "  $_" }

# --- 3. Wait for health ---
W-Step "Waiting for backend startup..."
Start-Sleep -Seconds 8

# --- 4. Verify after ---
$after = Count-Files $UploadsDir
W-Step "After restart: $after files in uploads"

if ($after -lt $before) {
    $lost = $before - $after
    $pct = [math]::Round($lost / $before * 100, 1)
    W-Err "WARNING: $lost files lost ($pct%)!"
    if ($pct -ge 10) {
        W-Err "Loss >= 10%, auto-restoring from prod..."
        $syncScript = Join-Path $PSScriptRoot 'sync-uploads-from-prod.ps1'
        & $syncScript
        W-OK "Restore complete, please re-verify."
    } else {
        W-Err "Minor loss. Run sync-uploads-from-prod.ps1 to check."
    }
} else {
    W-OK "File integrity OK: $after files (was $before)."
}

# --- 5. Health check ---
$health = & $dockerExe inspect $backendContainer --format '{{.State.Health.Status}}' 2>$null
if ($health -eq 'healthy' -or $health -eq 'starting') {
    W-OK "Container status: $health"
} else {
    W-Err "Container status abnormal: $health"
}
