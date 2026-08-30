# 本机常驻安装脚本：注册「登录时自动启动」计划任务（后台运行 + 日志）
#
# 使用方法（二选一）：
#   A. 右键此文件 -> 使用 PowerShell 运行（推荐）
#   B. 打开 PowerShell 执行：  powershell -ExecutionPolicy Bypass -File .\install_startup.ps1
#
# 卸载常驻：  Unregister-ScheduledTask -TaskName "GoldPriceAssistant" -Confirm:$false
#
# 注意：脚本仅注册任务，不在当前会话启动服务；
#       注册后【重新登录或手动运行 start_server.bat】即可生效。

$ErrorActionPreference = "Stop"

$TaskName = "GoldPriceAssistant"
$Python = "C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stdout = Join-Path $WorkDir "server.log"
$Stderr = Join-Path $WorkDir "server.log.err"

# 1) 停止并移除旧任务（如有）
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

# 2) 创建动作：登录时以后台方式启动 uvicorn，日志写入 server.log
$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m uvicorn app.main:app --host 127.0.0.1 --port 8888" `
    -WorkingDirectory $WorkDir

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -Hidden

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host ""
Write-Host "=========================================================="
Write-Host "  Installed: $TaskName"
Write-Host "  Auto start: on logon (background, logs -> server.log)"
Write-Host "  URL: http://127.0.0.1:8888"
Write-Host "  Now: log out/in OR run start_server.bat once"
Write-Host "  Uninstall: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host "=========================================================="
