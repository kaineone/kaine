#!/usr/bin/env bash
# KAINE first-boot orchestration.
#
# This script SHALL NOT run unattended. It refuses to proceed unless the
# operator has set KAINE_FIRST_BOOT_OPERATOR_PRESENT=1, so accidental
# invocations (CI, hooks, autocomplete) are a no-op.
#
# What this script does, in order:
#   1. Confirms the operator-present gate.
#   2. Asserts required services (Redis, Qdrant) are reachable.
#   3. Asserts external runtime endpoints (Lingua / Audio In / Audio Out)
#      resolve to loopback addresses per shipped config.
#   4. Prints the next manual steps for the operator and exits 0.
#
# This script does NOT start the cognitive cycle. Cycle boot is a
# deliberate, operator-initiated step that happens AFTER inspection
# and confirmation. See FIRST_BOOT.md for the full procedure.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${KAINE_FIRST_BOOT_OPERATOR_PRESENT:-}" != "1" ]]; then
  cat <<'EOF' >&2
KAINE first boot refused: operator must be present.

To proceed, sit at the keyboard and run:

    export KAINE_FIRST_BOOT_OPERATOR_PRESENT=1
    scripts/first-boot.sh

This script does NOT start the cognitive cycle. It only verifies
preconditions and prints the next steps. See FIRST_BOOT.md.
EOF
  exit 2
fi

cd "$PROJECT_ROOT"

echo "==> KAINE first-boot precondition checks"
echo

echo "[1/4] Verifying compose stacks..."
if ! command -v docker >/dev/null 2>&1; then
  echo "  docker not on PATH. Install Docker and re-run." >&2
  exit 3
fi

if ! docker ps --format '{{.Names}}' | grep -q '^kaine-redis$'; then
  echo "  Bring up Redis: scripts/redis-bootstrap.sh" >&2
  exit 3
fi
echo "  Redis container present."

if ! docker ps --format '{{.Names}}' | grep -q '^kaine-qdrant$'; then
  echo "  Bring up Qdrant: scripts/qdrant-bootstrap.sh" >&2
  exit 3
fi
echo "  Qdrant container present."

echo "[2/4] Verifying loopback-only URLs in config..."
config="$PROJECT_ROOT/config/kaine.toml"
for pattern in 'chat_url.*"http' 'speaches_url.*"http' 'chatterbox_url.*"http'; do
  url=$(grep -E "^[[:space:]]*${pattern}" "$config" | head -1 || true)
  if [[ -z "$url" ]]; then continue; fi
  case "$url" in
    *127.0.0.1*|*localhost*) : ;;
    *)
      echo "  Non-loopback URL detected: $url" >&2
      exit 3
      ;;
  esac
done
echo "  All configured runtime URLs are loopback."

echo "[3/4] Verifying secrets file is gitignored..."
if git check-ignore -q config/secrets.toml 2>/dev/null; then
  echo "  config/secrets.toml is gitignored."
else
  if [[ -e config/secrets.toml ]]; then
    echo "  config/secrets.toml exists but is NOT gitignored — refusing." >&2
    exit 3
  fi
  echo "  No secrets file yet (will be created on demand)."
fi

echo "[4/4] Running the test suite..."
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python3
fi
"$PY" -m pytest -q
echo "  Test suite passed."

echo
cat <<'EOF'
==> Preconditions OK.

The cognitive cycle is NOT running. To boot KAINE for the first time:

  1. Read FIRST_BOOT.md end-to-end.
  2. Enable the modules you intend to boot with in config/kaine.toml
     ([modules] section — all are false by default).
  3. Confirm Praxis shell whitelist is what you want (empty by default).
  4. Start the bus AUDIT trail, then start each module in the order
     documented in FIRST_BOOT.md.
  5. Connect Nexus and watch the first ticks.

KAINE first boot is a one-way door. Take your time.
EOF
