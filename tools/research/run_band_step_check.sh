#!/bin/bash
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# Run the band-step check's runs in parallel, CPU only, inside one memory-capped scope:
#   systemd-run --user --scope -p MemoryMax=16G nice -n 19 tools/research/run_band_step_check.sh OUTDIR [JOBS] [PARALLEL]
# JOBS is a file of "SEED ARM SCHEDULE" lines. The default is the shipped stimulus,
# seeds 1-3, settled (5 h per stage) and under the release rule. The 2026-10-31 record
# used arms none, melody and melody_proxy (fixed:18000) and none, melody_proxy (rule).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="${PY:-$REPO/.venv/bin/python}"
[ -x "$PY" ] || PY=/var/home/erik/Projects/kaineone/kaine/.venv/bin/python
OUT="$1"
JOBS="${2:-}"
PAR="${3:-15}"
mkdir -p "$OUT"
if [ -z "$JOBS" ]; then
  JOBS="$OUT/jobs.txt"
  : > "$JOBS"
  for s in 1 2 3; do echo "$s shipped fixed:18000" >> "$JOBS"; echo "$s shipped rule" >> "$JOBS"; done
fi
export CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
run_one() {
  local seed="$1" arm="$2" sched="$3"
  local name="${seed}-${arm}-${sched/:/_}"
  "$PY" -W ignore "$HERE/band_step_check.py" --repo "$REPO" --seed "$seed" --arm "$arm" --schedule "$sched" \
    --out "$OUT/$name.npz" > "$OUT/$name.log" 2>&1
}
export -f run_one
export PY HERE REPO OUT
xargs -P "$PAR" -L 1 bash -c 'run_one "$@"' _ < "$JOBS"
echo ALLDONE
