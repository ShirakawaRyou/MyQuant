@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Status-Local.ps1"
set "MYQUANT_EXIT=%ERRORLEVEL%"
pause
exit /b %MYQUANT_EXIT%
