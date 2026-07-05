#!/usr/bin/env bash
# Bring the KAINE OpenAI-compatible model server (the language organ) up in one
# invocation. Thin wrapper over the testable Python core in
# kaine.setup.model_server — binary discovery, launch-command construction,
# supervision-mode selection (systemd --user where available, else a supervised
# background process), and health-gating on the served alias all live there.
# Mirrors scripts/redis-bootstrap.sh / scripts/qdrant-bootstrap.sh ergonomics.
#
# - Locates the hardware-appropriate server binary (Unsloth Studio's llama-server
#   on NVIDIA, the unsloth-core build on AMD; honors KAINE_MODEL_SERVER_BIN).
# - Launches it against the downloaded organ GGUF under the EXACT
#   [lingua].model_id alias, with chain-of-thought suppressed, on the configured
#   port; supervises it; health-gates on /v1/models listing the alias.
# - NEVER silently installs the multi-GB server toolchain: if the binary is
#   absent it prints install guidance and exits non-zero.
#
# Idempotent: re-running when the alias is already served reports up and exits 0.
#
#   bash scripts/model-server-bootstrap.sh            # start (default)
#   bash scripts/model-server-bootstrap.sh start
#   bash scripts/model-server-bootstrap.sh status
#   bash scripts/model-server-bootstrap.sh stop

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

CMD="start"
while [[ $# -gt 0 ]]; do
  case "$1" in
    start|status|stop) CMD="$1"; shift ;;
    --help|-h) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Prefer the project venv's interpreter; fall back to python3 on PATH.
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

exec "$PY" -m kaine.setup.model_server "$CMD"
