@echo off
REM ScenePlay on Windows - always run from the repo root so the workers'
REM relative paths (ScenePlay.db, effects\*.mp3) resolve, and always start
REM via ws.py (running app.py directly crashes: it expects an argv flag).
REM .venv-win is the Windows venv; .venv is the LINUX one (shared HDD), so
REM run the venv python directly - a bare `python` fallback silently loses
REM yt-dlp and friends.
REM The server runs inside a PowerShell console (not cmd). -NoExit keeps the
REM window open after the app exits or crashes so the last output stays
REM readable (replaces the old `pause`).
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -Command "Set-Location -LiteralPath '%~dp0'; if (-not (Test-Path '.venv-win\Scripts\python.exe')) { Write-Host '[!] .venv-win not found - run install.bat first.' -ForegroundColor Red } else { & '.venv-win\Scripts\python.exe' ws.py }"
