@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Backtest.ps1"
set "MYQUANT_EXIT=%ERRORLEVEL%"
pause
exit /b %MYQUANT_EXIT%
