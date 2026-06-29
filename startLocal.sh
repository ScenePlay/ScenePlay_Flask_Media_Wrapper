#!/bin/bash
source .venv/bin/activate
# Run from the current directory so the workers' relative paths
# (./mpv.sh, processMedia/./youtube.sh, ScenePlay.db, effects/*.mp3) resolve.
cd "$PWD"
python3 ws.py
deactivate
