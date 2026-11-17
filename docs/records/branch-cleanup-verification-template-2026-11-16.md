# Branch cleanup — verification template (remote branch objects touched)

Date: 2026-11-16. Docs only. No deletions, no source edits, no commands
were executed while producing this file. It is a template for the operator to
record the verification state of the remote branch objects that intersect the
38 target-group branches in
`docs/records/branch-cleanup-command-list-2026-11-16.md`. The deletion
command list remains local-ref only; no remote deletion is instructed here.

Sources:
- `docs/records/branch-cleanup-command-list-2026-11-16.md`
- `docs/records/branch-cleanup-pre-execution-report-2026-11-16.md`
- `docs/records/branch-hygiene-audit-2026-11-16.md`
- `docs/records/CLEANUP-readiness.md`

## 1. Scope and safety

- Target set: 38 local branches (10 `merged`, 28 `squash`-equivalent).
- Local baseline recorded in pre-execution report:
  - `refs/heads`: 191
  - `refs/remotes`: 45
  - `refs/tags`: 0
  - all refs: 237
  - current branch: `feat/audition-encoder-bakeoff` (not in target set)
- This template records only remote branch objects that are present among the
  38 target names at verification time. It does not widen the scope to other
  remote branches and does not add remote deletion commands.

## 2. Remote branch objects touched

Measured against `refs/remotes/origin/*` for each of the 38 target branch names.

Expected count: **1** remote ref present. All other 37 target names are local-only
at the time of this template and have no `origin/<name>` object.

| # | Remote ref | Object SHA | Classification vs `origin/main` | Ahead | Behind | Cherry `+` | Notes |
|---|---|---:|---|---:|---:|---:|---|
| 1 | `origin/feat/residency-7.2-auto-rung-selection` | `fe081c36fd768ca33e776062153c901ee3fdb4e8` | squash-equivalent | 2 | 172 (approx; verify at execution) | 0 | Remote object mirrors a target local branch. Confirm at execution with `git rev-list --count origin/main..origin/feat/residency-7.2-auto-rung-selection` and `git cherry origin/main origin/feat/residency-7.2-auto-rung-selection`. |

Read-only discovery command (copy-paste safe):

```sh
set -euo pipefail
targets=(
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
printf '%-60s %s\n' 'remote ref' 'status'
for b in "${targets[@]}"; do
  ref="origin/$b"
  if git rev-parse --verify --quiet "$ref" >/dev/null 2>&1; then
    sha=$(git rev-parse --short "$ref")
    ahead=$(git rev-list --count origin/main.."$ref" 2>/dev/null || echo '?')
    cherry=$(git cherry origin/main "$ref" 2>/dev/null | grep -c '^+' || true)
    printf 'TOUCHED  %-54s sha=%-8s ahead=%-4s cherry+= %s\n' "$ref" "$sha" "$ahead" "$cherry"
  fi
done
printf 'remote refs touched: %s (expected 1)\n' "$(for b in "${targets[@]}"; do git rev-parse --verify --quiet "origin/$b" >/dev/null 2>&1 && printf '%s\n' "$b"; done | wc -l)"
```

## 3. Expected target counts

| Scope | Count | Notes |
|---|---:|---|
| Local target branches to delete | 38 | 10 merged + 28 squash-equivalent (`branch-cleanup-command-list-2026-11-16.md`). |
| Remote refs touched by target names | 1 | `origin/feat/residency-7.2-auto-rung-selection` only. |
| Remote refs not present | 37 | No `origin/<name>` exists; local-only deletion does not touch them. |
| Local refs after successful local-only deletion | 153 | Baseline `refs/heads` 191 - 38 (if all 38 local deletions succeed). |
| Remote refs after successful local-only deletion | 45 | Unchanged by local deletion; if operator also deletes the one touched remote ref with explicit approval, expected 44. |
| Tags after archive tag creation | 38 | One `archive/2026-11-16/<slug>` annotated tag per target branch. |

## 4. Operator result blocks

Fill in during execution. Use UTC timestamps. No deletions should be performed
unless `BRANCH_CLEANUP_APPROVED=1` is set and all earlier checklist items in
`docs/records/branch-cleanup-command-list-2026-11-16.md` are checked.

### 4.1 Pre-execution verification

- Date/time (UTC): ____________________
- Repository path: ____________________
- `git branch --show-current`: ____________________
- `origin/main` SHA: ____________________
- `refs/heads` BEFORE: ____________________
- `refs/remotes` BEFORE: ____________________
- `refs/tags` BEFORE: ____________________
- Working tree status (clean / exceptions noted): ____________________
- Remote refs touched BEFORE (expected 1): ____________________
- Mismatches vs expected target set (0 expected): ____________________

### 4.2 Dry-run result

- Command run: `docs/records/branch-cleanup-command-list-2026-11-16.md` dry-run
  block.
- Result (PASS / FAIL): ____________________
- Branches classified `merged`: ____________________ (expected 10)
- Branches classified `squash-equivalent`: ____________________ (expected 28)
- `NOT_SAFE` count (expected 0): ____________________
- `MISSING` count (expected 0): ____________________
- Notes: ____________________

### 4.3 Remote branch object result

- Touched remote ref verified before deletion (expected 1): ____________________
- `origin/feat/residency-7.2-auto-rung-selection` object SHA verified:
  ____________________ (expected `fe081c36...`)
- Classification verified (`squash-equivalent`): ____________________
- Operator decision for touched remote ref:
  - [ ] Leave remote ref untouched (default; local-only pass)
  - [ ] Delete remote ref in the same approved pass
- If deleted, remote deletion command used (record exactly): ____________________
- Remote refs AFTER: ____________________ (expected 45 if untouched, 44 if
  deleted)

### 4.4 Archive tag result

- Archive tags created BEFORE deletion: ____________________ (expected 38)
- Missing tags (expected 0): ____________________
- Tags pushed to origin: [ ] no  / [ ] yes; if yes, count: ____________________

### 4.5 Deletion result

- Approval token set (`BRANCH_CLEANUP_APPROVED=1`): [ ] yes  / [ ] no
- `git branch -D` successes: ____________________ (expected 38)
- Failures (expected 0): ____________________
- Failed branch names (if any): ____________________
- Retry/abort decision: ____________________

### 4.6 Post-execution verification

- `refs/heads` AFTER: ____________________ (expected 153 for local-only pass)
- `refs/remotes` AFTER: ____________________ (expected 45 or 44)
- `refs/tags` AFTER: ____________________ (expected 38)
- all refs AFTER: ____________________ (expected 236 for local-only pass with
  archive tags: 237 - 38 + 38)
- Remaining target branches expected (0): ____________________
- Re-run dry-run on any remaining target (PASS / FAIL): ____________________
- Discrepancies: ____________________

### 4.7 Operator sign-off

```
Verified by: ____________________
Date/time (UTC): ____________________
Scope covered: local target set (38) + remote touched set (1)
Result: [ ] PASS  /  [ ] FAIL
Approval token at execution: BRANCH_CLEANUP_APPROVED=1
Notes: ____________________
```

## 5. Rollback notes

- Local branch deletion removes branch refs only; commits remain reachable
  via archive tags (`archive/2026-11-16/<sanitized-branch-name>`).
- To restore a local branch:
  `git branch <original-name> archive/2026-11-16/<slug>`.
- Remote branch deletion is more impactful and is not part of the default
  local-only cleanup. If a remote touched ref is deleted and later needed,
  restore it from the local or archive-tag SHA and push with operator
  approval.
- Remove archive tags only after deletion verification is complete and no
  recovery is expected.
- No source files or working-tree contents should be modified by this
  verification template.