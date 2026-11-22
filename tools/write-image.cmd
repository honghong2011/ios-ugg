@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   UGG - write the iOS root image to userdata (from TWRP)
echo ============================================================
echo.
echo   fastboot was proven to write wrong data on this phone:
echo   reading the partition with dd shows 6a13d46a at block 1734927
echo   while the image file has 00004af9 there. This writes the image
echo   directly instead, with no protocol in the way.
echo.

REM ---------- find adb ----------
set "ADB="
if exist "adb.exe" set "ADB=%~dp0adb.exe"
if not defined ADB if exist "..\adb\adb.exe" set "ADB=%~dp0..\adb\adb.exe"
if not defined ADB (
    where adb >nul 2>&1 && set "ADB=adb"
)
if not defined ADB (
    echo [X] adb.exe not found.
    echo     Put adb.exe in this folder, or in ..\adb\
    pause
    exit /b 1
)
echo [1/6] adb: !ADB!

REM ---------- find the image ----------
set "IMG="
if exist "ios16-root.img" set "IMG=%~dp0ios16-root.img"
if not defined IMG if exist "ios16-root.simg" set "IMG=%~dp0ios16-root.simg"
if not defined IMG (
    echo [X] No ios16-root.img in this folder.
    echo     Put ios16-root.img next to this .cmd file.
    pause
    exit /b 1
)
echo [2/6] image: !IMG!

REM refuse a sparse image: this script writes raw bytes
set "ISIMG=0"
echo !IMG! | find /i ".simg" >nul && set "ISIMG=1"
if "!ISIMG!"=="1" (
    echo.
    echo [X] That is a .simg ^(sparse^) file. This script needs the raw .img.
    echo     Convert it first:
    echo         python ..\simg2img.py ios16-root.simg ios16-root.img
    pause
    exit /b 1
)

REM ---------- device ----------
echo [3/6] looking for the phone...
!ADB! start-server >nul 2>&1
set "STATE="
set "SERIAL="
for /f "usebackq tokens=1,2" %%A in (`!ADB! devices 2^>nul`) do (
    if not "%%A"=="List" if not ""=="%%A" (
        set "SERIAL=%%A"
        set "STATE=%%B"
    )
)
if not defined STATE (
    echo [X] No device. Boot the phone into TWRP first.
    pause
    exit /b 1
)
echo        device !SERIAL! state !STATE!
if not "!STATE!"=="recovery" if not "!STATE!"=="device" (
    echo [X] State is '!STATE!'; need TWRP recovery.
    pause
    exit /b 1
)

REM ---------- confirm ----------
echo.
echo ============================================================
echo   This ERASES userdata ^(about 53 GB^) and writes the iOS root.
echo   Android data on this phone will be gone. It takes 1-2 hours.
echo ============================================================
echo.
set "OK="
set /p OK=Type YES to continue: 
if /i not "!OK!"=="YES" (
    echo Cancelled.
    pause
    exit /b 1
)

REM ---------- push ----------
echo [4/6] pushing the image to /sdcard (this is the slow part)...
!ADB! push "!IMG!" /sdcard/ios16-root.img
if errorlevel 1 (
    echo [X] push failed. Check free space on /sdcard and the cable.
    pause
    exit /b 1
)

echo [5/6] pushing the writer script...
!ADB! push "%~dp0write-image.sh" /tmp/write-image.sh
if errorlevel 1 (
    echo [X] push of write-image.sh failed.
    pause
    exit /b 1
)

REM ---------- write ----------
echo [6/6] writing to userdata...
echo ------------------------------------------------------------
if not exist "out" mkdir "out"
!ADB! shell sh /tmp/write-image.sh /sdcard/ios16-root.img 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath 'out\write-result.txt'"
echo ------------------------------------------------------------

echo.
echo ============================================================
echo   Done. Look at the four blocks above.
echo.
echo   If they read 00 00 4a f9 ... then the card is correct and you
echo   can boot the kernel image next.
echo   Saved to out\write-result.txt
echo ============================================================
pause
