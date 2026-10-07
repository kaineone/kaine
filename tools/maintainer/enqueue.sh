#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# enqueue.sh PR — add a signed-off PR to main's merge queue (never --admin).
# gh 2.45's `pr merge` tries auto-merge, which this repo does not allow, so this
# calls the merge-queue GraphQL mutation directly.
set -euo pipefail
PR=${1:?usage: enqueue.sh PR}
ID=$(gh pr view "$PR" --repo kaineone/kaine --json id -q .id)
gh api graphql -f query='mutation($id:ID!){enqueuePullRequest(input:{pullRequestId:$id}){mergeQueueEntry{position state}}}' -f id="$ID" \
  --jq '"#'"$PR"' queued: position \(.data.enqueuePullRequest.mergeQueueEntry.position) (\(.data.enqueuePullRequest.mergeQueueEntry.state))"'
