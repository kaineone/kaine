#!/bin/bash
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
#
# Copy the abliterated organ's HuggingFace safetensors directory into the shared
# kaine-models volume at /models/Qwen3.5-4B-abliterated.
# Usage: provision_organ_base.sh SRC_DIR [--volume NAME] [--replace]

set -euo pipefail

SRC_DIR=""
VOLUME="${KAINE_MODELS_VOLUME:-kaine-models}"
IMAGE="${KAINE_IMAGE:-kaine:cuda}"
REPLACE=0

usage() {
    echo "Usage: $0 SRC_DIR [--volume NAME] [--replace]"
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --volume)
            VOLUME="$2"
            shift 2
            ;;
        --replace)
            REPLACE=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [[ -z "${SRC_DIR:-}" ]]; then
                SRC_DIR="$1"
                shift
            else
                echo "Unexpected argument: $1" >&2
                usage
            fi
            ;;
    esac
done

[[ -n "$SRC_DIR" ]] || usage
[[ -d "$SRC_DIR" ]] || { echo "Source directory not found: $SRC_DIR" >&2; exit 1; }
[[ -f "$SRC_DIR/config.json" ]] || { echo "Refusing: no config.json in $SRC_DIR" >&2; exit 1; }
[[ -n $(find "$SRC_DIR" -maxdepth 1 -name '*.safetensors' -print -quit) ]] || { echo "Refusing: no *.safetensors in $SRC_DIR" >&2; exit 1; }

DEST_NAME="Qwen3.5-4B-abliterated"

container_script=$(cat <<'SH'
set -e
SRC=/src
DEST=/models/$DEST_NAME

if [ -d "$DEST" ]; then
    src_sums=$(cd "$SRC" && find . -type f -exec sha256sum {} + | sort)
    dest_sums=$(cd "$DEST" && find . -type f -exec sha256sum {} + | sort)
    if [ "$src_sums" = "$dest_sums" ]; then
        echo "Already provisioned and identical; nothing to do."
        chown -R 10001:10001 "$DEST"
        exit 0
    fi
    if [ "$REPLACE" != "1" ]; then
        echo "Refusing: $DEST_NAME already exists with different content (use --replace)" >&2
        exit 1
    fi
fi

TMP=/models/.provision.$$
rm -rf "$TMP"
cp -aT "$SRC" "$TMP"
chown -R 10001:10001 "$TMP"

src_sums=$(cd "$SRC" && find . -type f -exec sha256sum {} + | sort)
dest_sums=$(cd "$TMP" && find . -type f -exec sha256sum {} + | sort)
if [ "$src_sums" != "$dest_sums" ]; then
    echo "Verification failed: copied hashes do not match source" >&2
    rm -rf "$TMP"
    exit 1
fi

mv -T "$TMP" "$DEST"
echo "Provisioned $DEST_NAME to /models/$DEST_NAME"
SH
)

docker run --rm \
    --user 0 \
    --entrypoint sh \
    -v "$SRC_DIR":/src:ro \
    -v "$VOLUME":/models \
    -e DEST_NAME="$DEST_NAME" \
    -e REPLACE="$REPLACE" \
    "$IMAGE" \
    -c "$container_script"
