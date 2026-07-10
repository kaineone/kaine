#!/bin/sh
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
#
# KAINE container entrypoint. Runs as the non-root `kaine` user. It establishes
# the owner-only (0700) posture on the mounted state/model volumes — the
# 0700/0600 protection the security work established must hold INSIDE the
# container too (design §7) — then execs the requested command (default
# `python -m kaine.cycle`, or `python -m kaine.nexus` for the web UI).
#
# It deliberately does NOT set any boot-gate variable. The cycle refuses to boot
# unless the operator explicitly exports KAINE_CYCLE_OPERATOR_PRESENT=1 (or the
# research safety net is verified). A bare run therefore never starts an entity.
set -eu

# Owner-only perms on the persistent volumes. chmod on a dir we own is safe as
# non-root; if the mount is not writable (read-only bind) we do not fail the
# whole boot — the app enforces its own at-rest guarantees. The entity-state
# volume mounts at /app/state (the app writes state CWD-relative under WORKDIR
# /app); /models is the shared read-mostly weights volume.
for d in /app/state /models; do
    if [ -d "$d" ]; then
        chmod 0700 "$d" 2>/dev/null || true
    fi
done

exec "$@"
