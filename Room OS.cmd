@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_room_os.ps1"
if errorlevel 1 pause
endlocal
