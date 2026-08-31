# 本机常驻安装脚本：配置「登录自动启动」与「每日快照定时采集」
#
# 使用方法（二选一）：
#   A. 右键此文件 -> 使用 PowerShell 运行（推荐，无需管理员）
#   B. 打开 PowerShell 执行：  powershell -ExecutionPolicy Bypass -File .\install_startup.ps1
#
# 安装完成后（无需管理员）：
#   1) 启动文件夹写入 GoldPriceAssistant.bat —— 登录后自动启动看门狗
#      看门狗职责：拉起服务 + 30s 健康守护（卡死自动重启）+ 每日定时采集快照
#   2) 若当前为管理员，额外注册计划任务（开机即启动，无需登录桌面）
#
# 卸载常驻：
#   删除启动文件夹中的 GoldPriceAssistant.bat
#   Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\GoldPriceAssistant.bat" | Remove-Item -Force

$ErrorActionPreference = "Continue"

$Python = "C:\Users\DFCFF\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
$WorkDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskService = "GoldPriceAssistant"
$TaskWatchdog = "GoldPriceAssistantWatchdog"
$TaskSnapshot = "GoldPriceAssistantSnapshot"

# ---------- 1) 启动文件夹：登录后自动启动看门狗（无需管理员） ----------
$startupDir = [Environment]::GetFolderPath("Startup")
$batPath = Join-Path $startupDir "GoldPriceAssistant.bat"

$batContent = @"
@echo off
rem 登录后自动启动看门狗：拉起服务 + 健康守护 + 每日定时采集快照
cd /d "$WorkDir"
start "" /min "$Python" watchdog.py --interval 30 --threshold 2
"@

Set-Content -Path $batPath -Value $batContent -Encoding ASCII
Write-Host "[OK] Startup entry created: $batPath"

# ---------- 2) 计划任务（可选，需要管理员权限） ----------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn
    $triggerDaily = @(
        (New-ScheduledTaskTrigger -Daily -At "16:00"),
        (New-ScheduledTaskTrigger -Daily -At "06:00")
    )
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited

    foreach ($t in @($TaskService, $TaskWatchdog, $TaskSnapshot)) {
        $old = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        if ($old) { Unregister-ScheduledTask -TaskName $t -Confirm:$false }
    }

    $a1 = New-ScheduledTaskAction -Execute $Python `
        -Argument "-m uvicorn app.main:app --host 0.0.0.0 --port 8888" -WorkingDirectory $WorkDir
    Register-ScheduledTask -TaskName $TaskService -Action $a1 `
        -Trigger $triggerLogon -Settings $settings -Principal $principal -Force | Out-Null

    $a2 = New-ScheduledTaskAction -Execute $Python `
        -Argument "watchdog.py --interval 30 --threshold 2" -WorkingDirectory $WorkDir
    Register-ScheduledTask -TaskName $TaskWatchdog -Action $a2 `
        -Trigger $triggerLogon -Settings $settings -Principal $principal -Force | Out-Null

    $a3 = New-ScheduledTaskAction -Execute $Python `
        -Argument "capture_snapshot.py --wait 180" -WorkingDirectory $WorkDir
    Register-ScheduledTask -TaskName $TaskSnapshot -Action $a3 `
        -Trigger $triggerDaily -Settings $settings -Principal $principal -Force | Out-Null

    Write-Host "[OK] Scheduled tasks registered (service / watchdog / snapshot)"
} else {
    Write-Host "[SKIP] 计划任务需管理员权限（已跳过）—— 启动文件夹方案已生效，功能完整"
}

Write-Host ""
Write-Host "=========================================================="
Write-Host "  安装完成（看门狗 = 拉服务 + 健康守护 + 定时采集快照）"
Write-Host "  URL: http://127.0.0.1:8888"
Write-Host "  生效方式：下次登录后自动运行（或现在双击 start_server.bat）"
Write-Host "  每日采集：06:00 / 16:00（由看门狗触发，服务需在运行）"
Write-Host "  日志：server.log / watchdog.log / capture.log"
Write-Host "  卸载：删除 $startupDir\GoldPriceAssistant.bat"
Write-Host "=========================================================="
