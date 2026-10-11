#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# safe-run.sh CMD... — run a heavy command (test suites, builds) without being
# able to freeze the desktop: a transient systemd user scope caps its memory at
# SAFE_RUN_MEM (default 16G) with swap disabled, so a runaway is OOM-killed at the
# cap instead of pushing the whole machine into swap, and it runs at low CPU and
# I/O priority so interactive work stays responsive.
set -euo pipefail
MEM="${SAFE_RUN_MEM:-16G}"
exec systemd-run --user --scope --quiet \
  -p MemoryMax="$MEM" -p MemorySwapMax=0 -p CPUWeight=20 -p IOWeight=20 \
  nice -n 10 ionice -c 3 "$@"
