#!/usr/bin/env bash
# Fix "413 Request Entity Too Large" on an EXISTING ScenePlay install:
# nginx defaults to a 1 MB upload cap, which blocks battlemap videos,
# AI-generated art, and backup-restore zips. New installs get the fix via
# supportFiles/default.txt; this patches a live box in place.
#
# Idempotent — safe to run repeatedly. Usage: sudo bash fixNginxUploadSize.sh
set -euo pipefail

CONF=/etc/nginx/sites-available/default

if [ ! -f "$CONF" ]; then
    echo "No $CONF — is nginx installed / was setupAutoStart.sh run?" >&2
    exit 1
fi

if grep -q "client_max_body_size" "$CONF"; then
    echo "client_max_body_size already set in $CONF — nothing to do."
    exit 0
fi

cp "$CONF" "$CONF.bak.$(date +%s)"
# Insert directly after the opening "server {" line
sed -i '0,/server {/s//server {\n\t# No upload size cap (nginx default 1m causes 413 on big uploads)\n\tclient_max_body_size 0;/' "$CONF"

nginx -t
systemctl reload nginx
echo "Done — nginx now accepts large uploads (client_max_body_size 0)."
