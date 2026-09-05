@echo off
chcp 65001 >nul
set "SCRIPT=%~dp0Prime_MPEG1_Converter.ps1"
if not exist "%SCRIPT%" (
    echo 找不到 Prime_MPEG1_Converter.ps1
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
