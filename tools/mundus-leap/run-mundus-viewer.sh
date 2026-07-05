#!/usr/bin/env bash
# Launch the FORKED Firestorm/OpenSim viewer (with the captureFrame vision op)
# logged in as the KAINE bot avatar, with the Mundus LEAP shim driving it.
#
# Usage:  MUNDUS_BOT_PASSWORD='...' tools/mundus-leap/run-mundus-viewer.sh
#
# Needs a display (run it from your desktop session). The shim's log + the
# captured frame land in $MUNDUS_STATE_DIR.
set -euo pipefail

# All paths/addresses are operator-specific — override via env or edit here.
# REPO defaults to this repo (resolved from the script location); VIEWER_DIR must
# point at your built forked-Firestorm package; LOGINURI is your OpenSim grid's
# address on your private mesh (e.g. http://<world-host>:9000/).
REPO="${KAINE_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VIEWER_DIR="${MUNDUS_VIEWER_DIR:?set MUNDUS_VIEWER_DIR to your built forked-Firestorm newview/packaged dir}"
SHIM="$REPO/.venv/bin/python $REPO/tools/mundus-leap/mundus_leap.py"
LOGINURI="${MUNDUS_LOGIN_URI:?set MUNDUS_LOGIN_URI to your grid, e.g. http://<world-host>:9000/}"

: "${MUNDUS_BOT_PASSWORD:?set MUNDUS_BOT_PASSWORD to the Kaine One account password}"
export MUNDUS_STATE_DIR="${MUNDUS_STATE_DIR:-$REPO/state/mundus}"
export MUNDUS_MODE="${MUNDUS_MODE:-demo}"
mkdir -p "$MUNDUS_STATE_DIR"

# Ensure the forked viewer knows the grid (added directly to its
# app_settings/grids.xml; seed from the stock viewer only if somehow missing).
GRID_AUTHORITY="${LOGINURI#http://}"; GRID_AUTHORITY="${GRID_AUTHORITY%/}"
if ! grep -q "$GRID_AUTHORITY" "$VIEWER_DIR/app_settings/grids.xml" 2>/dev/null; then
  cp "$HOME/firestorm/app_settings/grids.xml" "$VIEWER_DIR/app_settings/grids.xml"
  echo "seeded grid into the forked viewer"
fi

cd "$VIEWER_DIR"
echo "launching forked viewer as Kaine One -> $LOGINURI"
echo "shim log: $MUNDUS_STATE_DIR/shim.log"
exec ./firestorm \
  --loginuri "$LOGINURI" \
  --login Kaine One "$MUNDUS_BOT_PASSWORD" \
  --leap "$SHIM"
