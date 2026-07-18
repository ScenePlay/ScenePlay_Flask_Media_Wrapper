#!/bin/bash
# Stage a clean copy of the app for FTP deploy: exactly the files git tracks
# (working-tree versions, so uncommitted edits ride along) — no database, no
# .venv, no caches, no backups, no thumbnails. Replaces the old BKPrep zip
# flow, which also swept up ScenePlay.db (a live, un-snapshotted database —
# the "my data got wiped" transfer trap). The target box keeps its OWN
# database; moving DATA between boxes is what the app's Backup/Restore page
# is for.
set -euo pipefail

SRC="/run/media/eric/Transfer/5FD1E1415AC80F29/dev/ScenePlay_Flask_Media_Wrapper"
STAGE="$HOME/Desktop/FTP/ScenePlay"
BK_DIR="$HOME/ScenePlayBK"

rm -rf "$STAGE"
mkdir -p "$STAGE"

# Tracked files only, NUL-separated (safe for any filename); files deleted
# from the working tree but not yet committed are skipped, not fatal.
(cd "$SRC" && git ls-files -z) \
  | rsync -a --files-from=- --from0 --ignore-missing-args "$SRC/" "$STAGE/"

# Dated zip archive of the staged tree (same keep-a-copy habit as before).
mkdir -p "$BK_DIR"
STAMP="ScenePlay-$(date +%Y-%m-%d-%H%M%S).zip"
(cd "$(dirname "$STAGE")" && zip -qr "$BK_DIR/$STAMP" "$(basename "$STAGE")")

echo "staged:  $STAGE"
echo "archive: $BK_DIR/$STAMP"
