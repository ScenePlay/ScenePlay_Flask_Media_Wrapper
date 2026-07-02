#!/usr/bin/env bash
# Copy shared frontend assets from the local app (source of truth) into the
# relay portal repo. Run this BEFORE committing/deploying ScenePlayRemote,
# so both apps always ship the same copy.
#
# Usage:  scripts/sync_shared_assets.sh
set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RELAY_DIR="$LOCAL_DIR/../ScenePlayRemote"

# source (local repo, authoritative) -> destination (relay repo)
ASSETS=(
  "static/scripts/sfx.js:portal/sfx.js"
  "static/scripts/dice.js:portal/dice.js"
  "static/scripts/Tone.js:portal/Tone.js"
)

for pair in "${ASSETS[@]}"; do
  src="$LOCAL_DIR/${pair%%:*}"
  dst="$RELAY_DIR/${pair##*:}"
  if [ ! -f "$src" ]; then
    echo "MISSING source: $src" >&2
    exit 1
  fi
  if cmp -s "$src" "$dst" 2>/dev/null; then
    echo "unchanged  ${pair##*:}"
  else
    cp "$src" "$dst"
    echo "synced --> ${pair##*:}"
  fi
done
