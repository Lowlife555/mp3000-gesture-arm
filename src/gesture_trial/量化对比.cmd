@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY="C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe"

echo ============================================================
echo   量化对比：float32 vs int8（最能体现嵌入式思维的一张纸）
echo ============================================================
%PY% 04_quantize.py
echo.
echo   产物：reports\quantization.txt
pause
