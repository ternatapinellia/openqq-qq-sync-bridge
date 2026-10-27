@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
rem ==========================================================
rem  OpenQQ Sync Bridge v3.4 - Windows one-click updater
rem  Put this file next to the exe, then double-click it.
rem ==========================================================

set "EXE_NAME=OpenQQ-QQ-Sync-Bridge-v3.4.exe"
set "JS_NAME=OpenQQ-QQ-Sync-v3.4.js"
set "README_NAME=README-v3.4.txt"
set "START_CMD=启动OpenQQ同步桥-v3.4.cmd"
set "URL1=https://summer-pinellia.duckdns.org/projects/openqq-bridge/%E6%B0%91%E8%BD%AC%E5%AE%98%E6%95%B0%E6%8D%AE3.4%EF%BC%88windows%2Blinux%EF%BC%89.zip"
set "URL2=https://github.com/ternatapinellia/openqq-qq-sync-bridge/releases/download/v3.4/3.4.windows-linux.zip"

cd /d "%~dp0"
echo.
echo ============================================================
echo   OpenQQ Sync Bridge v3.4 updater
echo ============================================================
echo Target: %CD%
echo.

set "RUNNING="
tasklist /FI "IMAGENAME eq %EXE_NAME%" 2>nul | find /I "%EXE_NAME%" >nul && set "RUNNING=1"
if not defined RUNNING tasklist /FI "IMAGENAME eq OpenQQ-QQ-Sync-Bridge-v3.3.exe" 2>nul | find /I "OpenQQ-QQ-Sync-Bridge-v3.3.exe" >nul && set "RUNNING=1"
if defined RUNNING (
  echo [info] Bridge is running. It must be closed before update.
  choice /C YN /M "Kill it automatically"
  if errorlevel 2 (
    echo Cancelled.
    pause & exit /b 1
  )
taskkill /F /IM "%EXE_NAME%" >nul 2>&1
taskkill /F /IM "OpenQQ-QQ-Sync-Bridge-v3.3.exe" >nul 2>&1
  timeout /t 2 >nul
  echo [ok] Process stopped.
  echo.
)

set "TMPD=%TEMP%\openqq-update-%RANDOM%"
mkdir "%TMPD%" 2>nul
if not exist "%TMPD%" (
  echo [error] Cannot create temp dir.
  pause & exit /b 1
)

echo [1/4] Downloading package...
set "ZIP=%TMPD%\pkg.zip"
set "GOT="
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%URL1%' -OutFile '%ZIP%' -TimeoutSec 180 -UseBasicParsing } catch { exit 1 }"
if exist "%ZIP%" for %%A in ("%ZIP%") do if %%~zA GTR 1000000 set "GOT=1"
if not defined GOT (
  echo       Primary source failed, trying GitHub Release...
  del /q "%ZIP%" 2>nul
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%URL2%' -OutFile '%ZIP%' -TimeoutSec 180 -UseBasicParsing } catch { exit 1 }"
  if exist "%ZIP%" for %%A in ("%ZIP%") do if %%~zA GTR 1000000 set "GOT=1"
)
if not defined GOT (
  echo [error] Download failed. Nothing was changed.
  rmdir /s /q "%TMPD%" 2>nul
  pause & exit /b 1
)
for %%A in ("%ZIP%") do echo       Downloaded: %%~zA bytes
echo.

echo [2/4] Extracting...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try{Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%TMPD%\x' -Force}catch{exit 1}"
if not exist "%TMPD%\x\windows\%EXE_NAME%" (
  echo [error] Package does not contain the v3.4 exe. Nothing was changed.
  rmdir /s /q "%TMPD%" 2>nul
  pause & exit /b 1
)
echo       Extracted.
echo.

echo [3/4] Backing up current files...
for /f "tokens=1-3 delims=/-. " %%a in ("%DATE%") do set "D=%%a%%b%%c"
set "BKD=backup-%D%"
mkdir "%BKD%" 2>nul
for %%F in ("%EXE_NAME%" "%JS_NAME%" "bridge_port.txt" "%README_NAME%" "OpenQQ-QQ-Sync-Bridge-v3.3.exe" "OpenQQ-QQ-Sync-v3.3.js") do (
  if exist "%%~F" copy /y "%%~F" "%BKD%\%%~F" >nul 2>&1
)
echo       Backed up to %BKD%\
echo.

echo [4/4] Replacing files...
for %%F in ("%EXE_NAME%" "%JS_NAME%" "%README_NAME%" "启动OpenQQ同步桥-v3.4.cmd") do (
  if exist "%TMPD%\x\windows\%%~F" copy /y "%TMPD%\x\windows\%%~F" "%%~F" >nul 2>&1
)
rmdir /s /q "%TMPD%" 2>nul
echo.
echo ============================================================
echo   Update finished (v3.4)
echo ============================================================
echo  Backup: %CD%\%BKD%\
echo  Next steps:
echo    1) Start the bridge with 启动OpenQQ同步桥-v3.4.cmd
echo    2) Copy OpenQQ-QQ-Sync-v3.4.js into the SealDice scripts folder
echo       and reload the plugin in WebUI
echo    3) The old v3.3 exe/js can be deleted
echo.
pause
