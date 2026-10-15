@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Stop-Local.ps1"
set "MYQUANT_EXIT=%ERRORLEVEL%"
pause
exit /b %MYQUANT_EXIT%
