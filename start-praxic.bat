@echo off
chcp 65001 >nul
title Praxic Launcher
cd /d E:\Scripts\Praxic

echo ============================================
echo   Praxic 一键启动
echo   前端+后端: http://127.0.0.1:8000
echo ============================================

if not exist "D:\Anaconda\python.exe" (
  echo [错误] 未找到 Python: D:\Anaconda\python.exe
  pause
  exit /b 1
)

echo [1/1] 启动后端 (uvicorn :8000，托管前端 index.html) ...
start "Praxic-Backend" cmd /k "chcp 65001 >nul & D:\Anaconda\python.exe -m uvicorn praxic.api.server:app --host 127.0.0.1 --port 8000"

timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:8000"

echo 完成。后端窗口已打开，浏览器将打开 http://127.0.0.1:8000。
echo 关闭后端请直接关闭对应窗口。
pause
