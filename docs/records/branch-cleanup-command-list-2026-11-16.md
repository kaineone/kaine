# Branch cleanup command list — 2026-11-16

Docs only. No commands executed. Operator must review before running.

Source: `docs/records/branch-hygiene-audit-2026-11-16.md`. This list
contains only the 38 target-group (`build/`, `feat/`, `worktree-agent-`,
`fallback/`) branches classified `merged` (10) or `merged-equivalent` (squash,
28), already recommended for deletion on operator approval. Local branches
only; remote tracking refs are not included.

10 merged (`worktree-agent-*`):

```sh
git branch -D worktree-agent-a05b06b4cc0c0d491
git branch -D worktree-agent-a17c49e711e9ce22b
git branch -D worktree-agent-a3231a184d00caa48
git branch -D worktree-agent-a3923ff4b59d61aac
git branch -D worktree-agent-a3ef81feb8406aeef
git branch -D worktree-agent-a9557ea5c2a5ba93e
git branch -D worktree-agent-aaa077fed924c70a2
git branch -D worktree-agent-ad99d68b81d82780b
git branch -D worktree-agent-af4dde7b3fc8372b1
git branch -D worktree-agent-afa11a1b0b74d2ca1
```

28 merged-equivalent (squash):

```sh
git branch -D feat/custody-escrow
git branch -D feat/episodic-recall-precision-check
git branch -D feat/residency-10.3-residency-guide
git branch -D feat/residency-11.1-rung-quantization
git branch -D feat/residency-11.2-tier-profile-rungs
git branch -D feat/residency-12.1-stall-indicator
git branch -D feat/residency-12.10-lockstep-docs-v2
git branch -D feat/residency-12.2-event-tick-seq
git branch -D feat/residency-12.8-supervisor-barrier-v2
git branch -D feat/residency-12.9-lockstep-determinism-tests-v2
git branch -D feat/residency-2.2-probe-host-fit-surface
git branch -D feat/residency-3.4-weakref-tests
git branch -D feat/residency-5.2-supervisor-loading
git branch -D feat/residency-5.3-perception-queue
git branch -D feat/residency-5.4-auto-time-scale
git branch -D feat/residency-6.2-proxy-reconcile
git branch -D feat/residency-6.3-config-compat-test
git branch -D feat/residency-7.1-speech-rung-catalogue
git branch -D feat/residency-7.2-auto-rung-selection
git branch -D feat/residency-7.2-auto-rung-selection-v2
git branch -D feat/residency-7.4-voice-latency
git branch -D feat/residency-8.3-recommend-tier-residency
git branch -D feat/residency-config
git branch -D feat/residency-host-class-catalogue
git branch -D feat/social-cognition-config
git branch -D feat/vision-unload
git branch -D feat/voice-dev-validation
git branch -D worktree-agent-ab24b71e74d8ffe49
```

Total: 38 commands. Run only after operator approval and review.

---

## Pre-execution checklist (docs only)

- [ ] Working tree reviewed (`git status --short`); no uncommitted changes on branches in scope.
- [ ] Current branch is not in the delete list (`git branch --show-current`).
- [ ] Operator has read `docs/records/branch-hygiene-audit-2026-11-16.md` (delete candidates).
- [ ] All 38 target branch names still exist (validated by dry-run below).
- [ ] Any needed unpushed metadata on squash-equivalent branches has been captured.
- [ ] Source-of-truth backup exists (clone or origin) before destructive ops.
- [ ] No commands in this file have been executed yet; operator retains final say.

## Baseline branch count (record before starting)

```sh
set -euo pipefail
before=$(git branch --list | wc -l)
printf 'local branches BEFORE: %s\n' "$before"
git branch --show-current
git rev-parse --short origin/main 2>/dev/null || echo 'origin/main unavailable'
```

Record the `before` value; post-execution verification expects `before - 38`.

## Dry-run validation (no deletions)

Validates that every target is still `merged` (0 commits ahead) or
`squash-equivalent` (`git cherry` shows 0 `+` lines). Aborts on any mismatch.

```sh
set -euo pipefail
base=origin/main
branches=(
  worktree-agent-a05b06b4cc0c0d491
  worktree-agent-a17c49e711e9ce22b
  worktree-agent-a3231a184d00caa48
  worktree-agent-a3923ff4b59d61aac
  worktree-agent-a3ef81feb8406aeef
  worktree-agent-a9557ea5c2a5ba93e
  worktree-agent-aaa077fed924c70a2
  worktree-agent-ad99d68b81d82780b
  worktree-agent-af4dde7b3fc8372b1
  worktree-agent-afa11a1b0b74d2ca1
  feat/custody-escrow
  feat/episodic-recall-precision-check
  feat/residency-10.3-residency-guide
  feat/residency-11.1-rung-quantization
  feat/residency-11.2-tier-profile-rungs
  feat/residency-12.1-stall-indicator
  feat/residency-12.10-lockstep-docs-v2
  feat/residency-12.2-event-tick-seq
  feat/residency-12.8-supervisor-barrier-v2
  feat/residency-12.9-lockstep-determinism-tests-v2
  feat/residency-2.2-probe-host-fit-surface
  feat/residency-3.4-weakref-tests
  feat/residency-5.2-supervisor-loading
  feat/residency-5.3-perception-queue
  feat/residency-5.4-auto-time-scale
  feat/residency-6.2-proxy-reconcile
  feat/residency-6.3-config-compat-test
  feat/residency-7.1-speech-rung-catalogue
  feat/residency-7.2-auto-rung-selection
  feat/residency-7.2-auto-rung-selection-v2
  feat/residency-7.4-voice-latency
  feat/residency-8.3-recommend-tier-residency
  feat/residency-config
  feat/residency-host-class-catalogue
  feat/social-cognition-config
  feat/vision-unload
  feat/voice-dev-validation
  worktree-agent-ab24b71e74d8ffe49
)
bad=0
for b in "${branches[@]}"; do
  if ! git rev-parse --verify --quiet "$b" >/dev/null; then
    printf 'MISSING  %s\n' "$b"; bad=1; continue
  fi
  ahead=$(git rev-list --count "$base..$b")
  cherry_plus=$(git cherry "$base" "$b" | grep -c '^+' || true)
  if [ "$ahead" = "0" ]; then verdict=merged
  elif [ "$cherry_plus" = "0" ]; then verdict=squash-equivalent
  else verdict=NOT_SAFE; bad=1; fi
  printf '%-58s ahead=%-4s cherry+= %-2s %s\n' "$b" "$ahead" "$cherry_plus" "$verdict"
done
if [ "$bad" = "1" ]; then
  echo 'DRY-RUN FAILED: one or more branches are not safe to delete.'
  exit 1
fi
echo 'DRY-RUN PASSED: all 38 branches are merged or squash-equivalent.'
```

## Archive tags (create before deletion)

Creates an annotated archive tag per branch so the tip remains recoverable
after branch deletion. Run only after dry-run PASSES.

```sh
set -euo pipefail
branches=(
  worktree-agent-a05b06b4cc0c0d491
  worktree-agent-a17c49e711e9ce22b
  worktree-agent-a3231a184d00caa48
  worktree-agent-a3923ff4b59d61aac
  worktree-agent-a3ef81feb8406aeef
  worktree-agent-a9557ea5c2a5ba93e
  worktree-agent-aaa077fed924c70a2
  worktree-agent-ad99d68b81d82780b
  worktree-agent-af4dde7b3fc8372b1
  worktree-agent-afa11a1b0b74d2ca1
  feat/custody-escrow
  feat/episodic-recall-precision-check
  feat/residency-10.3-residency-guide
  feat/residency-11.1-rung-quantization
  feat/residency-11.2-tier-profile-rungs
  feat/residency-12.1-stall-indicator
  feat/residency-12.10-lockstep-docs-v2
  feat/residency-12.2-event-tick-seq
  feat/residency-12.8-supervisor-barrier-v2
  feat/residency-12.9-lockstep-determinism-tests-v2
  feat/residency-2.2-probe-host-fit-surface
  feat/residency-3.4-weakref-tests
  feat/residency-5.2-supervisor-loading
  feat/residency-5.3-perception-queue
  feat/residency-5.4-auto-time-scale
  feat/residency-6.2-proxy-reconcile
  feat/residency-6.3-config-compat-test
  feat/residency-7.1-speech-rung-catalogue
  feat/residency-7.2-auto-rung-selection
  feat/residency-7.2-auto-rung-selection-v2
  feat/residency-7.4-voice-latency
  feat/residency-8.3-recommend-tier-residency
  feat/residency-config
  feat/residency-host-class-catalogue
  feat/social-cognition-config
  feat/vision-unload
  feat/voice-dev-validation
  worktree-agent-ab24b71e74d8ffe49
)
for b in "${branches[@]}"; do
  slug=${b//\//__}
  tag="archive/2026-11-16/$slug"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    printf 'exists  %s\n' "$tag"
  else
    git tag -a "$tag" "$b" -m "Archive label for $b (branch-cleanup-2026-11-16 deletion candidate)"
    printf 'created %s -> %s\n' "$tag" "$(git rev-parse --short "$b")"
  fi
done
printf 'archive tags present: %s\n' "$(git tag --list 'archive/2026-11-16/*' | wc -l)"
```

Optional: push tags to origin after operator review (`git push origin --tags`).

## Operator approval marker

All boxes must be checked and signed before execution. No automated marker
replaces written operator approval.

- [ ] Audit reviewed (`branch-hygiene-audit-2026-11-16.md`)
- [ ] Dry-run PASSED on current repository state
- [ ] Archive tags created (and pushed if remote backup desired)
- [ ] Current branch verified not in delete list
- [ ] Working tree clean
- [ ] No unpushed metadata required from squash-equivalent branches

```
Approved by: ____________________
Date/time (UTC): ____________________
Scope: 38 target-group branches (10 merged + 28 squash-equivalent)
Approval token: BRANCH_CLEANUP_APPROVED=1
```

Execution gate (commands abort unless token is set):

```sh
[ "${BRANCH_CLEANUP_APPROVED:-0}" = "1" ] || { echo 'ABORT: BRANCH_CLEANUP_APPROVED not set'; exit 1; }
```

Set the token only after completing the sign-off above:

```sh
export BRANCH_CLEANUP_APPROVED=1
```

## Deletion execution (operator approved only)

Run the 38 `git branch -D ...` commands from the sections above only
after the gate passes. Re-run the dry-run immediately before execution.

## Post-execution branch count (verify -38)

```sh
set -euo pipefail
after=$(git branch --list | wc -l)
printf 'local branches AFTER: %s\n' "$after"
# Expected: baseline "before" minus 38. Compare manually to recorded value.
# Remaining target-group checks:
printf 'remaining merged/squash target branches: '
git branch --list 'worktree-agent-*' 'feat/residency-*' 'feat/custody-escrow' | wc -l
```

## Rollback / recovery notes

- Deletion removes branch refs only; commits remain reachable via archive
  tags (`archive/2026-11-16/<sanitized-branch-name>`).
- To restore a branch: `git branch <original-name> archive/2026-11-16/<slug>`.
- Remove an archive tag only after the deletion is verified and no longer
  needed: `git tag -d archive/2026-11-16/<slug>`.
- No source files or working-tree contents are modified by this document.