# 即物穷理 Praxic —— 后端 exe 闸门检查
# 用途：检查 PyInstaller 后端存在且健康接口、页面、静态资源可用，再允许打包。
# 被 package.json 的 electron:build 和 scripts/build-electron.ps1 共同调用。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\check-backend-exe.ps1
# 退出码：0 = 通过；1 = 后端缺失或启动检查失败；构建机需 Python 3.11+。

$ErrorActionPreference = "Stop"

# 项目根目录：scripts/ 的父目录
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$backendExe = Join-Path $projectRoot "dist\praxic-backend.exe"

if (-not (Test-Path -LiteralPath $backendExe -PathType Leaf)) {
    Write-Host "[错误] 后端 exe 不存在: $backendExe" -ForegroundColor Red
    Write-Host "       请先构建 Python 后端（PyInstaller）再打包 Electron。" -ForegroundColor Yellow
    Write-Host "       构建后端：python -m PyInstaller praxic.spec --noconfirm --clean" -ForegroundColor Yellow
    exit 1
}

$backendSizeMB = [Math]::Round((Get-Item -LiteralPath $backendExe).Length / 1MB, 1)
Write-Host ("       后端 exe OK: {0} ({1} MB)" -f (Split-Path -Leaf $backendExe), $backendSizeMB) -ForegroundColor Green
python (Join-Path $projectRoot "scripts\smoke_backend.py") $backendExe
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 冻结后端启动检查失败，拒绝打包。" -ForegroundColor Red
    exit 1
}
exit 0
