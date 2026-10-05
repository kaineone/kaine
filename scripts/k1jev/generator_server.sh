#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

set -euo pipefail

COMMAND="${1:-}"
shift || true

PORT=11450
DEVICE=0
IMAGE=""
GGUF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image)
            IMAGE="$2"
            shift 2
            ;;
        --gguf)
            GGUF="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --device)
            DEVICE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

if [[ "$COMMAND" == "start" ]]; then
    if [[ -z "$IMAGE" ]]; then
        echo "missing --image" >&2
        exit 2
    fi
    if [[ -z "$GGUF" ]]; then
        echo "missing --gguf" >&2
        exit 2
    fi

    if docker ps -q -f name="^kaine-k1jev-generator$" | grep -q .; then
        echo "container kaine-k1jev-generator already exists" >&2
        exit 2
    fi

    ENVF="${XDG_RUNTIME_DIR:-/tmp}/kaine-k1jev-generator.env"
    rm -f "$ENVF"
    TMPF=$(mktemp)
    chmod 600 "$TMPF"
    (
        umask 077
        {
            printf 'LLAMA_API_KEY='
            head -c 24 /dev/urandom | base64 | tr -d '/+='
        } > "$TMPF"
    )
    mv "$TMPF" "$ENVF"

    docker run -d --rm --name kaine-k1jev-generator \
        --gpus "device=$DEVICE" \
        --env-file "$ENVF" \
        -v "$(dirname "$GGUF"):/models:ro" \
        -p "127.0.0.1:$PORT:8080" \
        "$IMAGE" \
        --model "/models/$(basename "$GGUF")" \
        --alias qwen3.5-9b-generator \
        --ctx-size 16384 \
        --parallel 4 \
        --host 0.0.0.0 \
        --port 8080

    for _ in $(seq 1 180); do
        if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
            echo "generator ready on 127.0.0.1:$PORT; key in $ENVF (export K1JEV_GENERATOR_KEY from it)"
            exit 0
        fi
        sleep 1
    done

    echo "generator did not become healthy" >&2
    exit 1

elif [[ "$COMMAND" == "stop" ]]; then
    docker stop kaine-k1jev-generator >/dev/null 2>&1 || true
    rm -f "${XDG_RUNTIME_DIR:-/tmp}/kaine-k1jev-generator.env"
else
    echo "usage: generator_server.sh {start|stop} ..." >&2
    exit 2
fi
