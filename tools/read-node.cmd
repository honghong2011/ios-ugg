@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   UGG - read catalog nodes straight off the card
echo   (phone must be in TWRP)
echo ============================================================
echo.

if not exist "adb.exe" (
    echo [X] adb.exe is not in this folder: %~dp0
    pause
    exit /b 1
)

adb.exe start-server >nul 2>&1

set "STATE="
set "SERIAL="
for /f "usebackq tokens=1,2" %%A in (`adb.exe devices 2^>nul`) do (
    if not "%%A"=="List" if not "%%A"=="" (
        set "SERIAL=%%A"
        set "STATE=%%B"
    )
)

if "!STATE!"=="" (
    echo [X] No device. Put the phone in TWRP and re-plug the cable.
    pause
    exit /b 1
)
echo    device: !SERIAL!  state: !STATE!
echo.

echo [1/3] pushing the script...
adb.exe push "read-node.sh" /tmp/read-node.sh
if errorlevel 1 (
    adb.exe push "read-node.sh" /sdcard/read-node.sh
    set "REMOTE=/sdcard/read-node.sh"
) else (
    set "REMOTE=/tmp/read-node.sh"
)
echo.

echo [2/3] reading the card...
echo ------------------------------------------------------------
adb.exe shell sh !REMOTE!
echo ------------------------------------------------------------
echo.

echo [3/3] saving the output...
if not exist "out" mkdir "out"
adb.exe shell sh !REMOTE! > "out\read-node.txt" 2>&1
echo    saved to out\read-node.txt
echo.
echo ============================================================
echo   Send me out\read-node.txt
echo ============================================================
pause
