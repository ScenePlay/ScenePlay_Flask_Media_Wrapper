#!/bin/bash
source ~/ScenePlay/bin/activate
# Run from the project root so the workers' relative paths
# (./mpv.sh, processMedia/./youtube.sh, ScenePlay.db, effects/*.mp3) resolve.
cd ~/ScenePlay
python3 ~/ScenePlay/ws.py
deactivate