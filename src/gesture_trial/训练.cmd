@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY="C:\Users\<you>\venvs\mp3000-nn\Scripts\python.exe"

echo ============================================================
echo   训练手势 CNN（纯 CPU，约 2-3 分钟）
echo ============================================================
%PY% 02_train.py

echo.
echo ============================================================
echo   训练结束。产物在 reports\ 下：
echo     training_curves.png   训练/验证曲线
echo     confusion_matrix.png  混淆矩阵（看哪两类最容易混）
echo     metrics.txt           全部指标
echo.
echo   下一步：双击 实时演示.cmd
echo ============================================================
pause
