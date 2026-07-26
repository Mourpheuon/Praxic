# 即物穷理 Praxic —— Electron 壳构建脚本 (Windows PowerShell)
# 用法：.\scripts\build-electron.ps1
# 前置条件：Node.js >= 18, npm

param(
    [switch]$All,
    [switch]$Publish
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

$version = (Get-Content package.json | ConvertFrom-Json).version
Write-Host "========================================" -ForegroundColor Green
Write-Host "  即物穷理 Electron 壳构建  v$version" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# 1. Node.js 检查
Write-Host "[1/4] Node.js $(node --version)"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[错误] 未找到 Node.js，请安装 https://nodejs.org" -ForegroundColor Red
    exit 1
}

# 2. 安装依赖
Write-Host "[2/4] 安装 npm 依赖..."
npm install
if (Test-Path "siwu/web/package.json") {
    Write-Host "       安装前端依赖..."
    Set-Location siwu/web
    npm install
    Set-Location $projectRoot
}

# 3. 构建前端
Write-Host "[3/4] 构建前端（Vite）..."
if (Test-Path "siwu/web") {
    Set-Location siwu/web
    npx vite build
    Set-Location $projectRoot
    Write-Host "       前端构建完成 -> siwu/web/dist/"
} else {
    Write-Host "       siwu/web/ 不存在，跳过" -ForegroundColor Yellow
}

# 4. Electron Builder 打包
Write-Host "[4/4] 打包 Electron 应用..."
if ($Publish) {
    npx electron-builder --publish always
} elseif ($All) {
    npx electron-builder --win --mac --linux
} else {
    npx electron-builder
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  构建完成！产物目录: dist-electron/" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
