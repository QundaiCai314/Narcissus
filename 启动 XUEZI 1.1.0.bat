@echo off
setlocal
cd /d "%~dp0"
start "XUEZI Local Server" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0xuezi-server.ps1"
endlocal
