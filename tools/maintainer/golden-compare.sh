#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# golden-compare.sh [REF]: the same-machine check of module-core D7. It dumps the predictive golden traces at REF (default origin/main) and in the current tree, on this machine, and compares the recorded steps exactly. Run it in review of every PR that moves vision, audition or interoception code.

set -euo pipefail

VENV="${KAINE_VENV:-/run/media/erik/2TBm2Store/kaine/.venv}"
PY="$VENV/bin/python"
if [[ ! -x "$PY" ]]; then
    echo "error: python not found or not executable: $PY" >&2
    exit 2
fi

REF="${1:-origin/main}"
ROOT="$(git rev-parse --show-toplevel)"
OUT="$(mktemp -d)"
BASE_TREE="$OUT/base-tree"

git -C "$ROOT" worktree add --quiet --detach "$BASE_TREE" "$REF"
trap 'git -C "$ROOT" worktree remove --force "$BASE_TREE"; rm -rf "$OUT"' EXIT

export CUDA_VISIBLE_DEVICES=""
export PYTHONDONTWRITEBYTECODE=1

(cd "$BASE_TREE" && PYTHONPATH="$BASE_TREE" "$PY" -m tests.predictive_golden --dump "$OUT/base")
(cd "$ROOT" && PYTHONPATH="$ROOT" "$PY" -m tests.predictive_golden --dump "$OUT/head")
PYTHONPATH="$ROOT" "$PY" -m tests.golden_diff "$OUT/base" "$OUT/head"
