@echo off
chcp 65001 >nul
title 树莓派看门狗 - 别关这个窗口
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watch_pi.ps1"
echo.
echo 看门狗已停止。日志在 ..\logs\
pause