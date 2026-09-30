#!/bin/sh
# SPDX-License-Identifier: LicenseRef-CAL-0.2
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
                printf '%s\n' "--lora-scaled $path:0"
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
    if [ -n "$pid" ]; then
        kill -TERM "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || status=$?
    fi
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
            kill -TERM "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || status=$?
            break
        fi
    done
done
