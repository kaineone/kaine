#!/usr/bin/env bash
# KAINE service supervisor.  Reports and controls the Redis bus and Qdrant
# memory store, whether they are running as Docker containers or native
# user-level services.
#
# Usage:
#   scripts/services.sh status [redis|qdrant|all]
#   scripts/services.sh start  [redis|qdrant|all]
#   scripts/services.sh stop   [redis|qdrant|all] [--container]
#
# stop acts on this checkout's native services. A running container is shared
# by every checkout on the host, so stopping one needs --container.
#
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

source "$ROOT/scripts/lib/native-services.sh"

ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--container" ]]; then
    export KAINE_SERVICES_CONTAINER_OK=1
  else
    ARGS+=("$arg")
  fi
done
ACTION="${ARGS[0]:-status}"
TARGET="${ARGS[1]:-all}"

case "$ACTION" in
  status|start|stop) ;;
  *)
    echo "usage: scripts/services.sh status|start|stop [redis|qdrant|all]" >&2
    exit 2
    ;;
esac

case "$TARGET" in
  redis|qdrant|all) ;;
  *)
    echo "unknown service: $TARGET" >&2
    exit 2
    ;;
esac

SERVICES=()
if [[ "$TARGET" == "all" ]]; then
  SERVICES=(redis qdrant)
else
  SERVICES=("$TARGET")
fi

for svc in "${SERVICES[@]}"; do
  case "$ACTION" in
    status) service_status "$svc" ;;
    start)  service_start "$svc" ;;
    stop)   service_stop "$svc" ;;
  esac
done
