@echo off
setlocal EnableDelayedExpansion
title ScenePlay Windows Uninstaller
cd /d %~dp0

echo ============================================
echo  ScenePlay - Windows uninstaller
echo  (reverses install.bat)
echo ============================================
echo.
echo This stops ScenePlay and removes its autostart task, desktop
echo shortcut, firewall rules and Python environment (.venv-win).
echo The folder itself - with ScenePlay.db and your media - stays.
echo.
choice /c YN /m "Uninstall ScenePlay now"
if errorlevel 2 (
    echo Aborted - nothing changed.
    pause
    exit /b 0
)

REM ---- autostart task FIRST so nothing relaunches the app mid-uninstall ----
schtasks /query /tn ScenePlay >nul 2>nul
if not errorlevel 1 (
    schtasks /delete /f /tn ScenePlay >nul 2>nul
    echo [ok] Autostart task removed
) else (
    echo [ok] No autostart task found
)

REM ---------------------------------------------------------- stop the app --
REM Anything running out of .venv-win is ours (the server, yt-dlp children),
REM plus the mpv players the app spawned - matched by their IPC pipe name,
REM never the bare image name, so a user's own mpv window survives.
REM Same idiom as _nt_kill_by_cmdline in sql.py. The $PID check matters:
REM this PowerShell's OWN command line contains ".venv-win", so without it
REM the sweep would kill itself mid-run.
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like '*.venv-win*' -or $_.CommandLine -like '*mpvsocket-*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo [ok] ScenePlay processes stopped

REM ------------------------------------------------------ desktop shortcut --
REM same Desktop lookup as install.bat, so OneDrive-redirected desktops work
powershell -NoProfile -Command ^
  "Remove-Item -LiteralPath ([Environment]::GetFolderPath('Desktop')+'\ScenePlay.lnk') -ErrorAction SilentlyContinue"
echo [ok] Desktop shortcut removed (if it existed)

REM -------------------------------------------------------- firewall rules --
REM The "allow through firewall" prompt created rules bound to the venv's
REM python.exe; removing them needs an Administrator window - best-effort.
net session >nul 2>nul
if errorlevel 1 (
    echo [!] Not running as Administrator - skipping firewall rule cleanup.
    echo     Harmless once .venv-win is gone; or re-run as administrator.
) else (
    powershell -NoProfile -Command ^
      "Get-NetFirewallApplicationFilter -Program '%~dp0.venv-win\Scripts\python.exe' -ErrorAction SilentlyContinue | Get-NetFirewallRule | Remove-NetFirewallRule -ErrorAction SilentlyContinue"
    echo [ok] Firewall rules removed
)

REM ------------------------------------------------------------------ venv --
if exist .venv-win (
    rmdir /s /q .venv-win
    echo [ok] .venv-win removed
) else (
    echo [ok] .venv-win not present
)

REM -------------------------------------------- shared tools: all opt-in ----
REM mpv/ffmpeg/Python are general-purpose - other software may rely on them,
REM so each removal asks first. Detection mirrors install.bat.
set PKGMGR=
where winget >nul 2>nul
if not errorlevel 1 set PKGMGR=winget
if not defined PKGMGR (
    where choco >nul 2>nul
    if not errorlevel 1 set PKGMGR=choco
)
if not defined PKGMGR goto :done

if "%PKGMGR%"=="choco" (
    net session >nul 2>nul
    if errorlevel 1 (
        echo [!] Chocolatey removals need an Administrator window - skipping
        echo     the optional mpv/ffmpeg/Python removal prompts.
        goto :done
    )
)

echo.
echo mpv, ffmpeg and Python are shared tools - only remove what you are
echo sure nothing else on this PC needs.
choice /c YN /m "Remove mpv"
if !errorlevel! equ 1 (
    if "%PKGMGR%"=="winget" ( winget uninstall mpv ) else ( choco uninstall -y mpv )
)
choice /c YN /m "Remove ffmpeg"
if !errorlevel! equ 1 (
    if "%PKGMGR%"=="winget" ( winget uninstall -e --id Gyan.FFmpeg ) else ( choco uninstall -y ffmpeg )
)
choice /c YN /m "Remove Python 3.12"
if !errorlevel! equ 1 (
    if "%PKGMGR%"=="winget" ( winget uninstall -e --id Python.Python.3.12 ) else ( choco uninstall -y python312 )
)

:done
echo.
echo ============================================
echo  Uninstall finished.
echo  This folder still holds ScenePlay.db and
echo  your downloaded media - delete the folder
echo  yourself if you want those gone too.
echo ============================================
pause
