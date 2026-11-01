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
#   3. Asserts external runtime endpoints (language / audio in / audio out)
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

echo "[1/4] Verifying bus and memory store are reachable..."

PW=""
KEY=""
if [[ -f compose/.env ]]; then
  PW=$(grep -E '^KAINE_REDIS_PASSWORD=' compose/.env | tail -n1 | cut -d= -f2- || true)
  PW=${PW%$'\r'}
  KEY=$(grep -E '^KAINE_QDRANT_API_KEY=' compose/.env | tail -n1 | cut -d= -f2- || true)
  KEY=${KEY%$'\r'}
fi

REDIS_OK=0
if [[ -n "$PW" ]] && command -v redis-cli >/dev/null 2>&1; then
  if REDISCLI_AUTH="$PW" redis-cli -h 127.0.0.1 -p 6479 --no-auth-warning ping 2>/dev/null | grep -q PONG; then
    REDIS_OK=1
    echo "  Redis answers PONG."
  fi
fi

QDRANT_OK=0
PORT="${KAINE_QDRANT_HOST_PORT:-6533}"
if [[ -n "$KEY" ]] && command -v curl >/dev/null 2>&1; then
  if printf 'api-key: %s\n' "$KEY" | curl -fsS -H @- "http://127.0.0.1:${PORT}/readyz" >/dev/null 2>&1; then
    QDRANT_OK=1
    echo "  Qdrant /readyz is healthy."
  fi
fi

if [[ "$REDIS_OK" -eq 0 ]]; then
  echo "  Redis is not reachable. Bring it up with: scripts/redis-bootstrap.sh" >&2
fi
if [[ "$QDRANT_OK" -eq 0 ]]; then
  echo "  Qdrant is not reachable. Bring it up with: scripts/qdrant-bootstrap.sh" >&2
fi
if [[ "$REDIS_OK" -eq 0 || "$QDRANT_OK" -eq 0 ]]; then
  exit 3
fi

# The never-persisted bus holds heard and spoken words and latent values on
# companion streams. It has no host port, so it is checked inside its container:
# it must answer and must not persist (appendonly no, empty save). The cycle
# refuses to start a module that needs it otherwise.
VOLATILE_OK=0
if command -v docker >/dev/null 2>&1; then
  vol_cfg=$(docker exec kaine-redis-volatile sh -c \
    'REDISCLI_AUTH="$KAINE_REDIS_VOLATILE_PASSWORD" redis-cli --no-auth-warning CONFIG GET appendonly; REDISCLI_AUTH="$KAINE_REDIS_VOLATILE_PASSWORD" redis-cli --no-auth-warning CONFIG GET save' \
    2>/dev/null || true)
  appendonly=$(printf '%s\n' "$vol_cfg" | sed -n '2p')
  save=$(printf '%s\n' "$vol_cfg" | sed -n '4p')
  if [[ "$appendonly" == "no" && -z "$save" && -n "$vol_cfg" ]]; then
    VOLATILE_OK=1
    echo "  The never-persisted bus answers and does not persist."
  fi
fi
if [[ "$VOLATILE_OK" -eq 0 ]]; then
  echo "  The never-persisted bus (kaine-redis-volatile) is not running, or it persists." >&2
  echo "  Set KAINE_REDIS_VOLATILE_PASSWORD in compose/.env and start it with:" >&2
  echo "    docker compose -f compose/kaine.yml up -d kaine-redis-volatile" >&2
  exit 3
fi

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
  3. Confirm the effectors shell whitelist is what you want (empty by default).
  4. Start the bus AUDIT trail, then start each module in the order
     documented in FIRST_BOOT.md.
  5. Connect the dashboard and watch the first ticks.

KAINE first boot is a one-way door. Take your time.
EOF
