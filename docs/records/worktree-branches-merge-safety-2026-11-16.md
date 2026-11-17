# Worktree branch merge safety (2026-11-16)

Docs/report only. No branches, files, or state were modified.

## Method

- Seven `worktree-agent-*` merge candidates from `docs/records/worktree-agent-triage-2026-11-16.md`.
- Compared each branch to current local `main` (`3ee784ea`) using:
  - `git merge-base`, 1-commit-ahead inventory (3-dot diff, branch-only changes)
  - path categorization (code/config/docs/tests)
  - existence check for tests in branch
  - `git merge-tree --write-tree main <branch>` dry-run (no index/worktree writes)
- "Recently modified on main" was taken as commits on `main` after each branch merge base, including the named latest main commits touching the same files.
- Session hazard check was against the uncommitted files in this worktree (`git status --short`), including modified `config/kaine.toml`, `openspec/changes/module-ignition-study/tasks.md`, `openspec/changes/individuation-rebuild/validation/test_lora.py`, and untracked docs/tests/tools.

## Session overlap

No direct path overlap between the uncommitted session files and any of the seven branch file sets. Indirect/content risk remains where a branch and a recently merged main PR touched the same source files; those are listed per branch below.

## Summary

| Branch | Hash (full) | Commits ahead | Code | Tests | Config/docs | Tests in branch? | Dry-run | Main content already identical? |
|---|---|---:|---:|---:|---:|---|---|---|
| a788 | `5db9466208720e1595ee37b1a00166d34fa19320` | 1 | 4 | 1 | 0 | yes (new) | 3 conflicts | none |
| a835 | `8062a3107f11fca1f7296b12e0469e8ac4d313c1` | 1 | 4 | 1 | 0 | yes (new) | 1 conflict | 3/4 code + test already on main |
| a948 | `73ede6c51942e2f3e7c4f1740d9561219b8ac276` | 1 | 4 | 0 | 0 | no | 2 conflicts | 1/4 (`setup/speech_models.py`) already on main |
| a9c8 | `408024bb4785d4d7d9fad23e819d7b88b771578e` | 1 | 3 | 1 | 0 | yes (modified) | 1 conflict | 3/4 files already on main; only social module differs |
| ab24 | `6add69b80cd92af0d4712ef1c5a2dbcf0a451a6b` | 1 | 0 | 1 | 0 | yes (modified) | clean auto | entire test file already identical to main |
| ae7a | `c44fdd41ac1f9c78e1451515dfb9c30b6c673698` | 1 | 0 | 1 | 0 | yes (new) | clean auto | entire test file already identical to main |
| aeba | `566c9beec04be6d268537b3e48261101c8b2c379` | 2 | 2 | 1 | 0 | yes (modified) | 1 conflict | test file already identical to main |

---

## a788 - workspace feedback preservation (high risk: core feedback/preservation)

- Hash: `5db9466208720e1595ee37b1a00166d34fa19320`
- Merge base: `3890429` (latent-content-privacy-rule structural guards)
- Branch-only files:
  - `kaine/cycle/__main__.py` (modified)
  - `kaine/lifecycle/preservation.py` (modified)
  - `kaine/modules/feedback.py` (modified)
  - `kaine/workspace/feedback.py` (modified)
  - `tests/test_feedback_preservation.py` (new)
- Categories: code 4, tests 1, config 0, docs 0.
- Tests exist? yes (new test file in branch).
- Redundancy vs main: none of the five files is identical to current `main`.
- Main concurrency:
  - `kaine/cycle/__main__.py`: 5 main commits since base; latest `af05c58e` (supervisor treats barrier-waiting modules as alive, #796).
  - `kaine/lifecycle/preservation.py`: 3 main commits; latest `8e2c38ac` (CodeQL alerts in custody/preservation, #720).
  - `kaine/modules/feedback.py`: 2 main commits; latest `4ee8fe0e` (content workspace level option F, #658).
  - `kaine/workspace/feedback.py`: 2 main commits; latest `4ee8fe0e`.
  - `tests/test_feedback_preservation.py`: 1 main commit; latest `961fdf32` (workspace-feedback preserve top-down heads, #657).
- Dry-run conflicts:
  - `kaine/modules/feedback.py` (content)
  - `kaine/workspace/feedback.py` (content)
  - `tests/test_feedback_preservation.py` (add/add)
- Risk notes: core preservation + feedback code changed independently on main; auto-merge still updates `cycle/__main__.py` and `lifecycle/preservation.py`, then conflicts on the two feedback modules and the test. Requires manual rebase and adversarial review before merge.

## a835 - stimulus-control per-pass (medium risk: effector/stimulus)

- Hash: `8062a3107f11fca1f7296b12e0469e8ac4d313c1`
- Merge base: `3f346c6` (archive per-entity-shared-volumes)
- Branch-only files:
  - `kaine/cycle/programme_end.py` (modified; differs from main)
  - `kaine/modules/effectors/stimulus/controller.py` (modified; identical to main)
  - `kaine/modules/effectors/stimulus/programme.py` (modified; identical to main)
  - `kaine/modules/effectors/stimulus/records.py` (modified; identical to main)
  - `tests/test_stimulus_per_pass.py` (new; identical to main)
- Categories: code 4, tests 1.
- Tests exist? yes (new test file; already landed on main).
- Redundancy vs main: most of the change already exists on main; only `programme_end.py` still differs.
- Main concurrency: all 4 source/test paths have 1 main commit since base; latest `26ead231` (stimulus-control first-hours criterion, #669).
- Dry-run conflicts: `kaine/cycle/programme_end.py` (content) only.
- Risk notes: likely partial duplicate of the already-merged 5.4 stimulus-control PR. Rebase before merge; only reconcile the programme_end hunk.

## a948 - audition SpeakerEmbedder (medium/high risk: model provisioning + new module, no tests)

- Hash: `73ede6c51942e2f3e7c4f1740d9561219b8ac276`
- Merge base: `d38f023` (offline cross-modal decodability measurement)
- Branch-only files:
  - `kaine/model_paths.py` (modified; differs from main)
  - `kaine/modules/audition/speaker_embedder.py` (new; differs from main)
  - `kaine/setup/speech_models.py` (modified; identical to main)
  - `kaine/speech_manifest.py` (modified; differs from main)
- Categories: code 4, tests 0.
- Tests exist? no. Add coverage before merge.
- Redundancy vs main: `setup/speech_models.py` already identical to main.
- Main concurrency:
  - `kaine/model_paths.py`: 2 main commits since base; latest `1e280e1b` (face detection/expression/gaze pipeline, #683).
  - `kaine/modules/audition/speaker_embedder.py`: 2 main commits; latest `2df9a748` (residency integration routing for vision/audition, #738).
  - `kaine/setup/speech_models.py`: 1 main commit; latest `7a9794c3` (audition speaker embedding extraction pipeline, #682).
  - `kaine/speech_manifest.py`: 1 main commit; latest `7a9794c3`.
- Dry-run conflicts:
  - `kaine/modules/audition/speaker_embedder.py` (add/add)
  - `kaine/speech_manifest.py` (content)
- Risk notes: main already added a speaker embedding extraction pipeline. Direct merge conflicts; manual integration and new tests required. Safety-critical provenance (model path/manifest changes).

## a9c8 - social-cognition face expression/emotion (medium risk: social module)

- Hash: `408024bb4785d4d7d9fad23e819d7b88b771578e`
- Merge base: `b363110` (cross-modal identity binder)
- Branch-only files:
  - `kaine/faithful/felt.py` (modified; identical to main)
  - `kaine/faithful/templates.py` (modified; identical to main)
  - `kaine/modules/social_cognition/module.py` (modified; differs from main)
  - `tests/test_faithful_templates.py` (modified; identical to main)
- Categories: code 3, tests 1.
- Tests exist? yes (modified; already on main).
- Redundancy vs main: all files except `social_cognition/module.py` are already on main.
- Main concurrency: all 4 paths have 1 main commit; latest `f5b0cc66` (social-cognition emotion fusion/config tiers/preservation test, #685).
- Dry-run conflicts: `kaine/modules/social_cognition/module.py` (content) only.
- Risk notes: only one nontrivial code hunk remains; rebase should reduce to that file, then check social cognition behavior and template tests.

## ab24 - speech models tests (low risk: tests only, likely redundant)

- Hash: `6add69b80cd92af0d4712ef1c5a2dbcf0a451a6b`
- Merge base: `1f6da36` (probe-host fit report)
- Branch-only file: `tests/test_speech_models.py` (modified; identical to main)
- Categories: tests only.
- Tests exist? yes (modified; already on main).
- Redundancy vs main: entire file identical to main.
- Main concurrency: 1 main commit since base; latest `4641ae40` (consent-denied/idempotent-fetch speech tests, #758).
- Dry-run conflicts: none (clean auto-merge).
- Risk notes: likely already merged under #758. Confirm branch commit adds nothing beyond main before closing/abandoning; no source risk.

## ae7a - social cognition preservation tests (low risk: tests only, likely redundant)

- Hash: `c44fdd41ac1f9c78e1451515dfb9c30b6c673698`
- Merge base: `b363110` (cross-modal identity binder)
- Branch-only file: `tests/test_social_cognition_preservation.py` (new; identical to main)
- Categories: tests only.
- Tests exist? yes (new; already on main).
- Redundancy vs main: entire file identical to main.
- Main concurrency: 1 main commit since base; latest `f5b0cc66` (emotion fusion/config tiers/preservation test, #685).
- Dry-run conflicts: none (clean auto-merge).
- Risk notes: likely already merged under #685. Confirm no unique content before abandoning the branch.

## aeba - language episodic recall + redaction (high risk: privacy/redaction)

- Hash: `566c9beec04be6d268537b3e48261101c8b2c379` (2 commits)
- Merge base: `8ca2de7` (fake clock transition test fix)
- Branch-only files:
  - `kaine/modules/language/context.py` (modified; differs from main)
  - `kaine/modules/language/module.py` (modified; differs from main)
  - `tests/test_language_context.py` (modified; identical to main)
- Categories: code 2, tests 1.
- Tests exist? yes (modified; already on main).
- Redundancy vs main: test file identical to main; both code files still differ.
- Main concurrency:
  - `kaine/modules/language/context.py`: 1 main commit; latest `97e7c4e9` (episodic memory recall and dialogue in context, #718).
  - `kaine/modules/language/module.py`: 2 main commits; latest `6e030c9a` (lockstep mode for language/perception, #780).
  - `tests/test_language_context.py`: 1 main commit; latest `97e7c4e9`.
- Dry-run conflicts: `kaine/modules/language/module.py` (content).
- Risk notes: redaction-sensitive path. Context auto-merges against main's #718 version; module.py conflicts with main's later lockstep changes. Requires targeted merge, focused tests, and privacy review.

---

## Recommended merge handling

1. Prioritize `a788` and `aeba` (feedback preservation and privacy/redaction): manual rebase, conflict resolution, worker first-pass review, Claude adversarial sign-off.
2. For `a835`, `a9c8`, and `aeba`, strip commits/files already identical to main and carry only differing hunks (a948 also needs tests before merge).
3. Treat `ab24` and `ae7a` as likely no-op branches; verify commit content, then either abandon with operator approval or remove if explicitly approved.
4. `a948` lacks tests; add speaker-embedder coverage and test merge behavior with main's #738 integration before merge.
5. No deletions or merges were performed while producing this report.