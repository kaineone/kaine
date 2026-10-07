#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# gpu-lock.sh CMD... — run CMD holding the host-wide exclusive GPU lock.
# Every GPU user on the host goes through it: training (K1-Jev SFT, voice
# alignment), encoder bake-offs, the individuation calibration, the validation
# boot and any local model. Cloud worker calls do NOT need it.
# GPU_LOCK_PRIORITY=1 marks a job the integrator has approved to go next: while
# a priority job waits, ordinary jobs that win the lock hand it straight back.
# (Replace this file only by atomic rename; waiting jobs keep reading the old inode.)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# One lock per clone, shared by every worktree: it lives in the common git dir.
T="${KAINE_GPU_LOCK_DIR:-$(cd "$HERE" && git rev-parse --path-format=absolute --git-common-dir)}"
LOCK=$T/gpu.lock
exec 9>"$LOCK"
announced=0
if [ -n "${GPU_LOCK_PRIORITY:-}" ]; then
  mark="$T/gpu.priority.$$"
  : > "$mark"
  trap 'rm -f "$mark"' EXIT
  flock 9
  rm -f "$mark"
else
  while :; do
    if ! flock -n 9; then
      if [ "$announced" = 0 ]; then
        echo "gpu-lock: waiting for the GPU (held by: $(cat "$LOCK.owner" 2>/dev/null || echo unknown))" >&2
        announced=1
      fi
      flock 9
    fi
    # A live priority waiter goes first: hand the lock back and wait again.
    waiting=0
    for m in "$T"/gpu.priority.*; do
      [ -e "$m" ] || continue
      if kill -0 "${m##*.}" 2>/dev/null; then waiting=1; else rm -f "$m"; fi
    done
    [ "$waiting" = 0 ] && break
    flock -u 9
    sleep 3
  done
fi
echo "$(date -Is) pid=$$ ${GPU_LOCK_OWNER:-?}: $*" > "$LOCK.owner"
# A job gets the GPUs empty: unload whatever Ollama still holds in VRAM from the
# last holder, unless the job itself is a local Ollama call (GPU_LOCK_KEEP_OLLAMA=1).
if [ -z "${GPU_LOCK_KEEP_OLLAMA:-}" ]; then
  for m in $(ollama ps 2>/dev/null | awk 'NR>1 {print $1}'); do
    curl -s localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null
  done
  sleep 2
fi
"$@"
