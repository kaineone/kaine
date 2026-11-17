# Branch hygiene audit — 2026-11-16

Scope: local and remote branches. Targets audited: `build/*`, `feat/*`,
`worktree-agent-*`, `fallback/*`, plus experimental/non-standard branches.
Base for comparison: `origin/main` (`01b24026`, tip as of fetch).

Classification method:
- `merged` = branch tip is an ancestor of `origin/main`.
- `merged-equivalent (squash)` = not an ancestor, but `git cherry` reports
  zero patch-equivalent commits (`+` = 0); all work appears already applied.
- `active-unmerged` = has patch-equivalent (`+` > 0) commits not on `origin/main`.
- `likely duplicated / superseded` = active branch whose changes are represented
  by a successor, predecessor, or same-tip sibling (see notes).

No branches were deleted during this audit. Counts are unique branch names
(local or remote, de-duplicated).

## Summary counts (target groups: build/ feat/ worktree-agent- fallback/)

| Category | build/ | feat/ | worktree-agent- | fallback/ | Total |
|---|---:|---:|---:|---:|---:|
| Merged | 0 | 0 | 10 | 0 | 10 |
| Merged-equivalent (squash) | 0 | 27 | 1 | 0 | 28 |
| Active-unmerged | 7 | 47 | 6 | 2 | 62 |
| **Total unique** | **7** | **74** | **17** | **2** | **100** |

Project-wide (all prefixes), for context:
- Merged: 11
- Merged-equivalent (squash): 75
- Active-unmerged: 111
- Total non-main branches: 198

## Likely duplicated / superseded (target groups, active subset)

- `fallback/base-wcc` and `fallback/hr-workspace-continuous-competition-t1-1`
  have identical tip trees; the latter is a no-op ancestor edge of the former.
  Treat as one work unit.
- `build/developmental-stimulus-pre-rebase` (22 commits ahead, 21 novel patches)
  is an older pre-rebase snapshot next to `build/developmental-stimulus`
  (16 commits ahead). Likely superseded by the non-pre-rebase branch.
- `feat/emotion-fusion-config-tiers` vs `feat/emotion-fusion-config-tiers-7x`:
  sibling variants of the same config-tier work; the 7x variant is 1 commit
  ahead of its sibling. Reconcile before merging.
- Lockstep variants: `feat/residency-12.8/12.9/12.10/7.2` (v1) remain
  active-unmerged while their `-v2` siblings are squash-equivalent to main.
  The v1 branches carry 13–16 novel patches main does not have; decide whether
  to port them or discard in favour of the v2/squashed versions.
- `feat/entity-key-custody-envelope` is an ancestor stepping-stone of
  `feat/entity-key-custody-keyring`; keep a single canonical custody branch.
- Six `worktree-agent-*` branches carry 1–2 novel commits each (stimulus
  control, audition speaker embedder, social-cognition consumer/tests,
  heard-speech redaction, episodic recall). These look like worker fragments
  that may already be represented by later `feat/*` branches; verify before
  merging.

## Recommendations

### Merge candidates (active-unmerged, review then merge)

- `feat/audition-encoder-bakeoff` — current working branch; 1 novel commit,
  recent (4 commits behind main).
- `feat/voice-dev-stage2-alignment` — voice alignment work; 4 commits,
  6 behind main.
- `feat/residency-12.10-lockstep-docs` — substantial docs (20 ahead, 16 novel);
  27 behind main; rebase then merge.
- `build/latent-privacy`, `build/operator-speech`, `build/perceptual-sources`,
  `build/developmental-stimulus` — feature work, 6–59 commits ahead; rebase
  onto current main before review.
- Worktree-agent fragments above, if not already absorbed by `feat/*` peers.

### Keep for research / preservation

- Experimental non-target branches: `ablation-spec-5.5-5.6-disclosure`,
  `add-k1jev-distill-scripts`, `individuation-rebuild/disclosure-test`,
  `organ/*`, `research/band-step-check`, `social-cognition-identity`,
  `tools/crossmodal-decodability`, plus `spec/*` and `backup/*`.
- Pre-rebase snapshots (`build/developmental-stimulus-pre-rebase` and
  `backup/welfare-gates-pre-*`) should be retained until the superseding
  branches land, then can become delete candidates.

### Delete candidates (operator approval required)

- 10 merged `worktree-agent-*` branches (ancestor of main): safe to delete.
- 28 target-group squash-equivalent branches (27 feat + 1 worktree-agent):
  patch-equivalent to main; safe to delete after confirming branch names and
  that no unpushed metadata is needed.
- Project-wide, 86 branches total fall into merged/squash-equivalent buckets.
  Do **not** delete automatically; this audit requests approval.

## Representative sample (20 branches, `git log --oneline main..branch`)

| Branch | Ahead | Behind | Novel patches (`+`) | Category | Recommendation |
|---|---:|---:|---:|---|---|
| build/developmental-stimulus | 16 | 171 | 16 | active-unmerged | rebase, review |
| build/latent-privacy | 59 | 172 | 59 | active-unmerged | rebase, review |
| build/welfare-signal-unblended | 6 | 179 | 6 | active-unmerged | rebase, review |
| fallback/base-wcc | 1 | 168 | 1 | active-unmerged (dup tip) | reconcile with sibling |
| worktree-agent-a78898068c157f9f3 | 1 | 152 | 1 | active-unmerged | check against feat peers |
| worktree-agent-aebab2da16da02c47 | 2 | 96 | 2 | active-unmerged | check against feat peers |
| feat/audition-encoder-bakeoff | 1 | 4 | 1 | active-unmerged | merge candidate |
| feat/voice-dev-stage2-alignment | 4 | 6 | 4 | active-unmerged | merge candidate |
| feat/residency-12.10-lockstep-docs | 20 | 27 | 16 | active-unmerged | rebase, review |
| feat/entity-key-custody-envelope | 3 | 109 | 2 | active-unmerged | reconcile with keyring |
| feat/residency-7.2-auto-rung-selection | 7 | 45 | 6 | active-unmerged | review |
| feat/ablation-pca-decompose | 2 | 15 | 2 | active-unmerged | review |
| feat/custody-escrow | 1 | 93 | 0 | squash-equivalent | delete candidate |
| feat/residency-12.9-lockstep-determinism-tests-v2 | 1 | 22 | 0 | squash-equivalent | delete candidate |
| feat/residency-12.1-stall-indicator | 1 | 44 | 0 | squash-equivalent | delete candidate |
| worktree-agent-a3231a184d00caa48 | 0 | 93 | 0 | merged | delete candidate |
| ablation-spec-5.5-5.6-disclosure | 1 | 7 | 0 | squash-equivalent (experimental) | delete candidate / keep if referenced |
| individuation-rebuild/disclosure-test | 1 | 131 | 1 | active-unmerged (experimental) | keep for research |
| organ/pair-builder-fix | 17 | 179 | 17 | active-unmerged (experimental) | keep for research |
| tools/crossmodal-decodability | 1 | 179 | 0 | squash-equivalent (experimental) | delete candidate |

All counts above are `git rev-list --count origin/main..branch` (ahead),
`origin/main..` reverse (behind), and `git cherry` novel-patch count. No
branches were modified or deleted.
