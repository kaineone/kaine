# Branch/PR sequence — 2026-11-16

Docs only. No branches, commits, merges, or deletions were performed while
producing this file. Conservative plan: every item below is gated on explicit
operator approval; nothing auto-runs.

Sources: `docs/records/worktree-branches-merge-safety-2026-11-16.md`,
`docs/records/branch-cleanup-command-list-2026-11-16.md`,
`docs/records/CLEANUP-readiness.md`, `docs/records/worktree-agent-triage-2026-11-16.md`,
and project CLAUDE.md pipeline rules (OpenSpec/feature branch -> PR -> worker
first-pass review -> Claude adversarial sign-off -> merge).

## Ground rules (apply to every branch)

- **Operator approval gates** are numbered G0..G7 below; each gate must be
  explicitly cleared before proceeding. No implicit or assumed approval.
- One worktree only (`git worktree list`), in-place switches. Before any
  checkout: stash or commit the three modified tracked files
  (`config/kaine.toml`, `openspec/changes/individuation-rebuild/validation/test_lora.py`,
  `openspec/changes/module-ignition-study/tasks.md`) plus the untracked
  records/run artifacts. Do not carry edits across branches.
- `git fetch --all --prune` before each rebase; use the fetched `origin/main`
  SHA, not the stale snapshot (`01b24026` / `871ffe0a`).
- **No force push.** If a rebase needs new history, open a new branch + PR and
  leave the original intact. No branch deletion without a specific approval.
- Before merge enqueue: local gate green via
  `tools/maintainer/preflight-gate.sh <worktree>` (ruff, lint-imports,
  red-team, fast suite under `safe-run.sh` 16 GB cgroup; slow lane only if paths
  in `.github/slow-test-paths.txt` changed). Keep pytest under the ~16 GB ceiling.
- Worker first-pass review: `WORKER_MODEL` set (default is Kimi otherwise)
  via `review-pr.sh`; then Claude adversarial review + sign-off; enqueue via
  `enqueue.sh` / `enqueue-when-green.sh` only after the gate is green.
- High-risk changes (preservation, privacy/redaction, safety-critical
  provenance) require a **second Claude adversarial review** before sign-off.

---

## Gate G0 — Protect working tree and refresh base

**Approval required before starting.**

1. `git status --short --branch` on current checkout.
2. Protect the modified tracked files (commit to `feat/audition-encoder-bakeoff`
   the intended ones; stash the rest) and move untracked records/run artifacts
   out of the tree.
3. `git fetch --all --prune`; record the new `origin/main` SHA.
4. Confirm single worktree.

No rebase or checkout until G0 is cleared.

---

## Phase 1 — Seven active unmerged branches (`feat/` / `build/`)

Source of list: `CLEANUP-readiness.md` (PR/upstream/rebase-required table).
Order below is risk/dependency-ordered, not commit-date ordered.

### Group A — branches with open PRs (update existing PRs)

**A1. `feat/audition-encoder-bakeoff` (PR #818, 1 ahead / 4 behind, novel 1)**
- Gate G1a (approve update, not new branch).
- Rebase onto current `origin/main`; expect small conflicts on audition paths.
- Ensure staged edits do not include the unrelated tracked changes currently
  in the worktree (from G0).
- Worker first-pass review of PR #818; Claude adversarial review; sign-off;
  enqueue.

**A2. `feat/voice-dev-stage2-alignment` (PR #815, 4 ahead / 6 behind, novel 4)**
- Gate G1b.
- Rebase; check review comments on #815 first.
- Worker first-pass + Claude sign-off; enqueue.

### Group B — closed/conflicting PR (reopen or new PR)

**B1. `feat/residency-12.10-lockstep-docs` (PR #790 CLOSED, 20 ahead / 27 behind, 16 novel)**
- Gate G2 (approve reopening vs. new PR; do not force-push #790).
- Rebase onto `origin/main`; retain the lockstep v1 docs that main lacks.
- Open a new PR (`gh pr create`) rather than force-pushing into the closed
  #790; diff against the closed PR's final state for continuity.
- Worker first-pass + Claude sign-off; enqueue.

### Group C — `build/*` (no PR; push with `-u`, then one PR each)

**C1. `build/perceptual-sources` (8 ahead / 171 behind, novel 8; needs `-u` push first)**
- Gate G3a.
- Rebase first (smaller delta); push `-u`; open PR; verify SPDX headers and
  module-name rules for changed files.
- Worker first-pass + Claude sign-off; enqueue.

**C2. `build/developmental-stimulus` (16 ahead / 171 behind, novel 16)**
- Gate G3b.
- Rebase or split into feature-grouped PRs; keep this branch as integration
  source either way.
- Verify SPDX headers/module-name rules; worker first-pass + adversarial sign-off;
  enqueue.

**C3. `build/latent-privacy` (59 ahead / 172 behind, novel 59) — privacy/security**
- Gate G3c; **second Claude review required** (privacy-sensitive).
- Strongly consider splitting into feature-grouped PRs rather than one rebased
  megabragh. Keep this branch as integration source.
- Rebase, resolve, run gate; worker first-pass + Claude adversarial sign-off
  (+ second review) before enqueue.

**C4. `build/operator-speech` (56 ahead / 172 behind, novel 56)**
- Gate G3d.
- Rebase or split; keep integration branch. Worker first-pass + adversarial
  sign-off; enqueue.

---

## Phase 2 — Seven `worktree-agent-*` merge candidates

Source of list: `worktree-branches-merge-safety-2026-11-16.md`. Each is 1-2
commits ahead of its merge base with substantial main concurrency; standard
pipeline applies. Prioritize high-risk ones first per that report.

### High risk (manual rebase + conflict resolution + second Claude review)

**H1. `worktree-agent-a78898068c157f9f3` — workspace feedback preservation**
(`5db94662…`, 1 commit; feeds back into 5 files; 3 conflicts on merge)
- Gate G4a.
- Rebase onto `origin/main`; resolve conflicts on `kaine/modules/feedback.py`,
  `kaine/workspace/feedback.py`, `tests/test_feedback_preservation.py`
  (add/add). Merge-base concurrency high (5 main commits on
  `cycle/__main__.py`).
- Strip nothing (no files already on main). Add/verify the new tests.
- Worker first-pass + Claude adversarial sign-off + **second Claude review**
  (preservation). Enqueue only after green.

**H2. `worktree-agent-aebab2da16da02c47` — language episodic recall + redaction**
(`566c9bee…`, 2 commits; 1 conflict) — **privacy/redaction**
- Gate G4b; **second Claude review required**.
- Rebase; context auto-merges against main's #718; `module.py` conflicts with
  main's lockstep changes (#780). Redaction-sensitive path: verify heard
  speech dropped from logged prompt end-to-end.
- Test file already on main; focus on the two code files. Targeted merge + focused
  tests + privacy review. Enqueue after green.

### Medium risk

**M1. `worktree-agent-a94898e7da9879172` — audition SpeakerEmbedder**
(`73ede6c5…`, 1 commit; 2 conflicts; **no tests in commit**)
- Gate G5a.
- Rebase; `speaker_embedder.py` add/add with main's #738 integration;
  `speech_manifest.py` content; `model_paths.py` has 2 main commits.
- **Add speaker-embedder coverage before merge** (provenance/model-path safety).
- Worker first-pass + adversarial sign-off; enqueue after tests pass.

**M2. `worktree-agent-a8354776b02549459` — stimulus-control per-pass**
(`8062a310…`, 1 commit; 1 conflict)
- Gate G5b.
- Likely partial duplicate of already-merged 5.4 stimulus-control PR: 3 of 4
  source files + the test are identical to main. Strip those; carry only the
  `programme_end.py` hunk. Rebase; worker review; enqueue.

**M3. `worktree-agent-a9c82ff748647723d` — social-cognition face expression/emotion**
(`408024bb…`, 1 commit; 1 conflict)
- Gate G5c.
- Rebase reduces to `social_cognition/module.py` (all other files identical to
  main). Verify social cognition behavior and template tests; enqueue after
  green.

### Low risk — likely no-op candidates (verify, then decide)

**L1. `worktree-agent-ab24b71e74d8ffe49` — speech models tests**
(`6add69b8…`, 1 commit) — test file identical to main.
- Gate G6a (verification only first).
- Confirm the branch commit adds nothing beyond main (cherry/diff). If truly
  empty, recommend abandon with operator approval; **do not delete** without
  explicit delete approval (see cleanup list / G7).

**L2. `worktree-agent-ae7ab9df23db422f8` — social cognition preservation tests**
(`c44fdd41…`, 1 commit) — test file already on main.
- Gate G6b (verification only first).
- Same verify-then-abandon-with-approval handling; no automatic deletion.

---

## Phase 3 — Cleanup of already-merged / squash-equivalent branches (38 candidates)

Source: `branch-cleanup-command-list-2026-11-16.md`. This is **separate** from
the merge candidates above and runs only after G7.

**Gate G7 (operator approval, explicit, separate from all gates above)**
Prerequisites before executing any delete (from CLEANUP-readiness §cleanup):
1. Re-run `git merge-base --is-ancestor` and `git cherry origin/main <branch>`
   for all 38 names after any rebase/merge activity in Phases 1–2; the
   `+ 0` squash-equivalence can be invalidated by new main commits.
2. Confirm no in-flight work depends on them (open PRs / worktrees); currently
   only one worktree and the 7 active branches above are in flight — re-verify
   at execution time.
3. Local-only list; if any `origin/<branch>` exists, handle the remote ref in the
   same approval pass or leave it.
4. Archive before delete (recommended): create lightweight tags
   `archive/<branch>-2026-11-16` for recoverability.
5. Switch HEAD off any branch being deleted (use `main` or a feature branch).
6. Execute `git branch -D` exactly as listed, one at a time or in the
   documented blocks; verify 38 successes and reconcile any failure before
   continuing.
7. Deferred delete candidates (pre-rebase snapshots such as
   `build/developmental-stimulus-pre-rebase`, experimental/research branches)
   stay out of scope until referenced work closes.

No deletion of the 10 merged-empty `worktree-agent-*` happens before operator
approval even though they are classified `abandon-with-approval`.

---

## Summary execution order (conservative)

1. G0 — protect tree, fetch.
2. Phase 1 Group A (A1, A2) → Group B (B1) → Group C (C1..C4), each gated.
3. Phase 2 high-risk (H1, H2 with second review) → medium (M1..M3) → low (L1, L2 verify only).
4. Phase 3 cleanup (G7) only after all of the above land and operator signs off.

Throughout: no merging or deleting is performed by this document; this file is the
only artifact produced.
