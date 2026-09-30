@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_deploy_package.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo Packaging failed. No release ZIP was completed.
if /i not "%~1"=="--no-pause" pause
exit /b %EXIT_CODE%
