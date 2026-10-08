# =====================================================================
# 恒聘通 生产环境部署脚本
#
# 注意：.env 文件只需首次手动创建一次（cp .env.example .env 并填值）。
#       本脚本绝不会覆盖或重新生成 .env，确保 JWT_SECRET 等密钥稳定，
#       已登录用户的 token 在更新后仍然有效。
#
# 工作流：
#   0. 部署前自动备份 uploads 卷 + MySQL（多一层安全网）
#   1. 校验 .env 存在且无占位符
#   2. 构建前端到 dist-prod/
#   3. 重建后端镜像（保留 mysql 数据卷不动）
#   4. 重启 nginx 让新前端文件生效
#
# 参数：
#   -SkipBackup    跳过部署前备份（不推荐，仅紧急回滚等极端情况使用）
# =====================================================================

param(
    [switch]$SkipBackup
)

$ErrorActionPreference = 'Stop'

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  恒聘通 - 发布到生产环境" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 0) .env 校验和 SaaS 目标保护
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envPath)) {
    Write-Host ""
    Write-Host "[FATAL] 当前目录缺少 .env 文件。" -ForegroundColor Red
    Write-Host ""
    Write-Host "首次部署请执行：" -ForegroundColor Yellow
    Write-Host "  cp .env.example .env" -ForegroundColor White
    Write-Host "  然后用编辑器填入真实凭据（数据库密码、JWT_SECRET 等）" -ForegroundColor White
    Write-Host ""
    Write-Host "生成强随机密钥：" -ForegroundColor Yellow
    Write-Host '  python -c "import secrets; print(secrets.token_urlsafe(64))"' -ForegroundColor White
    Write-Host ""
    exit 1
}

$envContent = Get-Content -LiteralPath $envPath -Raw
if ($envContent -match 'PLEASE_CHANGE_ME') {
    Write-Host "[FATAL] .env 中仍包含占位符 PLEASE_CHANGE_ME，请先填入真实值。" -ForegroundColor Red
    exit 1
}

function Get-DotEnvValue([string]$Name, [string]$DefaultValue) {
    $match = [regex]::Match($envContent, "(?m)^\s*$([regex]::Escape($Name))\s*=\s*(.+?)\s*$")
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

$nginxPort = Get-DotEnvValue 'NGINX_PORT' '18280'
$projectName = Get-DotEnvValue 'COMPOSE_PROJECT_NAME' 'hengpintong-saas-preview'
$backendContainer = "${projectName}-backend-1"

Assert-SaasTarget -ProjectName $projectName -Port $nginxPort
$env:COMPOSE_PROJECT_NAME = $projectName

Write-Host "[OK] .env 校验通过，目标: $projectName / $nginxPort" -ForegroundColor Green

$previewRoot = Join-Path $PSScriptRoot 'outputs\saas-docker-preview'
$liveDist = Join-Path $previewRoot 'dist-prod'
$stagingDist = Join-Path $previewRoot 'dist-prod.staging'
$previousDist = Join-Path $previewRoot 'dist-prod.previous'
function Invoke-SaasCompose {
    param([string[]]$Arguments)
    & docker compose --env-file .env -p $projectName -f docker-compose.yml -f docker-compose.saas-preview.yml @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed: $($Arguments -join ' ')"
    }
}

function Assert-PreviewReady {
    for ($attempt = 1; $attempt -le 24; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://localhost:$nginxPort/api/health" -TimeoutSec 5
            $ready = Invoke-RestMethod -Uri "http://localhost:$nginxPort/api/ready" -TimeoutSec 5
            if ($health.ok -eq $true -and $ready.ok -eq $true -and $ready.db -eq 'up') {
                Write-Host "[OK] health/ready 通过（storage=$($ready.storage)）" -ForegroundColor Green
                return
            }
        } catch {
            # 服务启动窗口内继续轮询；超时后由调用方回滚并终止发布。
        }
        Start-Sleep -Seconds 5
    }
    throw "SaaS preview readiness failed at http://localhost:$nginxPort"
}

# 1) 部署前备份（uploads + mysql）— 多一层安全网
if (-not $SkipBackup) {
    Write-Host "`n[1/5] 部署前自动备份..." -ForegroundColor Yellow
    $backupScript = Join-Path $PSScriptRoot 'backup-all.ps1'
    if (Test-Path $backupScript) {
        try {
            & $backupScript
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[WARN] 备份脚本退出码 $LASTEXITCODE，请检查日志。" -ForegroundColor Yellow
                $continue = Read-Host '备份不完整，是否仍要继续部署? (y/n)'
                if ($continue -ne 'y' -and $continue -ne 'Y') { exit 1 }
            } else {
                Write-Host "[OK] 备份完成" -ForegroundColor Green
            }
        } catch {
            Write-Host "[WARN] 备份执行异常: $_" -ForegroundColor Yellow
            $continue = Read-Host '备份失败，是否仍要继续部署? (y/n)'
            if ($continue -ne 'y' -and $continue -ne 'Y') { exit 1 }
        }
    } else {
        Write-Host "[WARN] 找不到 backup-all.ps1，跳过备份步骤。" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[1/5] 已跳过备份 (-SkipBackup)" -ForegroundColor DarkGray
}

# 确认
$confirm = Read-Host "`n确认发布到生产环境? (y/n)"
if ($confirm -ne 'y' -and $confirm -ne 'Y') {
    Write-Host "已取消发布" -ForegroundColor Yellow
    exit 0
}

# 2) 构建到 staging，成功后再切换 live 目录
Write-Host "`n[2/5] 构建前端 -> $stagingDist" -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $previewRoot | Out-Null
if (Test-Path $stagingDist) { Remove-Item -LiteralPath $stagingDist -Recurse -Force }
npm ci --silent
if ($LASTEXITCODE -ne 0) { throw "npm ci 失败" }
npx tsc -b --pretty false
if ($LASTEXITCODE -ne 0) { throw "TypeScript 构建失败" }
npx vite build --outDir $stagingDist
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
if (-not (Test-Path (Join-Path $stagingDist 'index.html'))) { throw "staging 构建缺少 index.html" }
Write-Host "[OK] staging 前端构建完成" -ForegroundColor Green

# 3-5) 目标证明、原子切换、重建和就绪验证；任一步失败都 rollback 恢复旧前端。
$swapped = $false
try {
    Write-Host "`n[3/5] 证明 Docker 目标..." -ForegroundColor Yellow
    Invoke-SaasCompose @('config', '--services') | Out-Null
    Invoke-SaasCompose @('ps')

    if (Test-Path $previousDist) { Remove-Item -LiteralPath $previousDist -Recurse -Force }
    if (Test-Path $liveDist) { Move-Item -LiteralPath $liveDist -Destination $previousDist }
    Move-Item -LiteralPath $stagingDist -Destination $liveDist
    $swapped = $true

    Write-Host "`n[4/5] 重建后端并重载 Nginx..." -ForegroundColor Yellow
    Invoke-SaasCompose @('up', '-d', '--build', 'backend')
    Invoke-SaasCompose @('up', '-d', '--force-recreate', 'nginx')

    Write-Host "`n[5/5] 等待 SaaS preview 就绪..." -ForegroundColor Yellow
    Assert-PreviewReady
    if (Test-Path $previousDist) { Remove-Item -LiteralPath $previousDist -Recurse -Force }
} catch {
    Write-Host "[FATAL] 发布失败，开始回滚: $_" -ForegroundColor Red
    if ($swapped) {
        if (Test-Path $liveDist) { Move-Item -LiteralPath $liveDist -Destination $stagingDist -Force }
        if (Test-Path $previousDist) { Move-Item -LiteralPath $previousDist -Destination $liveDist -Force }
        try { Invoke-SaasCompose @('up', '-d', '--force-recreate', 'nginx') } catch { Write-Host "[FATAL] Nginx 回滚失败: $_" -ForegroundColor Red }
    }
    throw
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  SaaS preview 发布完成" -ForegroundColor Green
Write-Host "  访问地址: http://localhost:$nginxPort" -ForegroundColor Green
Write-Host "  已登录用户无需重新登录（JWT_SECRET 未变）" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
