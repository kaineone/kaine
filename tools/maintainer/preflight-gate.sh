#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# preflight-gate.sh WORKTREE — the local pre-flight gate. Run it on every branch
# before every push; CI should then never go red inside the merge queue. Mirrors
# the PR workflows: ruff, import-linter, the red-team suite, the fast suite in
# parallel, and the slow lane when the branch touches a slow path.
set -uo pipefail
WT=$(realpath "${1:?usage: preflight-gate.sh WORKTREE}")
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The main checkout (first worktree) holds the shared virtualenv.
MAIN="$(git -C "$HERE" worktree list --porcelain | awk 'NR==1 {print $2}')"
VENV="${KAINE_VENV:-$MAIN/.venv}"
PY="$VENV/bin/python"
BIN="$VENV/bin"
cd "$WT" || exit 1
fail=0
step() { echo "== $1"; shift; if "$@"; then echo "   ok"; else echo "   FAILED"; fail=1; fi; }
step "ruff" "$BIN/ruff" check kaine tests plugins
step "lint-imports" env PYTHONPATH="$WT" "$BIN/lint-imports"
step "redteam" env PYTHONPATH="$WT" "$PY" -m pytest -q -p no:cacheprovider tests/test_evaluation_redteam.py \
  tests/test_fork_merge_snapshot.py tests/test_praxis_audit_log.py tests/test_praxis_effectors.py tests/test_nexus_privacy.py
step "redteam-http" env PYTHONPATH="$WT" "$PY" -m pytest -q -p no:cacheprovider tests/test_nexus_routers.py -k "traversal or merge_form"
# GATE_WORKERS (default 8) sets the parallelism. CUDA_VISIBLE_DEVICES="": the
# suite runs CPU-only, as CI does, and never holds GPU memory.
step "suite (fast, -n 8)" env CUDA_VISIBLE_DEVICES="" PYTHONPATH="$WT" "$HERE/safe-run.sh" "$PY" -m pytest -q -p no:cacheprovider \
  -n "${GATE_WORKERS:-8}" --dist loadfile -m "not slow" -o faulthandler_timeout=600
git fetch -q origin main
re=$(grep -v '^#' .github/slow-test-paths.txt | grep -v '^[[:space:]]*$')
if [ -n "$re" ] && git diff --name-only origin/main...HEAD | grep -E -q -f <(printf '%s\n' "$re"); then
  step "slow lane (touched)" env CUDA_VISIBLE_DEVICES="" PYTHONPATH="$WT" "$HERE/safe-run.sh" "$PY" -m pytest -q -p no:cacheprovider -m slow -o faulthandler_timeout=600
fi
[ "$fail" = 0 ] && echo "PREFLIGHT GREEN" || echo "PREFLIGHT RED"
exit $fail
