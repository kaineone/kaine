# Branch/PR integration chunking — 2026-11-16

Docs only. No branches, commits, rebases, merges, pushes, or deletions were
performed while producing this file. Every integration chunk below is gated on
an explicit operator approval; nothing auto-runs. Chunk sizes are intentionally
kept small enough that a single pre-flight gate, worker first-pass review, and
Claude adversarial sign-off can cover the whole chunk.

Sources: `docs/records/branch-hygiene-audit-2026-11-16.md`,
`docs/records/CLEANUP-readiness.md`,
`docs/records/worktree-branches-merge-safety-2026-11-16.md`,
`docs/records/worktree-agent-triage-2026-11-16.md`,
`docs/records/branch-pr-sequence-2026-11-16.md`,
`docs/records/branch-cleanup-command-list-2026-11-16.md`,
`docs/records/branch-pr-execution-log-2026-11-16.md`.

## Chunk sizing rules

- One chunk = one bounded integration outcome, not "as many branches as fit".
- At most 3 branch updates per chunk; at most 1 high-risk (privacy,
  preservation, safety-critical, encryption, persistence) change per chunk.
- A single large branch (`build/latent-privacy`, `build/operator-speech`,
  `build/developmental-stimulus`) must be split into feature-sized PRs before
  integration rather than merged as one rebased tree.
- Each chunk ends with a green local gate (`tools/maintainer/preflight-gate.sh`
  under `safe-run.sh`), worker first-pass review (`review-pr.sh` with
  `WORKER_MODEL` set), Claude adversarial review, and sign-off before enqueue
  (`enqueue.sh` / `enqueue-when-green.sh`).
- High-risk chunks require a **second Claude adversarial review** before sign-off.
- One worktree only (`git worktree list`) for the whole run; no carrying
  uncommitted edits across chunks. Protect the three modified tracked files
  and move untracked records/run artifacts out of the tree before starting.

## Operator approval gates

Gates are numbered and must be cleared one at a time, in order. Clearing a
later gate implies the earlier chunk's gate, sign-off, and enqueue are complete.

| Gate | Clears | Requires |
|---|---|---|
| G0 | Tree protection + base refresh | `git status`, stash/commit decision, `git fetch --all --prune`, single-worktree confirmation |
| G1 | Chunk C1 (active PR updates) | Operator approval per branch update |
| G2 | Chunk C2 (reopened/closed-PR decision) | Explicit choice: reopen vs. new PR, no force-push |
| G3 | Chunk C3 (new `build/*` PRs) | Gate G3a..G3d, one per branch |
| G4 | Chunk C4 (high-risk worktree fragments) | Second Claude review for each |
| G5 | Chunk C5 (medium-risk fragments) | One approval per fragment |
| G6 | Chunk C6 (low-risk/no-op verification) | Verification-first; abandon only with approval |
| G7 | Chunk C7 (cleanup of 38 merged/squash-equivalent branches) | Re-run merge-base and cherry checks first |

## Integration chunks

### Chunk C0 — Protect tree and refresh base (gate G0)

- Protect modified tracked files (`config/kaine.toml`,
  `openspec/changes/individuation-rebuild/validation/test_lora.py`,
  `openspec/changes/module-ignition-study/tasks.md` where present).
- Move untracked records/run artifacts out of the tree.
- `git fetch --all --prune`; record the new `origin/main` SHA (do not trust
  the stale snapshot `01b24026` / `871ffe0a`).
- Confirm a single worktree.
- No rebase or checkout until G0 is cleared.
- Success: clean, protected tree + current base SHA recorded.
- Rollback: restore stashed files; abort the run. No repository state changed.

### Chunk C1 — Active unmerged PRs, 1–4 commits (gate G1)

Branches: `feat/audition-encoder-bakeoff` (PR #818, current branch),
`feat/voice-dev-stage2-alignment` (PR #815).

- Order: A1, then A2. Rebase each onto current `origin/main`.
- Confirm unrelated tracked edits from C0 are not staged.
- Read and address all review comments on each PR before enqueue.
- Worker first-pass review + Claude adversarial sign-off for each.
- Split trigger: if A2's rebase touches more than 3 subsystems or more than
  400 changed lines beyond its original 4 commits, split it into feature-grouped
  PRs before continuing.
- Success: both PRs updated/rebased, gates green, enqueued or clearly blocked
  with a written reason.
- Rollback: keep the original PRs open; abandon the rebase and restore the
  pre-chunk branch tips.

### Chunk C2 — Closed/conflicting PR decision (gate G2)

Branch: `feat/residency-12.10-lockstep-docs` (PR #790 CLOSED, 20 ahead /
27 behind, 16 novel).

- Decide explicitly whether to reopen #790 or create a new PR. No force-push.
- If reopening: new branch + PR, diffed against #790's final state for
  continuity.
- Split the 16 novel commits into documentation-area PRs if review size exceeds
  a manageable pass; retain this branch as the integration source.
- Worker first-pass + adversarial sign-off; enqueue only after green.
- Success: one approved PR path selected and recorded in the execution log.
- Rollback: leave #790 closed and untouched; discard the rebase, keep commits on
  a new branch.

### Chunk C3 — New `build/*` PRs, largest last (gate G3)

Branches: `build/perceptual-sources` (8 ahead), `build/developmental-stimulus`
(16 ahead), `build/operator-speech` (56 ahead), `build/latent-privacy` (59 ahead).

- Order: G3a sources, G3b stimulus, G3d operator speech, G3c latent privacy
  last because it is privacy/security-sensitive and needs a second Claude
  review.
- Push each with `-u`, then open one PR per chunked feature group.
- Rebase before push. Verify SPDX headers and module-name rules for changed files.
- Split `build/developmental-stimulus`, `build/operator-speech`, and
  `build/latent-privacy` into feature-grouped PRs; do not merge them as
  megabranches.
- `build/latent-privacy`: second Claude review required; verify redaction,
  heard-speech handling, and privacy invariants end to end.
- Success: each branch has at least one manageable PR with a clear scope and
  green gate.
- Rollback: keep the integration branch intact; abandon individual split PRs
  without touching the source branch.

### Chunk C4 — High-risk worktree fragments (gate G4, second review)

Fragments: `worktree-agent-a78898068c157f9f3` (workspace feedback preservation),
`worktree-agent-aebab2da16da02c47` (language episodic recall + redaction).

- H1 preservation: resolve add/add conflicts on
  `kaine/modules/feedback.py`, `kaine/workspace/feedback.py`, and
  `tests/test_feedback_preservation.py`; high merge-base concurrency on
  `cycle/__main__.py`.
- H2 privacy/redaction: focus on the code files; the test file is already on
  main; verify heard speech is dropped from logged prompts end to end.
- Second Claude adversarial review required for both. Targeted tests plus the
  normal gate.
- Success: preservation and redaction behavior verified with reviewed tests.
- Rollback: targeted merge only; if redaction cannot be verified, abort the
  chunk and leave the fragment unmerged.

### Chunk C5 — Medium-risk worktree fragments (gate G5)

- M1. `worktree-agent-a94898e7da9879172` (audition SpeakerEmbedder): add
  speaker-embedder coverage before merge; provenance/model-path safety.
- M2. `worktree-agent-a8354776b02549459` (stimulus-control per-pass): strip
  the 3 identical-of-4 source files and test; carry only the
  `programme_end.py` hunk.
- M3. `worktree-agent-a9c82ff748647723d` (social-cognition face
  expression/emotion): rebase reduces to `social_cognition/module.py`; verify
  behavior and template tests.
- Success: each fragment either lands with focused tests or is explicitly
  deferred with a reason.
- Rollback: per-fragment revert; do not bundle unrelated fragments into one PR.

### Chunk C6 — Low-risk/no-op verification (gate G6)

- L1. `worktree-agent-ab24b71e74d8ffe49` (speech models tests): verify the
  commit adds nothing beyond main; recommend abandon with operator approval
  only if truly empty.
- L2. `worktree-agent-ae7ab9df23db422f8` (social cognition preservation
  tests): same verify-then-abandon-with-approval handling.
- No automatic branch deletion in this chunk.
- Success: verified status recorded for each fragment; no deletion performed.
- Rollback: none beyond not merging; verification work can be discarded.

### Chunk C7 — Integration cleanup (gate G7, after C1–C6)

Source: `branch-cleanup-command-list-2026-11-16.md` (38 merged/squash-equivalent
local branches).

- Re-run `git merge-base --is-ancestor` and `git cherry origin/main <branch>`
  for all 38 names after the integration work above; squash equivalence can be
  invalidated by new main commits.
- Confirm no open PR or worktree depends on them.
- Optional and recommended before deletion: create lightweight tags
  `archive/<branch>-2026-11-16` on each candidate.
- Switch HEAD off any branch being deleted (use `main` or a feature branch).
- Execute only the 38 documented `git branch -D` commands, one at a time or in
  the documented blocks, after explicit approval.
- Count successes; expected local branch count decreases by 38
  (`before - 38`).
- Deferred candidates (pre-rebase snapshots such as
  `build/developmental-stimulus-pre-rebase`; experimental/research branches)
  stay out of scope until referenced work closes.
- Success: 38 verified deletions or a documented failure/reconciliation list.
- Rollback: tags preserve deleted branch tips for recovery; no force operations.

## Cross-chunk discipline

- Local gate required before every enqueue:
  `tools/maintainer/preflight-gate.sh <worktree>` (ruff, lint-imports,
  red-team, fast suite under `safe-run.sh` with the 16 GB ceiling).
- Worker first-pass review always uses `WORKER_MODEL` when set; otherwise the
  harness defaults to Kimi and must be noted as such.
- Claude performs the adversarial review and sign-off; high-risk chunks get a
  second Claude review.
- `git fetch --all --prune` before each rebase; use the fetched `origin/main`
  SHA, not a cached one.
- No force push. If a rebase needs new history, open a new branch + PR and
  leave the original intact.
- No branch deletion without the specific approval captured in G7.
- Progress is recorded only in
  `docs/records/branch-pr-execution-log-2026-11-16.md`.

## Bottom line

This file defines the integration sequence only. It chunks the active branches
into seven gated stages (C0–C7), keeps each merge to a manageable size, keeps
destructive cleanup in a separately approved final stage, and leaves every git
operation for explicit operator execution.
