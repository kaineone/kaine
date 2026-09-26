#!/usr/bin/env bash
# Bring the KAINE Qdrant memory store from a fresh clone to a healthy,
# authenticated, ready state in one invocation.
#
# Behaviour:
# - By default, use Docker when it is present and fall back to a native
#   downloaded binary otherwise. Pass --native or --container to choose.
# - Reuse the existing usable KAINE_QDRANT_API_KEY from compose/.env
#   (non-empty and not a placeholder). Generate a fresh key only when
#   there is none.
# - --rotate always generates a fresh API key.
# - --keep-key is an alias for the default behaviour and is kept for
#   backward compatibility.
# - Upserts KAINE_QDRANT_API_KEY in compose/.env via kaine.secrets_file.
# - Mirrors the key into config/secrets.toml under [qdrant].api_key.
# - Brings the chosen runtime up so the container/native server picks up the value.
# - Confirms /readyz returns 200 with the api-key header.
#
# Idempotent: re-running without flags keeps the current key. Rotate
# explicitly with --rotate to replace the credential.
#
#   bash scripts/qdrant-bootstrap.sh
#   bash scripts/qdrant-bootstrap.sh --keep-key
#   bash scripts/qdrant-bootstrap.sh --rotate

# SPDX-License-Identifier: LicenseRef-CAL-0.2
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
    --keep-key) KEEP=1; shift ;;
    --native) NATIVE_FLAG=1; shift ;;
    --container) CONTAINER_FLAG=1; shift ;;
    --help|-h) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

# Qdrant has no Android build; on Termux the memory backend is sqlite_vec.
if is_termux; then
  echo "==> Qdrant has no Android build. On Termux use [mnemos].backend = \"sqlite_vec\" (phase 3)."
  exit 0
fi

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
if [[ "$RUNTIME_MODE" == "container" && "$ROTATE" -eq 1 && "$CONTAINER_FLAG" -eq 0 ]] && container_is_running qdrant; then
  echo "==> kaine-qdrant container is already running; --rotate requires --container to recreate the shared container" >&2
  exit 2
fi

# 1. Resolve the API key (shared code path for both runtimes).
KEY=""
resolve_credential KAINE_QDRANT_API_KEY qdrant api_key "$ROTATE" "$KEEP" KEY

# 2. Upsert the KAINE_QDRANT_API_KEY line in compose/.env.
write_env_credential "$ENV_FILE" KAINE_QDRANT_API_KEY "$KEY" "$PY"

# 3. Mirror into config/secrets.toml under [qdrant].api_key.
mirror_toml_credential "$SECRETS_FILE" "$SECRETS_EXAMPLE" qdrant api_key "$KEY" "$PY"

# 4. Bring up the chosen runtime.
if [[ "$RUNTIME_MODE" == "container" ]]; then
  if [[ "$CONTAINER_FLAG" -eq 0 ]] && container_is_running qdrant; then
    echo "==> kaine-qdrant container is already running; verifying health"
    PORT="${KAINE_QDRANT_HOST_PORT:-6533}"
    if wait_qdrant_readyz "$KEY" 127.0.0.1 "$PORT" 60; then
      echo "==> kaine-qdrant container is healthy and was left untouched"
      exit 0
    fi
    echo "==> kaine-qdrant container is running but not answering; refusing to recreate it without --container" >&2
    exit 3
  fi

  echo "==> docker compose -f compose/qdrant.yml down"
  docker compose -f compose/qdrant.yml down --remove-orphans 2>&1 | sed 's/^/    /' || true
  echo "==> docker compose -f compose/qdrant.yml up -d"
  KAINE_QDRANT_API_KEY="$KEY" docker compose -f compose/qdrant.yml up -d 2>&1 | sed 's/^/    /'
else
  native_bootstrap_qdrant "$ROOT" "$KEY" "$ROTATE"
fi

# 5. Wait for /readyz.
PORT="${KAINE_QDRANT_HOST_PORT:-6533}"
if [[ "$RUNTIME_MODE" == "native" ]]; then
  PORT=6533
fi
if ! wait_qdrant_readyz "$KEY" 127.0.0.1 "$PORT" 60; then
  if [[ "$RUNTIME_MODE" == "container" ]]; then
    echo "==> container logs:" >&2
    docker compose -f compose/qdrant.yml logs --tail=40 kaine-qdrant >&2
  fi
  exit 3
fi

echo "==> kaine-qdrant is up at 127.0.0.1:${PORT} and authenticated"
echo "    api key lives in $ENV_FILE (mode 600) and $SECRETS_FILE (mode 600)"
