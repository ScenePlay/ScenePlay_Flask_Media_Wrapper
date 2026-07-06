@echo off
setlocal EnableDelayedExpansion
title ScenePlay Windows Installer
cd /d %~dp0

echo ============================================
echo  ScenePlay - Windows installer
echo  (Windows analog of requirements.sh)
echo ============================================
echo.

REM ---------------------------------------------------------------- winget --
where winget >nul 2>nul
if errorlevel 1 (
    echo [!] winget is not available. Install "App Installer" from the
    echo     Microsoft Store, then re-run install.bat.
    pause
    exit /b 1
)

set NEED_RESTART=0

REM ---------------------------------------------------------------- python --
where python >nul 2>nul
if errorlevel 1 (
    echo [*] Python not found - installing Python 3.12 via winget...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    set NEED_RESTART=1
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [ok] Python %%v found
)

REM ------------------------------------------------------------------- mpv --
where mpv >nul 2>nul
if errorlevel 1 (
    echo [*] mpv not found - installing via winget...
    winget install mpv --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo [!] winget could not install mpv automatically.
        echo     Install it manually and make sure mpv.exe is on PATH:
        echo     https://mpv.io/installation/
    ) else (
        set NEED_RESTART=1
    )
) else (
    echo [ok] mpv found
)

REM ---------------------------------------------------------------- ffmpeg --
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [*] ffmpeg not found - installing via winget ^(needed by yt-dlp^)...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo [!] winget could not install ffmpeg automatically.
        echo     Install it manually and put ffmpeg.exe on PATH:
        echo     https://www.gyan.dev/ffmpeg/builds/
    ) else (
        set NEED_RESTART=1
    )
) else (
    echo [ok] ffmpeg found
)

REM A winget install only lands on PATH for NEW shells - a fresh run picks it up.
if "%NEED_RESTART%"=="1" (
    echo.
    echo [!] New tools were installed. Close this window, open a NEW one,
    echo     and run install.bat again to finish setup.
    pause
    exit /b 0
)

REM ------------------------------------------------------------ python venv --
REM .venv-win, NOT .venv: on the shared HDD .venv is the Linux virtualenv
REM (bin/, no Scripts\) — the two must live side by side.
if not exist .venv-win\Scripts\python.exe (
    echo [*] Creating Python virtual environment...
    python -m venv .venv-win
    if errorlevel 1 (
        echo [!] venv creation failed - check the Python install.
        pause
        exit /b 1
    )
) else (
    echo [ok] .venv-win already exists
)

echo [*] Installing Python packages...
.venv-win\Scripts\python -m pip install --upgrade pip --quiet
.venv-win\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [!] pip install failed - see errors above.
    pause
    exit /b 1
)
echo [ok] Python packages installed

REM ------------------------------------------------------ desktop shortcut --
choice /c YN /m "Create a desktop shortcut for ScenePlay"
if !errorlevel! equ 1 (
    powershell -NoProfile -Command ^
      "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\ScenePlay.lnk');" ^
      "$s.TargetPath='%~dp0startApp.bat';$s.WorkingDirectory='%~dp0';$s.Description='ScenePlay server';$s.Save()"
    echo [ok] Desktop shortcut created
)

REM ------------------------------------------------------------- autostart --
choice /c YN /m "Start ScenePlay automatically when you log in"
if !errorlevel! equ 1 (
    schtasks /create /f /sc onlogon /tn ScenePlay /tr "\"%~dp0startApp.bat\"" >nul
    if errorlevel 1 (
        echo [!] Could not create the scheduled task ^(try an elevated prompt^).
    ) else (
        echo [ok] ScenePlay will start at logon ^(Task Scheduler: "ScenePlay"^)
    )
)

echo.
echo ============================================
echo  Install complete.
echo  Start now with:  startApp.bat
echo  Then open:       http://localhost:8086
echo ============================================
pause
