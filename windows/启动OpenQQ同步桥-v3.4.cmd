@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
:START
set "PORT_FILE=%~dp0bridge_port.txt"
set "PORT="
if exist "%PORT_FILE%" set /p PORT=<"%PORT_FILE%"
if "%PORT%"=="" set "PORT=38999"
set /a PORT_NUM=%PORT% >nul 2>&1
if %PORT_NUM% LSS 1 set "PORT=38999"
if %PORT_NUM% GTR 65535 set "PORT=38999"
echo Starting OpenQQ QQ Sync Bridge v3.4 on port %PORT%...
OpenQQ-QQ-Sync-Bridge-v3.4.exe --port %PORT%
set "ERR=%errorlevel%"
if "%ERR%"=="0" (
  echo Bridge exited, restarting...
  timeout /t 1 /nobreak >nul
  goto START
)
echo Bridge exited with error code %ERR%.
pause
endlocal
