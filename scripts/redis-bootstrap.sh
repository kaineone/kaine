#!/usr/bin/env bash
# Bring the KAINE Redis bus from a fresh clone to a healthy, authenticated,
# ping-able state in one invocation.
#
# Behaviour:
# - By default, reuse the existing usable KAINE_REDIS_PASSWORD from compose/.env
#   (non-empty and not the placeholder). Generate a fresh password only when
#   there is none.
# - --rotate always generates a fresh password.
# - --keep-password is an alias for the default behaviour and is kept for
#   backward compatibility.
# - Upserts KAINE_REDIS_PASSWORD in compose/.env via kaine.secrets_file.
# - Mirrors the password into config/secrets.toml under [redis].password.
# - docker compose down && up -d so the container picks up the value.
# - Confirms the bus answers PING with PONG.
#
# Idempotent: re-running without flags keeps the current password. Rotate
# explicitly with --rotate to replace the credential.
#
#   bash scripts/redis-bootstrap.sh
#   bash scripts/redis-bootstrap.sh --keep-password
#   bash scripts/redis-bootstrap.sh --rotate

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"; if [[ ! -x "$PY" ]]; then PY=python3; fi

ROTATE=0
KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rotate) ROTATE=1; shift ;;
    --keep-password) KEEP=1; shift ;;
    --help|-h) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

ENV_FILE="compose/.env"
SECRETS_FILE="config/secrets.toml"
SECRETS_EXAMPLE="config/secrets.example.toml"

# 1. Resolve the password.
PW=""
if [[ "$ROTATE" -eq 0 && -f "$ENV_FILE" ]]; then
  PW=$(grep -E '^KAINE_REDIS_PASSWORD=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)
  PW=${PW%$'\r'}
  UNUSABLE=0
  if [[ -z "$PW" || "${#PW}" -lt 32 ]]; then
    UNUSABLE=1
  else
    shopt -s nocasematch
    if [[ "$PW" == replace-me* ]]; then
      UNUSABLE=1
    fi
    shopt -u nocasematch
  fi
  if [[ "$UNUSABLE" -eq 1 ]]; then
    if [[ "$KEEP" -eq 1 ]]; then
      echo "==> --keep-password set but no usable existing password; generating new" >&2
    fi
    if [[ -n "$PW" ]]; then
      echo "==> existing password is shorter than 32 characters or a placeholder; generating a new one" >&2
    fi
    PW=""
  else
    echo "==> kept the existing password from $ENV_FILE; pass --rotate to replace it"
  fi
fi
if [[ -z "$PW" ]]; then
  PW=$(openssl rand -hex 32)
  echo "==> generated a fresh random password"
fi

# 2. Write compose/.env.
umask 077
printf '%s\n' "$PW" | "$PY" -m kaine.secrets_file env "$ENV_FILE" KAINE_REDIS_PASSWORD -
chmod 600 "$ENV_FILE"
echo "==> wrote $ENV_FILE (mode 600)"

# 3. Mirror into config/secrets.toml.
if [[ ! -f "$SECRETS_FILE" ]]; then
  cp "$SECRETS_EXAMPLE" "$SECRETS_FILE"
  echo "==> created $SECRETS_FILE from example"
fi
chmod 600 "$SECRETS_FILE"
printf '%s\n' "$PW" | "$PY" -m kaine.secrets_file toml "$SECRETS_FILE" redis password -
echo "==> mirrored password into $SECRETS_FILE"

# 4. Recreate the container so the new password takes effect.
echo "==> docker compose -f compose/redis.yml down"
docker compose -f compose/redis.yml down --remove-orphans 2>&1 | sed 's/^/    /' || true
echo "==> docker compose -f compose/redis.yml up -d"
KAINE_REDIS_PASSWORD="$PW" docker compose -f compose/redis.yml up -d 2>&1 | sed 's/^/    /'

# 5. Wait for healthy, then ping.
echo -n "==> waiting for kaine-redis to be ready"
for i in $(seq 1 30); do
  if REDISCLI_AUTH="$PW" redis-cli -h 127.0.0.1 -p 6479 --no-auth-warning ping 2>/dev/null | grep -q PONG; then
    echo " ok"
    break
  fi
  echo -n "."
  sleep 0.5
  if [[ "$i" -eq 30 ]]; then
    echo
    echo "==> timed out waiting for PONG; container logs:" >&2
    docker compose -f compose/redis.yml logs --tail=40 kaine-redis >&2
    exit 3
  fi
done

echo "==> kaine-redis is up at 127.0.0.1:6479 and authenticated"
echo "    password lives in $ENV_FILE (mode 600) and $SECRETS_FILE (mode 600)"
echo "    rotate later with: bash scripts/redis-bootstrap.sh --rotate"
