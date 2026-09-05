@echo off
set "SCRIPT=%~dp0Prime_MPEG1_Batch_Converter_V5.ps1"
if not exist "%SCRIPT%" (
  echo Prime_MPEG1_Batch_Converter_V5.ps1 not found.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
