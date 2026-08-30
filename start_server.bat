@echo off
title Gold Price Investment Assistant
cd /d "%~dp0"
echo ============================================
echo  Gold Price Investment Assistant
echo  URL: http://127.0.0.1:8888
echo ============================================

rem --- 已运行则直接打开浏览器（幂等） ---
curl -s -m 2 http://127.0.0.1:8888/api/v1/health >nul 2>&1
if %errorlevel%==0 (
    echo  Service already running. Opening browser ...
    start "" http://127.0.0.1:8888/
    exit /b 0
)

echo  Starting service, opening browser in 6s ...
echo  Close this window to stop the service.
echo.
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8888/"
"C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8888
pause
