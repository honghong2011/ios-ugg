@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   UGG - pull the kernel console log (phone must be in TWRP)
echo ============================================================
echo.

if not exist "adb.exe" (
    echo [X] adb.exe is not in this folder:
    echo     %~dp0
    echo     Put adb.exe, AdbWinApi.dll and AdbWinUsbApi.dll here.
    echo.
    pause
    exit /b 1
)
echo [1/6] adb.exe found.

REM ---------- 2. device: parse `adb devices`, do NOT trust a shell probe ----------
echo [2/6] looking for a device...
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
    echo.
    echo [X] No device listed by adb. Checklist:
    echo     - phone is in TWRP, not Android
    echo     - the cable carries data ^(not charge-only^)
    echo     - re-plug the cable, or TWRP: Mount -^> re-toggle
    echo     - Windows: accept the driver wizard, or install Google USB driver
    echo.
    pause
    exit /b 1
)

echo        device: !SERIAL!  state: !STATE!

if "!STATE!"=="unauthorized" (
    echo.
    echo [X] The phone says UNAUTHORIZED.
    echo     Look at the TWRP screen: accept 'Allow USB debugging'.
    echo     If no prompt appears, tap: TWRP -^> Advanced -^> ADB Sideload, back out,
    echo     then re-plug the cable.
    echo.
    pause
    exit /b 1
)

if not "!STATE!"=="device" if not "!STATE!"=="recovery" if not "!STATE!"=="sideload" (
    echo.
    echo [X] Device state is '!STATE!', which is not usable.
    echo.
    pause
    exit /b 1
)
echo        OK -- continuing.
echo.

REM ---------- 3. push the phone-side script ----------
echo [3/6] pushing the phone-side script...
adb.exe push "ugg-grab-log.sh" /tmp/ugg-grab-log.sh
if errorlevel 1 (
    echo        push to /tmp failed, trying /sdcard...
    adb.exe push "ugg-grab-log.sh" /sdcard/ugg-grab-log.sh
    if errorlevel 1 (
        echo [X] push failed both ways.
        pause
        exit /b 1
    )
    set "REMOTE=/sdcard/ugg-grab-log.sh"
) else (
    set "REMOTE=/tmp/ugg-grab-log.sh"
)
echo.

REM ---------- 4. run it ----------
echo [4/6] reading the log area out of userdata...
echo ------------------------------------------------------------
adb.exe shell sh !REMOTE!
echo ------------------------------------------------------------
echo.

REM ---------- 5. pull it ----------
echo [5/6] pulling the dump to this PC...
if not exist "out" mkdir "out"
adb.exe pull /sdcard/sweetlog.bin "out\sweetlog.bin"
if errorlevel 1 (
    echo.
    echo [X] pull failed. Copy it by hand:
    echo     adb.exe pull /sdcard/sweetlog.bin "out\sweetlog.bin"
    echo.
    pause
    exit /b 1
)
echo.

REM ---------- 6. decode ----------
echo [6/6] decoding...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sweetlog-decode.ps1" -InputFile "out\sweetlog.bin" -OutputFile "out\kernel-console.txt"

echo.
echo ============================================================
echo   Done.
echo   Raw dump : out\sweetlog.bin
echo   Readable : out\kernel-console.txt
echo.
echo   Send me kernel-console.txt ^(or the .bin if it did not decode^).
echo ============================================================
echo.
pause
