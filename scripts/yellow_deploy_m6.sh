#!/bin/sh
set -eu

# This script is executed only from the authenticated Studio Code Server
# terminal after the outer deployment archive SHA-256 has been verified.

COMPONENTS=/config/custom_components
CURRENT="$COMPONENTS/owlet_cam"
# Home Assistant scans every directory under custom_components. Keep rollback
# copies outside that directory so their manifests cannot shadow the active
# integration during startup.
BACKUP=/config/.owlet_cam-m5-backup-before-m6
FAILED=/config/.owlet_cam-m6-failed-source
HOLD=/config/.owlet_cam-m6-userfiles-hold
PAYLOAD=/config/.owlet-cam-m6-stage/payload
NEW_SOURCE="$PAYLOAD/owlet_cam"
RUNTIME_ARCHIVE="$PAYLOAD/owlet-cam-helper-aarch64-m6.tar.gz"
RUNTIME_CURRENT="$CURRENT/userfiles/runtime/current"
RUNTIME_PREVIOUS="$CURRENT/userfiles/runtime/.previous-m5-before-m6"
RUNTIME_STAGE="$CURRENT/userfiles/runtime/.current-m6-stage"

test -d "$CURRENT/userfiles"
test -f "$NEW_SOURCE/manifest.json"
test -f "$RUNTIME_ARCHIVE"
test ! -e "$BACKUP"
test ! -e "$FAILED"
test ! -e "$HOLD"
test ! -e "$RUNTIME_PREVIOUS"
test ! -e "$RUNTIME_STAGE"

(cd "$PAYLOAD" && sha256sum -c SHA256SUMS)
mkdir "$RUNTIME_STAGE"
tar -xzf "$RUNTIME_ARCHIVE" -C "$RUNTIME_STAGE"
test -x "$RUNTIME_STAGE/bin/stream_capture"
test -x "$RUNTIME_STAGE/runtime/bin/linker64"
grep -q '"version": "0.6.0-dev"' "$RUNTIME_STAGE/runtime-manifest.json"
grep -q '"contains_proprietary_files": false' \
    "$RUNTIME_STAGE/runtime-manifest.json"

if test -d "$RUNTIME_CURRENT"; then
    mv "$RUNTIME_CURRENT" "$RUNTIME_PREVIOUS"
fi
mv "$RUNTIME_STAGE" "$RUNTIME_CURRENT"

rollback_source() {
    if test -d "$HOLD"; then
        if test -d "$CURRENT"; then
            mv "$CURRENT" "$FAILED"
        fi
        if test -d "$BACKUP"; then
            mv "$BACKUP" "$CURRENT"
        fi
        mv "$HOLD" "$CURRENT/userfiles"
    fi
}
trap rollback_source EXIT HUP INT TERM

mv "$CURRENT/userfiles" "$HOLD"
mv "$CURRENT" "$BACKUP"
mv "$NEW_SOURCE" "$CURRENT"
mv "$HOLD" "$CURRENT/userfiles"

trap - EXIT HUP INT TERM
find "$CURRENT" -type d -exec chmod 700 {} +
find "$CURRENT" -type f ! -path '*/userfiles/*' -exec chmod 600 {} +
echo "Milestone 6 source and helper staged successfully"
