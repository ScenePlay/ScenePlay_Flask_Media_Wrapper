#!/usr/bin/env bash
# Install the repo's git hooks (secret guard + auto-version bump). Run once after
# cloning; safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
install -m 755 "$DIR/scripts/git-hooks/pre-commit" "$DIR/.git/hooks/pre-commit"
echo "installed .git/hooks/pre-commit (secret guard + auto-version bump)"
