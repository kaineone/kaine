# PR and branch-cleanup readiness — 2026-11-16

Docs only. No commands were executed. Current checkout is
`feat/audition-encoder-bakeoff` at `871ffe0a`; `origin/main` is
`01b24026` (chore: voice-dev tasks done, #817). Several tracked files in the
working tree are modified and many artifact/record files are untracked, so a
branch switch or pull has to account for them first.

## Seven active unmerged merge candidates

Source: `docs/records/branch-hygiene-audit-2026-11-16.md`
(recommendations, merge candidates). Branch-by-branch state:

| Branch | PR | Ahead / Behind / Novel | Upstream | Rebase? |
|---|---|---:|---|---|
| `feat/audition-encoder-bakeoff` | #818 OPEN | 1 / 4 / 1 | origin (current) | yes, 4 behind |
| `feat/voice-dev-stage2-alignment` | #815 OPEN | 4 / 6 / 4 | origin | yes, 6 behind |
| `feat/residency-12.10-lockstep-docs` | #790 CLOSED | 20 / 27 / 16 | origin | yes; prior PR closed (conflicting) |
| `build/latent-privacy` | none | 59 / 172 / 59 | none | yes; rebase or split PR |
| `build/operator-speech` | none | 56 / 172 / 56 | none | yes; rebase or split PR |
| `build/perceptual-sources` | none | 8 / 171 / 8 | origin/main only | yes; needs `-u` push first |
| `build/developmental-stimulus` | none | 16 / 171 / 16 | none | yes; rebase or split PR |

"Novel" is the `git cherry origin/main branch` `+` count.

### Prerequisites before opening or updating a PR (any of the seven)

1. **Protect the current working tree.** The checkout has modified
   `config/kaine.toml`, `openspec/changes/individuation-rebuild/validation/test_lora.py`,
   and `openspec/changes/module-ignition-study/tasks.md`, plus many untracked
   records/run artifacts. Commit the intended ones to
   `feat/audition-encoder-bakeoff`, stash the rest, or move untracked records
   out of the tree before checking out another branch. Do not let
   `git checkout` carry unrelated edits into five other branches.
2. **Confirm the branch in use.** `git status --short --branch`; there is only
   one worktree (`git worktree list`), so switches are in-place.
3. **Fetch and refresh base.** `git fetch --all --prune` (already run for this
   snapshot); use the current `origin/main` SHA, not the stale
   `01b24026` from the earlier fetch if it moved.
4. **Rebase each branch onto current `origin/main`.** All seven are behind by
   4-172 commits; resolve conflicts per branch. For `build/*` branches with
   50+ commits, consider splitting into feature-grouped PRs rather than one
   rebased megabrag, but keep the existing branch as the integration source.
5. **Run the local gate.** `tools/maintainer/preflight-gate.sh <worktree>`.
   Required bar per project CI gates: ruff, lint-imports, red-team suite,
   fast suite (CPU-only via `safe-run.sh`), and the slow lane only if paths in
   `.github/slow-test-paths.txt` changed. Keep pytest suite memory under the
   ~16 GB ceiling and use `safe-run.sh` (16 GB/run, cgroup).
6. **Branch-specific checks.**
   - `feat/audition-encoder-bakeoff` and `feat/voice-dev-stage2-alignment`:
     update existing open PRs (#818, #815) after rebase; check review comments
     first; ensure staged edits do not include the unrelated tracked changes
     currently in the worktree.
   - `feat/residency-12.10-lockstep-docs`: prior PR #790 is CLOSED with
     conflicts; open a new PR (or reopen with a clean rebase) rather than
     force-pushing; retain this branch's lockstep v1 docs that main lacks.
   - `build/latent-privacy`, `build/operator-speech`, `build/perceptual-sources`,
     `build/developmental-stimulus`: no PR exists. Push with `-u` (four have no
     upstream; `build/perceptual-sources` is not on origin at all), then open one
     PR per branch. Verify SPDX headers and module-name rules for changed files.
7. **Publish.** Use `gh pr create` (or `gh pr edit` only where it works; repo
   note says `gh pr edit` is broken on gh 2.45 — use `gh api PATCH` instead).
   Follow commit identity `Kaine.One <kaine.one@tuta.com>`, no force push; if a
   rebase needs new history, open a new branch/PR rather than rewriting.
8. **Adversarial review.** Worker first-pass review (`review-pr.sh`, with
   `WORKER_MODEL` set; default is Kimi otherwise), then Claude adversarial
   review and sign-off before merge. Enqueue via `enqueue.sh` /
   `enqueue-when-green.sh` only after the local gate is green.

## Cleanup list (38 target-group delete candidates)

Source: `docs/records/branch-cleanup-command-list-2026-11-16.md`
(10 merged `worktree-agent-*`, 28 squash-equivalent `feat/*` + one
`worktree-agent-*`).

Prerequisites before deleting any of them:

1. **Operator approval.** Both the audit and cleanup list explicitly require it;
   nothing here should be deleted automatically.
2. **Refresh the classification after any main update.** Re-run
   `git merge-base --is-ancestor` and `git cherry origin/main <branch>` for all
   38 names after rebase/merge activity; the `+ 0` squash-equivalence can be
   invalidated by new main commits.
3. **Confirm no in-flight work depends on them.** Check open PRs and worktrees:
   currently only one worktree and 7 open PRs; the listed branches are not among
   them, but verify at execution time.
4. **No remote tracking refs.** The list is local-only; if `origin/<branch>`
   exists for any name, handle the remote ref in the same approval pass or leave
   it.
5. **Archive before delete (recommended).** Create lightweight tags or noted refs
   (e.g. `archive/<branch>-2026-11-16`) for recoverability even though all are
   merged/patch-equivalent; deletion is irreversible on the local reflog only.
6. **Switch off target branches first.** Ensure nothing is checked out on a
   branch being deleted; use main or a feature branch as HEAD.
7. **Run commands exactly as listed**, using `git branch -D` (already force) one
   at a time or in the documented blocks; verify the count (38 successes) and
   reconcile any failure before continuing.
8. **Deferred delete candidates are out of scope here:** pre-rebase snapshots
   such as `build/developmental-stimulus-pre-rebase` should stay until the
   superseding branch lands, and the experimental/research branches stay until
   referenced work is closed.

## Not in scope

No repository policy files, CI configuration, or branch state were modified.
This file is the only edit.}