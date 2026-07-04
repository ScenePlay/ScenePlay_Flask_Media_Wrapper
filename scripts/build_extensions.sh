#!/bin/bash
# Package the browser extensions into static/ext so users can download them
# straight from the ScenePlay server (Utilities page links there).
#
# A Firefox .xpi is just a zip with manifest.json at the archive ROOT — the
# same file Mozilla signs if submitted to AMO. Unsigned, it installs
# permanently only on ESR / Developer Edition / Nightly with
# xpinstall.signatures.required=false (release Firefox requires AMO signing).
set -e
cd "$(dirname "$0")/.."
mkdir -p static/ext
rm -f static/ext/ScenePlay-firefox.xpi static/ext/ScenePlay-chrome.zip
(cd FireFoxExt && zip -q ../static/ext/ScenePlay-firefox.xpi manifest.json popup.html popup.js icon.png)
(cd ChromeExt  && zip -q ../static/ext/ScenePlay-chrome.zip  manifest.json popup.html popup.js icon.png)
echo "built:"
ls -la static/ext/ScenePlay-firefox.xpi static/ext/ScenePlay-chrome.zip
