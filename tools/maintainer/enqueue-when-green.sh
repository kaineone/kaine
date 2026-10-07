#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# enqueue-when-green.sh PR... : enqueue each PR in order once its required checks all pass.
cd "$(dirname "$0")"
for pr in "$@"; do
  while :; do
    out=$(gh pr checks "$pr" --required 2>&1 | cut -f2)
    if grep -qx 'fail' <<<"$out"; then echo "#$pr has a FAILED required check; skipping"; break; fi
    if [ -n "$out" ] && ! grep -qvx 'pass' <<<"$out"; then ./enqueue.sh "$pr"; break; fi
    sleep 30
  done
done
echo done
