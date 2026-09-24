#!/usr/bin/env bash
# Bring the KAINE Qdrant memory store from a fresh clone to a healthy,
# authenticated, ready state in one invocation.
#
# Behaviour:
# - By default, reuse the existing usable KAINE_QDRANT_API_KEY from
#   compose/.env (non-empty and not a placeholder). Generate a fresh key
#   only when there is none.
# - --rotate always generates a fresh API key.
# - --keep-key is an alias for the default behaviour and is kept for
#   backward compatibility.
# - Upserts KAINE_QDRANT_API_KEY in compose/.env via kaine.secrets_file.
# - Mirrors the key into config/secrets.toml under [qdrant].api_key.
# - docker compose down && up -d so the container picks up the value.
# - Confirms /readyz returns 200 with the api-key header.
#
# Idempotent: re-running without flags keeps the current key. Rotate
# explicitly with --rotate to replace the credential.
#
#   bash scripts/qdrant-bootstrap.sh
#   bash scripts/qdrant-bootstrap.sh --keep-key
#   bash scripts/qdrant-bootstrap.sh --rotate

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"; if [[ ! -x "$PY" ]]; then PY=python3; fi

ROTATE=0
KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rotate) ROTATE=1; shift ;;
    --keep-key) KEEP=1; shift ;;
    --help|-h) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

ENV_FILE="compose/.env"
SECRETS_FILE="config/secrets.toml"
SECRETS_EXAMPLE="config/secrets.example.toml"

# 1. Resolve the API key.
KEY=""
if [[ "$ROTATE" -eq 0 && -f "$ENV_FILE" ]]; then
  KEY=$(grep -E '^KAINE_QDRANT_API_KEY=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)
  KEY=${KEY%$'\r'}
  UNUSABLE=0
  if [[ -z "$KEY" || "${#KEY}" -lt 32 ]]; then
    UNUSABLE=1
  else
    shopt -s nocasematch
    if [[ "$KEY" == replace-me* ]]; then
      UNUSABLE=1
    fi
    shopt -u nocasematch
  fi
  if [[ "$UNUSABLE" -eq 1 ]]; then
    if [[ "$KEEP" -eq 1 ]]; then
      echo "==> --keep-key set but no usable existing key; generating new" >&2
    fi
    if [[ -n "$KEY" ]]; then
      echo "==> existing API key is shorter than 32 characters or a placeholder; generating a new one" >&2
    fi
    KEY=""
  else
    echo "==> kept the existing API key from $ENV_FILE; pass --rotate to replace it"
  fi
fi
if [[ -z "$KEY" ]]; then
  KEY=$(openssl rand -hex 32)
  echo "==> generated a fresh random API key"
fi

# 2. Upsert the KAINE_QDRANT_API_KEY line in compose/.env without
# touching the Redis password if it's already there.
umask 077
printf '%s\n' "$KEY" | "$PY" -m kaine.secrets_file env "$ENV_FILE" KAINE_QDRANT_API_KEY -
chmod 600 "$ENV_FILE"
echo "==> updated $ENV_FILE with KAINE_QDRANT_API_KEY"

# 3. Mirror into config/secrets.toml under [qdrant].api_key.
if [[ ! -f "$SECRETS_FILE" ]]; then
  cp "$SECRETS_EXAMPLE" "$SECRETS_FILE"
  echo "==> created $SECRETS_FILE from example"
fi
chmod 600 "$SECRETS_FILE"
printf '%s\n' "$KEY" | "$PY" -m kaine.secrets_file toml "$SECRETS_FILE" qdrant api_key -
echo "==> mirrored api_key into $SECRETS_FILE"

# 4. Recreate the container.
echo "==> docker compose -f compose/qdrant.yml down"
docker compose -f compose/qdrant.yml down --remove-orphans 2>&1 | sed 's/^/    /' || true
echo "==> docker compose -f compose/qdrant.yml up -d"
KAINE_QDRANT_API_KEY="$KEY" docker compose -f compose/qdrant.yml up -d 2>&1 | sed 's/^/    /'

# 5. Wait for /readyz.
PORT="${KAINE_QDRANT_HOST_PORT:-6533}"
echo -n "==> waiting for kaine-qdrant /readyz"
for i in $(seq 1 60); do
  if printf 'api-key: %s\n' "$KEY" | curl -fsS -H @- "http://127.0.0.1:${PORT}/readyz" >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  echo -n "."
  sleep 0.5
  if [[ "$i" -eq 60 ]]; then
    echo
    echo "==> timed out waiting for /readyz; container logs:" >&2
    docker compose -f compose/qdrant.yml logs --tail=40 kaine-qdrant >&2
    exit 3
  fi
done

echo "==> kaine-qdrant is up at 127.0.0.1:${PORT} and authenticated"
echo "    api key lives in $ENV_FILE (mode 600) and $SECRETS_FILE (mode 600)"
