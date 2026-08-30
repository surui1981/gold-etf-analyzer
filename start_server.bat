@echo off
chcp 65001 >nul
title Gold Price Investment Assistant
cd /d "%~dp0"
echo ============================================
echo  黄金价格投资辅助工具 - 本机启动
echo  URL: http://127.0.0.1:8888
echo  关闭本窗口即停止服务
echo ============================================
echo.

rem --- 已运行则直接打开浏览器 ---
curl -s -m 2 http://127.0.0.1:8888/api/v1/health >nul 2>&1
if %errorlevel%==0 (
    echo  [OK] 服务已在运行，正在打开浏览器...
    start "" http://127.0.0.1:8888/
    exit /b 0
)

rem --- 端口被残留进程占用 -> 自动清理后继续（一键自愈） ---
netstat -ano | findstr ":8888" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo  [提示] 检测到残留进程占用 8888，自动清理后重启...
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8888" ^| findstr "LISTENING"') do (
        taskkill /F /PID %%p >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

rem --- 定位 Python 解释器（按优先级探测） ---
set "PYTHON="
if exist "C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PYTHON=C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined PYTHON if exist "C:\Users\DFCFF\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PYTHON=C:\Users\DFCFF\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not defined PYTHON where python >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON py -3 --version >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
    echo  [错误] 未找到 Python 环境！
    echo  请到 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本后重试。
    pause
    exit /b 1
)
echo  [OK] 使用 Python: %PYTHON%

rem --- 依赖检查：缺失则自动安装 ---
"%PYTHON%" -c "import uvicorn, akshare" >nul 2>&1
if not %errorlevel%==0 (
    echo  [提示] 首次运行，正在安装依赖（约 1-3 分钟）...
    "%PYTHON%" -m pip install -e ".[dev]"
    if not %errorlevel%==0 (
        echo  [错误] 依赖安装失败。请手动执行：
        echo  %PYTHON% -m pip install -e ".[dev]"
        pause
        exit /b 1
    )
)

echo.
echo  [OK] 正在启动服务，6 秒后自动打开浏览器...
echo  [OK] 关闭本窗口即停止服务。
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8888/"
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8888
pause
