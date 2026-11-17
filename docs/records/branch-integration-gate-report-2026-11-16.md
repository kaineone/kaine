# Branch integration gate report (2026-11-16)

Docs only. No branches, commits, merges, deletions, or other repository state were
modified while producing this file. This is a gating report: it declares the
approved integration order and the conditions that must hold before any branch
from the prior triage may be merged.

Sources:
- `docs/records/worktree-agent-triage-2026-11-16.md`
- `docs/records/worktree-branches-merge-safety-2026-11-16.md`
- `docs/records/branch-pr-sequence-2026-11-16.md`
- `docs/records/branch-pr-execution-log-2026-11-16.md`
- `docs/records/openspec-triage-board-2026-11-16-2.md`
- `docs/records/CLEANUP-readiness.md`

## Scope and inventory

Prior triage identified 17 `worktree-agent-*` branches:

- 10 already merged into `main` (0 commits ahead) -> classified
  `abandon-with-approval`, **not deleted**.
- 7 unmerged merge candidates (1-2 commits ahead) -> all touch `kaine/` source
  code or tests and require the integration path below.

The broader branch cleanup inventory (do not conflate with this integration gate)
contains 38 local cleanup candidates; those are governed by gate `G7` and are
out of scope here except through the no-delete safety gate in section 6.

Unmerged candidate inventory:

| Candidate | Commit(s) | Risk | Branch-only files |
|---|---:|---|---|
| `worktree-agent-a78898068c157f9f3` | 1 | High (preservation) | 4 code + 1 new test |
| `worktree-agent-aebab2da16da02c47` | 2 | High (privacy/redaction) | 2 code + 1 test (already on main) |
| `worktree-agent-a94898e7da9879172` | 1 | Medium/high (model provisioning) | 4 code, no tests |
| `worktree-agent-a8354776b02549459` | 1 | Medium (effector) | 4 code + 1 test; 3/4 already on main |
| `worktree-agent-a9c82ff748647723d` | 1 | Medium (social cognition) | 3 code + 1 test; 3/4 already on main |
| `worktree-agent-ab24b71e74d8ffe49` | 1 | Low (tests only) | 1 test; file identical to main |
| `worktree-agent-ae7ab9df23db422f8` | 1 | Low (tests only) | 1 new test; file identical to main |

Dry-run merge status from prior triage:
- `a788`: 3 conflicts.
- `a835`: 1 conflict.
- `a948`: 2 conflicts.
- `a9c8`: 1 conflict.
- `ab24`: clean auto-merge, likely already landed.
- `ae7a`: clean auto-merge, likely already landed.
- `aeba`: 1 conflict.

## Merge-order sequence

Order is risk/dependency-first, not commit-date-first. Each item is gated; no
item starts before its listed gate is cleared.

### Gate G0 - Protect working tree and refresh base (required first)

1. Record `git status --short --branch`.
2. Protect the currently modified tracked files
   (`config/kaine.toml`,
   `openspec/changes/individuation-rebuild/validation/test_lora.py`,
   `openspec/changes/module-ignition-study/tasks.md`) and move untracked
   records/run artifacts out of the tree.
3. `git fetch --all --prune`; record the refreshed `origin/main` SHA.
4. Confirm a single worktree (`git worktree list`).

No rebase or checkout may occur until G0 is cleared.

### Phase 2A - High-risk integration (second Claude review required)

**I1. `worktree-agent-a78898068c157f9f3` - workspace feedback preservation**
- Gate: `G4a`.
- Required before merge:
  - Rebase onto refreshed `origin/main`.
  - Resolve conflicts on `kaine/modules/feedback.py`,
    `kaine/workspace/feedback.py`, and the add/add conflict on
    `tests/test_feedback_preservation.py`.
  - Account for main concurrency: 5 commits on `cycle/__main__.py`,
    3 on `lifecycle/preservation.py`, 2 each on the two feedback modules.
  - Run preflight gate: `tools/maintainer/preflight-gate.sh <worktree>`.
  - Worker first-pass review with `WORKER_MODEL` set via `review-pr.sh`.
  - Claude adversarial review + sign-off.
  - **Second Claude adversarial review** (preservation; high-risk).
  - Enqueue only via `enqueue.sh` / `enqueue-when-green.sh` after green.

**I2. `worktree-agent-aebab2da16da02c47` - language episodic recall + redaction**
- Gate: `G4b`.
- Required before merge:
  - Rebase onto refreshed `origin/main`.
  - Reconcile `context.py` (auto-merges against main's commit `97e7c4e9`)
    and resolve the `module.py` conflict against main's later lockstep changes
    (`6e030c9a`).
  - Verify end-to-end that heard speech is dropped from the logged prompt.
  - Treat the privacy/redaction path as high-risk (second Claude review).
  - Enqueue only after gate green and both reviews pass.

### Phase 2B - Medium-risk integration

**I3. `worktree-agent-a94898e7da9879172` - audition SpeakerEmbedder**
- Gate: `G5a`.
- Dependency: main already added a speaker embedding extraction pipeline
  (`7a9794c3`); integrate rather than overwrite.
- Required before merge:
  - Rebase; resolve `speaker_embedder.py` add/add and
    `speech_manifest.py` content conflict; `setup/speech_models.py` is already
    identical to main.
  - **Add speaker-embedder test coverage; merge is blocked without it.**
  - Model-path/manifest changes are safety-critical provenance: worker
    first-pass + Claude adversarial sign-off before enqueue.

**I4. `worktree-agent-a8354776b02549459` - stimulus-control per-pass**
- Gate: `G5b`.
- Dependency: likely partial duplicate of the already-merged 5.4
  stimulus-control change (`26ead231`); only `programme_end.py` differs from
  main.
- Required before merge:
  - Strip the 3 source files and test already identical to main.
  - Carry only the `programme_end.py` hunk.
  - Rebase; worker review; Claude sign-off; enqueue after green.

**I5. `worktree-agent-a9c82ff748647723d` - social-cognition face expression/emotion**
- Gate: `G5c`.
- Dependency: `social_cognition/module.py` is the only differing hunk; all
  other paths already on main (`f5b0cc66`).
- Required before merge:
  - Rebase to reduce to the remaining `module.py` hunk.
  - Verify social-cognition behavior and `test_faithful_templates.py`.
  - Enqueue after green.

### Phase 2C - Low-risk verification-first

**I6. `worktree-agent-ab24b71e74d8ffe49` - speech models tests**
- Gate: `G6a` (verification only first).
- Dependency: entire test file already identical to main (`4641ae40`).
- Required before any decision:
  - Confirm the branch commit adds nothing beyond main (diff/cherry).
  - If truly empty, recommend abandon with operator approval.
  - No deletion without explicit delete approval.

**I7. `worktree-agent-ae7ab9df23db422f8` - social cognition preservation tests**
- Gate: `G6b` (verification only first).
- Dependency: entire test file already identical to main (`f5b0cc66`).
- Required before any decision:
  - Confirm no unique content.
  - If truly empty, recommend abandon with operator approval.
  - No deletion without explicit delete approval.

### Completion boundary for Phase 2

No Phase 3 cleanup, branch deletion, or abandonment may proceed until I1-I7
have either landed on `main` with PR evidence or been explicitly abandoned by
the operator and recorded in `branch-pr-execution-log-2026-11-16.md`.

## Required approvals

Approval gates are numbered and must be explicitly cleared. Implicit or assumed
approval is not valid. Names below match the existing gate plan.

| Gate | Scope | Type | Approver |
|---|---|---|---|
| G0 | Protect working tree and refresh base | Required first | Operator |
| G4a | Feedback preservation integration | Required | Operator + Claude adversarial sign-off |
| G4b | Language redaction integration | Required | Operator + Claude adversarial sign-off |
| G5a | SpeakerEmbedder + new tests | Required | Operator + Claude sign-off |
| G5b | Stimulus-control reduced merge | Required | Operator + Claude sign-off |
| G5c | Social-cognition reduced merge | Required | Operator + Claude sign-off |
| G6a/G6b | No-op branch verification | Required | Operator |
| Second Claude review | High-risk: preservation and privacy/redaction | Required for I1, I2 | Claude (distinct adversarial pass) |
| Worker first-pass review | All candidates with source/test changes | Required | `review-pr.sh` with `WORKER_MODEL` set |
| Enqueue | `enqueue.sh` / `enqueue-when-green.sh` only after local gate green | Required | Maintainer after sign-off |
| G7 | Cleanup/deletion of already-merged or empty branches | Separate explicit approval | Operator |

Standing requirements for every candidate:
- Home-branch protection of unrelated tracked changes (G0).
- `git fetch --all --prune`; use refreshed `origin/main`, not stale snapshots.
- No force push; if rebase needs new history, open a new branch and leave the
  original intact.
- Preflight gate green via `tools/maintainer/preflight-gate.sh <worktree>`.
- Higher-risk classes (preservation, privacy/redaction, provenance safety)
  require the second Claude review named above.

## Dependencies from prior triage

### Worktree triage dependencies

- Classification dependency: the 7 unmerged branches and 10 `abandon-with-approval`
  branches come from `worktree-agent-triage-2026-11-16.md`; those counts must be
  re-verified before any deletion after Phases 1-2 change `main`.
- Safety dependency: `worktree-branches-merge-safety-2026-11-16.md` supplies
  merge-base SHAs, conflict lists, redundancy findings, and main-concurrency
  notes used in the I1-I7 requirements above.
- Reduction dependency: `a835`, `a9c8`, and `ab24`/`ae7a` may be reducible to
  small or empty hunks because most of their changes are already on `main`.
- Test dependency: `a948` is blocked until speaker-embedder coverage exists;
  `a788` carries a new preservation test that must be reconciled after its
  add/add conflict.
- Privacy dependency: `aeba` must satisfy redaction behavior against main's
  lockstep changes before merge, not just merge cleanly.

### OpenSpec / validation dependencies

From `openspec-triage-board-2026-11-16-2.md` (27 active changes; 0 fully
complete at snapshot time):

- OpenSpec changes referenced or implicated by the branch work must remain at
  their documented gate state; do not mark them complete solely because a branch
  merges:
  - `welfare-indicator-response` still requires maintenance-sleep length
    recording at validation boot (task 6.5) despite being near-complete.
  - `stimulus-control-act` still has a supervised validation boot and
    development-run join task open.
  - `individuation-rebuild` is blocked on the operator bundle-export decision
    and real-organ smoke test even at 60/67.
- Action-path changes (`act-intent-derivation`, `active-vision`,
  `embodiment-motor-contingency`, `goal-directed-grasping`,
  `planning-act-proposals`, `world-model-action-outcomes`) remain design-only
  with unsatisfied start conditions and must not be unblocked by branch
  integration alone.
- Ablation-gated changes (`affect-active-inference`,
  `episodic-memory-retrieval-energy`, `sleep-replay`) depend on completion of
  the workspace-mediation ablation and are not cleared by branch integration.
- Archive criteria from the triage board require all tasks checked, strict
  validation, tests green, PR evidence, records, doc/paper updates, and no open
  operator-only tasks. No change currently meets all eight criteria; branch
  integration does not by itself satisfy them.

### Pipeline dependency

Per project policy, every candidate follows:
OpenSpec proposal where applicable -> feature branch -> PR -> worker first-pass
review -> Claude adversarial review and sign-off -> merge to main -> enqueue.
High-risk items additionally require the second Claude review.

## No-delete safety gate

This gate exists to prevent deletion of branches that may still carry unique
work or be referenced by in-flight plans. It is mandatory and separate from
every integration gate above.

Rules:
1. **No branch deletion is performed by this report or any document produced
   alongside it.**
2. The 10 `worktree-agent-*` branches already merged into `main` remain present
   (classified `abandon-with-approval`) until operator approval is explicitly
   granted; classification is not permission.
3. The 2 likely no-op branches (`ab24`, `ae7a`) are verify-first; they may not
   be abandoned or deleted until:
   - their branch commits are compared against `origin/main` after a fresh fetch,
   - the result is recorded in `branch-pr-execution-log-2026-11-16.md`, and
   - explicit abandonment/deletion approval is recorded.
4. Before any delete (including G7's 38 cleanup candidates), all of the
   following must hold:
   - Re-run `git merge-base --is-ancestor` and `git cherry origin/main <branch>`
     for every candidate name after any rebase or merge activity; prior
     squash-equivalence findings can be invalidated by new main commits.
   - Confirm no open PRs, worktrees, or in-flight tasks depend on the branch.
   - Resolve whether any `origin/<branch>` ref exists; handle it in the same
     approval pass or leave it untouched.
   - Create recoverability tags `archive/<branch>-2026-11-16` before deletion
     (recommended).
   - Switch HEAD off any branch being deleted.
   - Execute `git branch -D` exactly as documented, one at a time or in the
     documented blocks; reconcile every unexpected failure before continuing.
5. Deferred delete candidates (pre-rebase snapshots such as
   `build/developmental-stimulus-pre-rebase`, experimental/research branches)
   remain out of scope until their referenced work closes.
6. If disk usage on the working drive reaches 95% or higher, stop all
   build/container/deletion activity and report before resuming.
7. Any proposed deletion that cannot satisfy items 1-4 is blocked; the branch
   stays intact.

## Exit conditions (integration gate closes only when all hold)

- G0 and every applicable I1-I7 gate are recorded as cleared in the execution
  log.
- High-risk candidates I1 and I2 have worker first-pass review, Claude
  adversarial sign-off, and the second Claude review recorded.
- `a948` has passing speaker-embedder coverage.
- `ab24` and `ae7a` have verification recorded and either landed or been
  explicitly abandoned.
- All changed paths pass the local preflight gate.
- No branch was deleted outside the no-delete safety gate and explicit G7
  approval.
- The execution log records the final `origin/main` SHA, HEAD SHA, and the
  disposition of every candidate.

## Status

Prepared: 2026-11-16. Docs only. No repository mutations performed. Awaiting
explicit operator clearances (G0 first) before any integration work begins.