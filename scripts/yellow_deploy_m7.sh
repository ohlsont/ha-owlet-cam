#!/bin/sh
set -eu

# Run only from Home Assistant's authenticated Terminal & SSH ingress after the
# outer deployment archive and every source file checksum have been verified.

COMPONENTS=/config/custom_components
CURRENT="$COMPONENTS/owlet_cam"
BACKUP=/config/.owlet-cam-m7-backup-before-panel
FAILED=/config/.owlet-cam-m7-failed-source
HOLD=/config/.owlet-cam-m7-userfiles-hold
PAYLOAD=/config/.owlet-cam-m7-stage/payload
NEW_SOURCE="$PAYLOAD/owlet_cam"

test -d "$CURRENT/userfiles"
test -f "$NEW_SOURCE/manifest.json"
test -f "$NEW_SOURCE/http.py"
test -f "$NEW_SOURCE/frontend/owlet-cam-panel.js"
test -f "$PAYLOAD/SOURCE_SHA256SUMS"
test ! -e "$BACKUP"
test ! -e "$FAILED"
test ! -e "$HOLD"

(cd "$PAYLOAD" && sha256sum -c SOURCE_SHA256SUMS)

# The deployed source stub contains no runtime material. Preserve the complete
# existing private directory instead of merging or copying it.
test -f "$NEW_SOURCE/userfiles/.gitkeep"
test -f "$NEW_SOURCE/userfiles/README.md"
test "$(find "$NEW_SOURCE/userfiles" -type f | wc -l)" -eq 2
rm "$NEW_SOURCE/userfiles/.gitkeep" "$NEW_SOURCE/userfiles/README.md"
rmdir "$NEW_SOURCE/userfiles"

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
find "$CURRENT" -type d ! -path '*/userfiles/*' -exec chmod 700 {} +
find "$CURRENT" -type f ! -path '*/userfiles/*' -exec chmod 600 {} +
echo "Milestone 7 source staged successfully; private userfiles preserved"
