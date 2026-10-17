@echo off
rem Double-click launcher for Windows. Runs serve.ps1 without needing to change PowerShell's execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %*
set "rc=%errorlevel%"
if not "%rc%"=="0" pause
exit /b %rc%
