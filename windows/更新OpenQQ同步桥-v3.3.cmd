@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
rem =====================================================================
rem  OpenQQ 同步桥 v3.3 一键更新脚本（Windows）
rem
rem  作用：从网站下载最新的桥发布包，替换本文件夹里的
rem        OpenQQ-QQ-Sync-Bridge-v3.3.exe 和 bridge_port.txt 等文件。
rem
rem  用法：把本文件放到跟 exe 同一个文件夹，双击运行即可。
rem        如果 exe 正在运行，脚本会先请你关掉它。
rem
rem  安全措施：
rem    * 更新前把旧文件备份到 backup-<日期>/ 文件夹
rem    * 下载后校验文件完整（是有效的 zip 才能解出 exe）
rem    * 只有全部成功才替换，失败保留原文件
rem =====================================================================

set "EXE_NAME=OpenQQ-QQ-Sync-Bridge-v3.3.exe"
set "URL1=https://summer-pinellia.duckdns.org/projects/openqq-bridge/%%E6%%B0%%91%%E8%%BD%%AC%%E5%%AE%%98%%E6%%95%%B0%%E6%%8D%%AE3.3%%EF%%BC%%88windows%%2Blinux%%EF%%BC%%89.zip"
set "URL2=https://github.com/ternatapinellia/openqq-qq-sync-bridge/releases/download/v3.3/3.3.windows%%2Blinux.zip"

cd /d "%~dp0"
echo.
echo ============================================================
echo   OpenQQ 同步桥 一键更新
echo ============================================================
echo 当前目录：%CD%
echo.

rem ---------- 1. 检查 exe 是否在运行 ----------
tasklist /FI "IMAGENAME eq %EXE_NAME%" 2>nul | find /I "%EXE_NAME%" >nul
if not errorlevel 1 (
  echo [提示] 检测到桥正在运行：%EXE_NAME%
  echo        更新需要替换这个文件，请先关闭桥的窗口。
  echo.
  choice /C YN /M "是否自动帮你结束这个进程"
  if errorlevel 2 (
    echo 已取消。请手动关闭桥后重新运行本脚本。
    pause & exit /b 1
  )
  taskkill /F /IM "%EXE_NAME%" >nul 2>&1
  timeout /t 2 >nul
  echo 已结束进程。
  echo.
)

rem ---------- 2. 准备临时目录 ----------
set "TMPD=%TEMP%\openqq-bridge-update-%RANDOM%"
mkdir "%TMPD%" 2>nul
if not exist "%TMPD%" (
  echo [错误] 无法创建临时目录 %TMPD%
  pause & exit /b 1
)

rem ---------- 3. 下载发布包 ----------
echo [1/4] 下载最新发布包...
set "ZIP=%TMPD%\pkg.zip"
set "GOT="
rem 优先用 PowerShell（走系统代理、TLS 兼容性最好），失败再用 curl
set "PSDL=powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%URL1%' -OutFile '%ZIP%' -TimeoutSec 180 -UseBasicParsing } catch { exit 1 }"
%PSDL%
if exist "%ZIP%" for %%A in ("%ZIP%") do if %%~zA GTR 1000000 set "GOT=1"
if not defined GOT (
  echo       主源失败，改用 GitHub Release...
  del /q "%ZIP%" 2>nul
  set "PSDL=powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%URL2%' -OutFile '%ZIP%' -TimeoutSec 180 -UseBasicParsing } catch { exit 1 }"
  !PSDL!
  if exist "%ZIP%" for %%A in ("%ZIP%") do if %%~zA GTR 1000000 set "GOT=1"
)
if not defined GOT (
  echo       PowerShell 也失败，最后尝试 curl...
  del /q "%ZIP%" 2>nul
  curl.exe -fsSL --max-time 180 -o "%ZIP%" "%URL1%" 2>nul
  if exist "%ZIP%" for %%A in ("%ZIP%") do if %%~zA GTR 1000000 set "GOT=1"
)
if not defined GOT (
  echo [错误] 下载失败（网络问题）。原文件未改动。
  rmdir /s /q "%TMPD%" 2>nul
  pause & exit /b 1
)
for %%A in ("%ZIP%") do echo       下载完成：%%~zA 字节
echo.

rem ---------- 4. 解压 ----------
echo [2/4] 解压...
set "PS=powershell.exe -NoProfile -ExecutionPolicy Bypass -Command"
%PS% "try{Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%TMPD%\x' -Force}catch{exit 1}"
if not exist "%TMPD%\x\windows\%EXE_NAME%" (
  echo [错误] 压缩包里没有找到 %EXE_NAME%，原文件未改动。
  rmdir /s /q "%TMPD%" 2>nul
  pause & exit /b 1
)
echo       解压完成。
echo.

rem ---------- 5. 备份旧文件 ----------
echo [3/4] 备份当前文件...
for /f "tokens=1-3 delims=/-. " %%a in ("%DATE%") do set "D=%%a%%b%%c"
if "%D%"=="" set "D=%RANDOM%"
set "BKD=backup-%D%"
mkdir "%BKD%" 2>nul
for %%F in ("%EXE_NAME%" "bridge_port.txt" "OpenQQ-QQ-Sync-v3.3.js" "README-v3.3.txt" "启动OpenQQ同步桥-v3.3.cmd") do (
  if exist "%%~F" copy /y "%%~F" "%BKD%\%%~F" >nul 2>&1
)
echo       已备份到 %BKD%\
echo.

rem ---------- 6. 替换 ----------
echo [4/4] 替换文件...
set "FAILED="
for %%F in ("%EXE_NAME%" "bridge_port.txt" "OpenQQ-QQ-Sync-v3.3.js" "README-v3.3.txt" "启动OpenQQ同步桥-v3.3.cmd") do (
  if exist "%TMPD%\x\windows\%%~F" (
    copy /y "%TMPD%\x\windows\%%~F" "%%~F" >nul 2>&1
    if errorlevel 1 set "FAILED=%%~F"
  )
)

if defined FAILED (
  echo [错误] 以下文件替换失败：!FAILED!
  echo        正在从备份还原...
  for %%F in ("%EXE_NAME%" "bridge_port.txt" "OpenQQ-QQ-Sync-v3.3.js" "README-v3.3.txt" "启动OpenQQ同步桥-v3.3.cmd") do (
    if exist "%BKD%\%%~F" copy /y "%BKD%\%%~F" "%%~F" >nul 2>&1
  )
  rmdir /s /q "%TMPD%" 2>nul
  pause & exit /b 1
)

rmdir /s /q "%TMPD%" 2>nul
echo.
echo ============================================================
echo   更新完成！
echo ============================================================
echo  备份：%CD%\%BKD%\
echo  下一步：双击「启动OpenQQ同步桥-v3.3.cmd」重新启动桥
echo         海豹里的插件如果也更新了，记得在 WebUI 重载插件
echo.
pause
