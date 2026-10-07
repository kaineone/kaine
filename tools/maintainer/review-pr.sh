#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# review-pr.sh PR OUT_DIR [CONTEXT_FILE...] — the worker's first-pass review.
# Builds a brief from review-template.md, the PR's description and its diff (plus
# any context files) and sends it to the worker model through worker.py.
# Output: OUT_DIR/response.txt with FINDING blocks, or NO FINDINGS. The lead
# verifies every finding; worker findings are input, never a verdict.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SLUG="${KAINE_REPO:-kaineone/kaine}"
PR=$1; OUT=$2; shift 2
mkdir -p "$OUT"
B="$OUT/review_brief.md"
{
  cat "$HERE/review-template.md"
  echo; echo "## The PR's description"
  gh pr view "$PR" --repo "$REPO_SLUG" --json title,body -q '"### " + .title + "\n\n" + .body'
  echo; echo '## The diff'; echo '```diff'
  gh pr diff "$PR" --repo "$REPO_SLUG"
  echo '```'
  for c in "$@"; do echo; echo "## Context: $(basename "$c")"; cat "$c"; done
} > "$B"
echo "brief: $(wc -c < "$B") chars"
if ! python3 "$HERE/worker.py" "$B" "$OUT" --think high --text; then
  echo "review-pr: the worker failed; read $OUT/thinking.txt" >&2
  exit 1
fi
echo "== worker findings"
cat "$OUT/response.txt"
