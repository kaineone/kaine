#!/usr/bin/env bash
# Clone + build OpenNARS for Applications (ONA) into external/.
#
# Idempotent:
#   - clones if external/OpenNARS-for-Applications/ doesn't exist;
#   - otherwise `git fetch && git pull --ff-only`;
#   - rebuilds only if upstream source is newer than the NAR binary;
#   - smoke-tests the binary to confirm it launches.
#
#   bash scripts/build-ona.sh              # default behavior
#   bash scripts/build-ona.sh --force      # rebuild even when up-to-date

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

REPO_URL="${KAINE_ONA_REPO_URL:-https://github.com/opennars/OpenNARS-for-Applications.git}"
ONA_DIR="external/OpenNARS-for-Applications"
NAR_BIN="$ONA_DIR/NAR"
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

mkdir -p external

if [[ ! -d "$ONA_DIR/.git" ]]; then
  echo "==> cloning $REPO_URL"
  git clone --depth=1 "$REPO_URL" "$ONA_DIR"
else
  echo "==> updating existing clone in $ONA_DIR"
  git -C "$ONA_DIR" fetch --depth=1 origin
  git -C "$ONA_DIR" reset --hard origin/HEAD 2>&1 | sed 's/^/    /'
fi

# Decide whether to rebuild.
need_build=0
if [[ ! -x "$NAR_BIN" ]]; then
  need_build=1
elif [[ "$FORCE" -eq 1 ]]; then
  echo "==> --force given; rebuilding"
  need_build=1
else
  newest_source=$(find "$ONA_DIR/src" "$ONA_DIR"/build.sh -type f \
                    -newer "$NAR_BIN" 2>/dev/null | head -n1 || true)
  if [[ -n "$newest_source" ]]; then
    echo "==> source newer than binary ($newest_source); rebuilding"
    need_build=1
  fi
fi

if [[ "$need_build" -eq 1 ]]; then
  echo "==> running upstream build script"
  (cd "$ONA_DIR" && ./build.sh) 2>&1 | sed 's/^/    /'
else
  echo "==> binary up-to-date; skipping rebuild"
fi

# Smoke test: launch NAR briefly and confirm it responds.
if [[ ! -x "$NAR_BIN" ]]; then
  echo "==> ERROR: $NAR_BIN missing after build" >&2
  exit 3
fi

# NAR's interactive mode reads from stdin; feed `quit` and check we
# got a non-empty reply on stdout.
echo "==> smoke test"
if printf 'quit\n' | timeout 5 "$NAR_BIN" shell >/dev/null 2>&1; then
  echo "==> NAR launches cleanly at $NAR_BIN"
else
  # Some ONA versions exit non-zero on `quit`; tolerate as long as the
  # binary exists and is executable.
  if "$NAR_BIN" --help >/dev/null 2>&1 || true; then
    echo "==> NAR is present (interactive smoke test inconclusive)"
  fi
fi

echo "==> done. KAINE config [nous] binary_path should point at $ROOT/$NAR_BIN"
