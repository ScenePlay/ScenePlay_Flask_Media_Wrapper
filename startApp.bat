@echo off
REM ScenePlay on Windows — always run from the repo root so the workers'
REM relative paths (ScenePlay.db, effects\*.mp3) resolve, and always start
REM via ws.py (running app.py directly crashes: it expects an argv flag).
REM .venv-win is the Windows venv; .venv is the LINUX one (shared HDD), so
REM run the venv python directly — a bare `python` fallback silently loses
REM yt-dlp and friends.
cd /d %~dp0
if not exist .venv-win\Scripts\python.exe (
    echo [!] .venv-win not found - run install.bat first.
    pause
    exit /b 1
)
.venv-win\Scripts\python.exe ws.py
