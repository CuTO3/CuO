@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0CuCl-Control.ps1"
if errorlevel 1 pause
