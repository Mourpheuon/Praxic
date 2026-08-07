# 即物穷理 Praxic —— 后端 exe 闸门检查
# 用途：确保 PyInstaller 后端产物存在，否则拒绝 Electron 打包（防空壳安装包）。
# 被 package.json 的 electron:build 和 scripts/build-electron.ps1 共同调用。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\check-backend-exe.ps1
# 退出码：0 = 通过；1 = 后端 exe 缺失

$ErrorActionPreference = "Stop"

# 项目根目录：scripts/ 的父目录
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$backendExe = Join-Path $projectRoot "dist\praxic-backend.exe"

if (-not (Test-Path -LiteralPath $backendExe -PathType Leaf)) {
    Write-Host "[错误] 后端 exe 不存在: $backendExe" -ForegroundColor Red
    Write-Host "       请先构建 Python 后端（PyInstaller）再打包 Electron。" -ForegroundColor Yellow
    Write-Host "       构建后端：& 'E:\Scripts\Praxic\.venv-build\Scripts\python.exe' -m PyInstaller praxic.spec --noconfirm --clean" -ForegroundColor Yellow
    exit 1
}

$backendSizeMB = [Math]::Round((Get-Item -LiteralPath $backendExe).Length / 1MB, 1)
Write-Host ("       后端 exe OK: {0} ({1} MB)" -f (Split-Path -Leaf $backendExe), $backendSizeMB) -ForegroundColor Green
exit 0
