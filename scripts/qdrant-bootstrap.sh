#!/usr/bin/env bash
# Bring the KAINE Qdrant memory store from a fresh clone to a healthy,
# authenticated, ready state in one invocation. Mirrors
# scripts/redis-bootstrap.sh.
#
# - Generates a random API key (or preserves with --keep-key).
# - Writes/updates compose/.env to set KAINE_QDRANT_API_KEY=<value>
#   exactly once; preserves the existing KAINE_REDIS_PASSWORD line.
# - Mirrors the key into config/secrets.toml under [qdrant].api_key.
# - docker compose down && up -d so the container picks up the value.
# - Confirms `/readyz` returns 200 with the api-key header.
#
#   bash scripts/qdrant-bootstrap.sh
#   bash scripts/qdrant-bootstrap.sh --keep-key

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-key) KEEP=1; shift ;;
    --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

ENV_FILE="compose/.env"
SECRETS_FILE="config/secrets.toml"
SECRETS_EXAMPLE="config/secrets.example.toml"

# 1. Resolve the API key.
KEY=""
if [[ "$KEEP" -eq 1 && -f "$ENV_FILE" ]]; then
  KEY=$(grep -E '^KAINE_QDRANT_API_KEY=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)
  if [[ -z "$KEY" || "$KEY" == "replace-me-with-a-strong-random-api-key" ]]; then
    echo "==> --keep-key set but no usable existing key; generating new" >&2
    KEY=""
  fi
fi
if [[ -z "$KEY" ]]; then
  KEY=$(openssl rand -hex 32)
  echo "==> generated a fresh random API key"
else
  echo "==> preserving existing API key from $ENV_FILE"
fi

# 2. Upsert the KAINE_QDRANT_API_KEY line in compose/.env without
# touching the Redis password if it's already there.
umask 077
if [[ ! -f "$ENV_FILE" ]]; then
  touch "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
if grep -qE '^KAINE_QDRANT_API_KEY=' "$ENV_FILE"; then
  sed -i.bak -E "s|^KAINE_QDRANT_API_KEY=.*|KAINE_QDRANT_API_KEY=$KEY|" "$ENV_FILE"
  rm -f "${ENV_FILE}.bak"
else
  printf 'KAINE_QDRANT_API_KEY=%s\n' "$KEY" >> "$ENV_FILE"
fi
echo "==> updated $ENV_FILE with KAINE_QDRANT_API_KEY"

# 3. Mirror into config/secrets.toml under [qdrant].api_key.
if [[ ! -f "$SECRETS_FILE" ]]; then
  cp "$SECRETS_EXAMPLE" "$SECRETS_FILE"
  echo "==> created $SECRETS_FILE from example"
fi
chmod 600 "$SECRETS_FILE"
if grep -qE '^\[qdrant\]' "$SECRETS_FILE"; then
  # Replace api_key under [qdrant]. Use a Python helper for safety
  # because sed inside a section is fiddly across BSD/GNU.
  python3 - "$SECRETS_FILE" "$KEY" <<'PY'
import re, sys, pathlib
path, key = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8")
def replace_under_section(text, section, field, value):
    pattern = re.compile(
        rf"(\[{section}\][^\[]*?\n)([ \t]*{field}\s*=\s*\".*?\")",
        re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(lambda m: m.group(1) + f"{field} = \"{value}\"", text)
    # Append into the section
    pattern2 = re.compile(rf"(\[{section}\][^\[]*?)(\n\[|\Z)", re.DOTALL)
    return pattern2.sub(
        lambda m: m.group(1).rstrip() + f"\n{field} = \"{value}\"\n" + (m.group(2) or ""),
        text,
    )
text = replace_under_section(text, "qdrant", "api_key", key)
path.write_text(text, encoding="utf-8")
PY
else
  printf '\n[qdrant]\napi_key = "%s"\n' "$KEY" >> "$SECRETS_FILE"
fi
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
  if curl -fsS -H "api-key: $KEY" "http://127.0.0.1:${PORT}/readyz" >/dev/null 2>&1; then
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
