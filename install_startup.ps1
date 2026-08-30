# 本机常驻安装脚本：注册「登录时自动启动」计划任务（服务 + 看门狗）
#
# 使用方法（二选一）：
#   A. 右键此文件 -> 使用 PowerShell 运行（推荐）
#   B. 打开 PowerShell 执行：  powershell -ExecutionPolicy Bypass -File .\install_startup.ps1
#
# 注册两个任务：
#   GoldPriceAssistant          —— 登录时启动服务（后台，日志 server.log）
#   GoldPriceAssistantWatchdog  —— 登录时启动看门狗（每 30s 健康检查，卡死自动重启）
#
# 卸载常驻：
#   Unregister-ScheduledTask -TaskName "GoldPriceAssistant" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "GoldPriceAssistantWatchdog" -Confirm:$false
#
# 注意：脚本仅注册任务，不在当前会话启动服务；
#       注册后【重新登录或手动运行 start_server.bat】即可生效。

$ErrorActionPreference = "Stop"

$Python = "C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -Hidden
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

# ---------- 任务 1：服务本体 ----------
$TaskService = "GoldPriceAssistant"
$existing = Get-ScheduledTask -TaskName $TaskService -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskService -Confirm:$false
    Write-Host "Removed existing task: $TaskService"
}

$actionService = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m uvicorn app.main:app --host 0.0.0.0 --port 8888" `
    -WorkingDirectory $WorkDir

Register-ScheduledTask -TaskName $TaskService -Action $actionService `
    -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

# ---------- 任务 2：看门狗 ----------
$TaskWatchdog = "GoldPriceAssistantWatchdog"
$existingWd = Get-ScheduledTask -TaskName $TaskWatchdog -ErrorAction SilentlyContinue
if ($existingWd) {
    Unregister-ScheduledTask -TaskName $TaskWatchdog -Confirm:$false
    Write-Host "Removed existing task: $TaskWatchdog"
}

$actionWatchdog = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "watchdog.py --interval 30 --threshold 2" `
    -WorkingDirectory $WorkDir

Register-ScheduledTask -TaskName $TaskWatchdog -Action $actionWatchdog `
    -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host ""
Write-Host "=========================================================="
Write-Host "  Installed:"
Write-Host "   - $TaskService          (service, background)"
Write-Host "   - $TaskWatchdog  (watchdog, 30s health check)"
Write-Host "  Auto start: on logon"
Write-Host "  URL: http://127.0.0.1:8888"
Write-Host "  Now: log out/in OR run start_server.bat once"
Write-Host "  Logs: server.log / watchdog.log"
Write-Host "  Uninstall:"
Write-Host "    Unregister-ScheduledTask -TaskName $TaskService -Confirm:`$false"
Write-Host "    Unregister-ScheduledTask -TaskName $TaskWatchdog -Confirm:`$false"
Write-Host "=========================================================="
