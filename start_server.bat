@echo off
title Gold Price Investment Assistant
cd /d "%~dp0"
echo ============================================
echo  Gold Price Investment Assistant
echo  URL: http://127.0.0.1:8888
echo  Keep this window open to run the service.
echo  Close this window to stop the service.
echo ============================================
echo.
echo  Starting service, opening browser in 6s ...
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8888/"
"C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8888
pause
