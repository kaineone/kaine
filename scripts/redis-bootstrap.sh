#!/usr/bin/env bash
# Bring the KAINE Redis bus from a fresh clone to a healthy, authenticated,
# ping-able state in one invocation.
#
# Behaviour:
# - By default, use Docker when it is present and fall back to a native
#   user-level redis-server otherwise. Pass --native or --container to choose.
# - Reuse the existing usable KAINE_REDIS_PASSWORD from compose/.env
#   (non-empty and not the placeholder). Generate a fresh password only when
#   there is none.
# - --rotate always generates a fresh password.
# - --keep-password is an alias for the default behaviour and is kept for
#   backward compatibility.
# - Upserts KAINE_REDIS_PASSWORD in compose/.env via kaine.secrets_file.
# - Mirrors the password into config/secrets.toml under [redis].password.
# - Brings the chosen runtime up so the container/native server picks up the value.
# - Confirms the bus answers PING with PONG.
#
# Idempotent: re-running without flags keeps the current password. Rotate
# explicitly with --rotate to replace the credential.
#
#   bash scripts/redis-bootstrap.sh
#   bash scripts/redis-bootstrap.sh --keep-password
#   bash scripts/redis-bootstrap.sh --rotate

# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"; if [[ ! -x "$PY" ]]; then PY=python3; fi

source "$ROOT/scripts/lib/native-services.sh"

ROTATE=0
KEEP=0
NATIVE_FLAG=0
CONTAINER_FLAG=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rotate) ROTATE=1; shift ;;
    --keep-password) KEEP=1; shift ;;
    --native) NATIVE_FLAG=1; shift ;;
    --container) CONTAINER_FLAG=1; shift ;;
    --help|-h) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ "$NATIVE_FLAG" -eq 1 && "$CONTAINER_FLAG" -eq 1 ]]; then
  echo "==> cannot use --native and --container together" >&2
  exit 2
fi

MODE=""
if [[ "$NATIVE_FLAG" -eq 1 ]]; then
  MODE="native"
elif [[ "$CONTAINER_FLAG" -eq 1 ]]; then
  MODE="container"
fi
detect_runtime_mode "$MODE"

ENV_FILE="compose/.env"
SECRETS_FILE="config/secrets.toml"
SECRETS_EXAMPLE="config/secrets.example.toml"

# Rotating a running shared container requires an explicit --container.
if [[ "$RUNTIME_MODE" == "container" && "$ROTATE" -eq 1 && "$CONTAINER_FLAG" -eq 0 ]] && container_is_running redis; then
  echo "==> kaine-redis container is already running; --rotate requires --container to recreate the shared container" >&2
  exit 2
fi

# 1. Resolve the password (shared code path for both runtimes).
PW=""
resolve_credential KAINE_REDIS_PASSWORD redis password "$ROTATE" "$KEEP" PW

# 2. Write compose/.env.
write_env_credential "$ENV_FILE" KAINE_REDIS_PASSWORD "$PW" "$PY"

# 3. Mirror into config/secrets.toml.
mirror_toml_credential "$SECRETS_FILE" "$SECRETS_EXAMPLE" redis password "$PW" "$PY"

# 4. Bring up the chosen runtime.
if [[ "$RUNTIME_MODE" == "container" ]]; then
  if [[ "$CONTAINER_FLAG" -eq 0 ]] && container_is_running redis; then
    echo "==> kaine-redis container is already running; verifying health"
    if wait_redis_ping "$PW" 127.0.0.1 6479 30; then
      echo "==> kaine-redis container is healthy and was left untouched"
      exit 0
    fi
    echo "==> kaine-redis container is running but not answering; refusing to recreate it without --container" >&2
    exit 3
  fi

  echo "==> docker compose -f compose/redis.yml down"
  docker compose -f compose/redis.yml down --remove-orphans 2>&1 | sed 's/^/    /' || true
  echo "==> docker compose -f compose/redis.yml up -d"
  KAINE_REDIS_PASSWORD="$PW" docker compose -f compose/redis.yml up -d 2>&1 | sed 's/^/    /'
else
  native_bootstrap_redis "$ROOT" "$PW" "$ROTATE"
fi

# 5. Wait for healthy, then ping.
if ! wait_redis_ping "$PW" 127.0.0.1 6479 30; then
  if [[ "$RUNTIME_MODE" == "container" ]]; then
    echo "==> container logs:" >&2
    docker compose -f compose/redis.yml logs --tail=40 kaine-redis >&2
  fi
  exit 3
fi

echo "==> kaine-redis is up at 127.0.0.1:6479 and authenticated"
echo "    password lives in $ENV_FILE (mode 600) and $SECRETS_FILE (mode 600)"
echo "    rotate later with: bash scripts/redis-bootstrap.sh --rotate"
