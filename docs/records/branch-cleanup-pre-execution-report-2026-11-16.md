# Branch cleanup — pre-execution dry-run report (2026-11-16)

Docs only. No commands were executed while producing this file, and this file
contains **no deletion commands**. It records the dry-run verification script,
the recorded baseline ref counts, and the expected post-execution ref counts
for the 38 target-group branches in
`docs/records/branch-cleanup-command-list-2026-11-16.md`. Deletion commands
live only in that command-list file and require `BRANCH_CLEANUP_APPROVED=1`.

Sources: `docs/records/branch-cleanup-command-list-2026-11-16.md`,
`docs/records/branch-hygiene-audit-2026-11-16.md`,
`docs/records/branch-pr-chunking-2026-11-16.md`.

## Scope (no deletes)

- Target set: 38 local branches only (10 `merged`, 28 `squash`-equivalent).
- No remote tracking refs are included; no branches are deleted by this file.
- No `git branch -D`, `git push`, rebase, merge, tag push, or prune is executed
  by any command listed here. Every command below is read-only verification.

## Recorded baseline ref counts (measured, pre-execution)

Command used to measure:

```sh
printf 'local branches (refs/heads): %s\n' "$(git for-each-ref --format='%(refname)' refs/heads | wc -l)"
printf 'remote branches (refs/remotes): %s\n' "$(git for-each-ref --format='%(refname)' refs/remotes | wc -l)"
printf 'tags (refs/tags): %s\n' "$(git for-each-ref --format='%(refname)' refs/tags | wc -l)"
printf 'all refs: %s\n' "$(git for-each-ref | wc -l)"
printf 'current branch: %s\n' "$(git branch --show-current)"
```

Recorded values:

| Ref namespace | Count |
|---|---:|
| `refs/heads` (local branches) | 191 |
| `refs/remotes` (remote tracking) | 45 |
| `refs/tags` | 0 |
| all refs | 237 |
| current branch | `feat/audition-encoder-bakeoff` (not in target set) |

## Target set verification (dry-run, no deletions)

Verified baseline classification of all 38 names against `origin/main`:

- `merged` (0 commits ahead): 10
- `squash`-equivalent (`git cherry` shows 0 `+` lines): 28
- `NOT_SAFE`: 0
- `MISSING`: 0

Expected classification equation: `10 + 28 = 38`, `0` not-safe.

## Exact dry-run commands (copy-paste safe for operators)

Operator must run from `/var/home/erik/Projects/kaineone/kaine` on a clean,
protected tree. All commands are read-only. Use `set -euo pipefail` so any
mismatch aborts before any later (separate) deletion step.

### 1. Confirm current checkout is not a deletion target

```sh
set -euo pipefail
git branch --show-current
test "$(git branch --show-current)" != "$(git branch --show-current | grep -E '^(worktree-agent-|feat/(custody-escrow|episodic-recall-precision-check|residency-|social-cognition-config|vision-unload|voice-dev-validation))$' || true)" || \
  { echo 'ABORT: current branch is in the target set'; exit 1; }
echo 'OK: current branch is not a target.'
```

### 2. Record baseline ref counts before any action

```sh
set -euo pipefail
printf 'refs/heads BEFORE: %s\n' "$(git for-each-ref --format='%(refname)' refs/heads | wc -l)"
printf 'refs/tags BEFORE: %s\n' "$(git for-each-ref --format='%(refname)' refs/tags | wc -l)"
printf 'all refs BEFORE: %s\n' "$(git for-each-ref | wc -l)"
```

### 3. Confirm every target branch still exists

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
missing=0
for b in "${branches[@]}"; do
  if ! git rev-parse --verify --quiet "$b" >/dev/null; then
    printf 'MISSING  %s\n' "$b"; missing=1
  fi
done
[ "$missing" = "0" ] && echo 'OK: all 38 target branches exist.'
```

### 4. Dry-run safety classification (read-only; no deletions)

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
bad=0; merged=0; squash=0
for b in "${branches[@]}"; do
  ahead=$(git rev-list --count "$base..$b")
  cherry_plus=$(git cherry "$base" "$b" | grep -c '^+' || true)
  if [ "$ahead" = "0" ]; then
    verdict=merged; merged=$((merged + 1))
  elif [ "$cherry_plus" = "0" ]; then
    verdict=squash-equivalent; squash=$((squash + 1))
  else
    verdict=NOT_SAFE; bad=1
  fi
  printf '%-58s ahead=%-4s cherry+= %-2s %s\n' "$b" "$ahead" "$cherry_plus" "$verdict"
done
printf 'summary: merged=%s squash=%s (total %s)\n' "$merged" "$squash" "$((merged + squash))"
if [ "$bad" = "1" ] || [ "$((merged + squash))" != "38" ]; then
  echo 'DRY-RUN FAILED: one or more branches are not safe to delete.'
  exit 1
fi
echo 'DRY-RUN PASSED: all 38 branches are merged or squash-equivalent.'
```

### 5. Optional archive-tag existence/count check (read-only)

```sh
set -euo pipefail
printf 'archive tags currently present: %s\n' \
  "$(git tag --list 'archive/2026-11-16/*' | wc -l)"
# Expected before tag creation: 0
```

## Expected ref counts

### Scenario A — deletions only (no archive tags created)

| Ref namespace | Before | After | Delta |
|---|---:|---:|---:|
| `refs/heads` | 191 | 153 | -38 |
| `refs/remotes` | 45 | 45 | 0 |
| `refs/tags` | 0 | 0 | 0 |
| all refs | 237 | 199 | -38 |

### Scenario B — deletions plus the optional 38 archive tags

| Ref namespace | Before | After | Delta |
|---|---:|---:|---:|
| `refs/heads` | 191 | 153 | -38 |
| `refs/remotes` | 45 | 45 | 0 |
| `refs/tags` | 0 | 38 | +38 |
| all refs | 237 | 237 | 0 |

In both scenarios the only ref-level mutation is `-38` local branches; remote
tracking refs and `HEAD` are untouched, and no remote state is modified.

## Operator suitability notes

- Suitable operators: POSIX `sh`-compatible runners with `git`, `grep`, and
  `wc`; commands use `set -euo pipefail` and avoid any mutation.
- Commands are idempotent at the verification level: re-running them does not
  change repository state.
- Any `NOT_SAFE` or `MISSING` result blocks progression to the deletion
  approval gate; reconcile before retrying.
- This report intentionally excludes the deletion commands. Those commands and
  the `BRANCH_CLEANUP_APPROVED=1` gate are in
  `docs/records/branch-cleanup-command-list-2026-11-16.md` and must not be
  run from this file.
- Rollback for this verification phase is trivial: because no mutation occurs,
  no rollback is required. If a future deletion run needs reversal, the
  optional `archive/2026-11-16/*` tags preserve deleted tips.

## Sign-off (verification only)

- [ ] Dry-run commands executed as listed above.
- [ ] Results match: 10 merged + 28 squash-equivalent, 0 not-safe, 0 missing.
- [ ] Baseline ref counts recorded (191 heads / 45 remotes / 0 tags / 237 all).
- [ ] Expected post-execution counts acknowledged.
- Verified by: ____________________  UTC: ____________________
