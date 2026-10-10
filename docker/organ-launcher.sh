#!/bin/sh
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
#
# Organ container entrypoint: starts llama-server and hot-swaps the per-entity
# GGUF LoRA when the generation file changes. The LoRA is loaded with scale 0
# (--lora-scaled ...:0) so the base organ serves requests that do not specify a
# lora field; per-request lora fields still apply the scaled adapter. All
# command-line arguments are forwarded to llama-server.

set -eu

ADAPTERS_DIR="${KAINE_ORGAN_ADAPTERS_DIR:-/organ-adapters}"
POLL_S="${KAINE_ORGAN_POLL_S:-5}"
# Seconds llama-server gets to exit after SIGTERM before it is killed. Some
# builds ignore SIGTERM while idle-asleep, so a bounded stop is required.
STOP_TIMEOUT_S="${KAINE_ORGAN_STOP_TIMEOUT_S:-30}"

# Resolve the llama-server binary. The default is the image's /app/llama-server
# when present, otherwise whatever is on PATH.
LLAMA_SERVER="${KAINE_LLAMA_SERVER:-}"
if [ -z "$LLAMA_SERVER" ]; then
    if [ -x /app/llama-server ]; then
        LLAMA_SERVER=/app/llama-server
    else
        LLAMA_SERVER=llama-server
    fi
fi

log() {
    echo "organ-launcher: $*" >&2
}

# Stop the running llama-server: SIGTERM, then SIGKILL after STOP_TIMEOUT_S.
stop_server() {
    [ -n "$pid" ] || return 0
    kill -TERM "$pid" 2>/dev/null || true
    waited=0
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$STOP_TIMEOUT_S" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        log "llama-server did not exit within ${STOP_TIMEOUT_S}s of SIGTERM; killing it"
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || status=$?
}

# Read the generation counter; missing/absent means "no adapter".
read_gen() {
    cat "$ADAPTERS_DIR/generation" 2>/dev/null || echo "0"
}

# Build the extra llama-server arguments from active.json, validating the
# SHA-256 of the referenced GGUF. Uses sed/grep only; the container may lack jq.
build_extra_args() {
    if [ ! -f "$ADAPTERS_DIR/active.json" ]; then
        log "not loading adapter: no active.json manifest"
        return
    fi

    file=$(sed -n 's/.*"file":[[:space:]]*"\([^"]*\)".*/\1/p' "$ADAPTERS_DIR/active.json")
    sha=$(sed -n 's/.*"sha256":[[:space:]]*"\([0-9a-fA-F]\{64\}\)".*/\1/p' "$ADAPTERS_DIR/active.json")

    case "$file" in
        */*|*..*)
            # A shell case '*' also matches '/': refuse any name that could
            # leave the adapters directory.
            log "not loading adapter: invalid active.json file name '$file'"
            ;;
        active-[0-9]*.gguf)
            path="$ADAPTERS_DIR/$file"
            if [ -f "$path" ] && printf '%s  %s\n' "$sha" "$path" | sha256sum -c - >/dev/null 2>&1; then
                # --no-cache-prompt: a request must never reuse KV that another
                # request computed with a different adapter setting (measured at
                # build 9976: base requests after an adapted one were contaminated).
                printf '%s\n' "--lora-scaled $path:0 --no-cache-prompt"
            else
                log "not loading adapter: SHA mismatch or missing file for $file"
            fi
            ;;
        *)
            log "not loading adapter: invalid active.json file name '$file'"
            ;;
    esac
}

pid=""
status=0

cleanup() {
    stop_server
    exit "${status:-0}"
}
trap 'cleanup' TERM INT

while true; do
    generation=$(read_gen)
    extra=$(build_extra_args || true)

    # Unquoted $extra is intentional: it contains two distinct arguments when set.
    # shellcheck disable=SC2086
    "$LLAMA_SERVER" "$@" $extra &
    pid=$!
    last_generation=$generation

    while true; do
        sleep "$POLL_S"

        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" || status=$?
            exit "$status"
        fi

        current_generation=$(read_gen)
        if [ "$current_generation" != "$last_generation" ]; then
            log "generation changed ($last_generation -> $current_generation), restarting llama-server"
            stop_server
            break
        fi
    done
done
