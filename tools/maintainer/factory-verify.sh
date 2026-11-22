#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# factory-verify.sh: the health check the Fabro factory runs on every workspace
# (`verify` in .fabro/workflows/feature/workflow.toml). It mirrors the local
# pre-flight gate without the parts that need the host: no PR scope guard (the
# run has no origin), no safe-run.sh (no user systemd bus in the sandbox).
# ruff, import-linter, the red-team tests and the fast suite on the CPU.
set -uo pipefail
VENV="${KAINE_VENV:-/run/media/erik/2TBm2Store/kaine/.venv}"
PY="$VENV/bin/python"
BIN="$VENV/bin"
[ -x "$PY" ] || { echo "factory-verify: no Python environment at $VENV"; exit 2; }
export PYTHONPATH="$PWD" CUDA_VISIBLE_DEVICES="" PYTHONDONTWRITEBYTECODE=1
fail=0
step() { echo "== $1"; shift; if "$@"; then echo "   ok"; else echo "   FAILED"; fail=1; fi; }
step "ruff" "$BIN/ruff" check --no-cache kaine tests plugins
step "lint-imports" "$BIN/lint-imports" --no-cache
step "redteam" "$PY" -m pytest -q -p no:cacheprovider tests/test_evaluation_redteam.py \
  tests/test_fork_merge_snapshot.py tests/test_effectors_audit_log.py tests/test_effectors.py tests/test_dashboard_privacy.py
# The stimulus-off golden digest is pinned to CI's CPU torch build; the shared
# environment has a CUDA build of torch whose float results differ, so it fails
# here on untouched main. CI still runs it on every PR and in the merge queue.
step "suite (fast)" "$PY" -m pytest -q -p no:cacheprovider -n "${VERIFY_WORKERS:-6}" --dist loadfile \
  -m "not slow" -o faulthandler_timeout=600 \
  --deselect tests/test_stimulus_disabled_identity.py::test_off_is_bit_identical_to_the_build_without_it
[ "$fail" = 0 ] && echo "VERIFY GREEN" || echo "VERIFY RED"
exit $fail
