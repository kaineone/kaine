# Worktree-agent branch triage (2026-11-16)

Scope: `worktree-agent-*` branches in `/var/home/erik/Projects/kaineone/kaine`. Branches were inspected; none were deleted.

## Counts

- Total `worktree-agent-*` branches present: 17 (prompt referenced 60; only 17 exist in this repo)
- Already merged into `main` (0 commits ahead): 10 -> `abandon-with-approval`
- Unmerged (1+ commits ahead of `main`): 7 -> `merge candidate`
- `keep` (actively in-progress, no merge path yet): 0

All 7 unmerged branches touch `kaine/` source code (plus tests in several cases); none are docs/config-only.

## Branch inventory (all 17)

| Branch | Commits ahead of main | Touches source (kaine/) | Classification |
|---|---:|---|---|
| worktree-agent-a05b06b4cc0c0d491 | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-a17c49e711e9ce22b | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-a3231a184d00caa48 | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-a3923ff4b59d61aac | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-a3ef81feb8406aeef | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-a78898068c157f9f3 | 1 | yes | merge candidate |
| worktree-agent-a8354776b02549459 | 1 | yes | merge candidate |
| worktree-agent-a94898e7da9879172 | 1 | yes | merge candidate |
| worktree-agent-a9557ea5c2a5ba93e | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-a9c82ff748647723d | 1 | yes | merge candidate |
| worktree-agent-aaa077fed924c70a2 | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-ab24b71e74d8ffe49 | 1 | no (tests only) | merge candidate |
| worktree-agent-ad99d68b81d82780b | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-ae7ab9df23db422f8 | 1 | no (tests only) | merge candidate |
| worktree-agent-aebab2da16da02c47 | 2 | yes | merge candidate |
| worktree-agent-af4dde7b3fc8372b1 | 0 | n/a (merged) | abandon-with-approval |
| worktree-agent-afa11a1b0b74d2ca1 | 0 | n/a (merged) | abandon-with-approval |

## Representative detailed findings (10)

1. worktree-agent-a78898068c157f9f3
   - `git log`: `5db94662 (worktree-agent-a78898068c157f9f3) workspace-feedback: preserve top-down heads and gains through preservation and revive`
   - Files touched: kaine/cycle/__main__.py, kaine/lifecycle/preservation.py, kaine/modules/feedback.py, kaine/workspace/feedback.py, tests/test_feedback_preservation.py
   - Classification: merge candidate (feedback/preservation core -> needs adversarial review)

2. worktree-agent-a8354776b02549459
   - `git log`: `8062a310 (worktree-agent-a8354776b02549459) stimulus-control-act 5.2: per-pass viewings with continue mode`
   - Files touched: kaine/cycle/programme_end.py, kaine/modules/effectors/stimulus/controller.py, kaine/modules/effectors/stimulus/programme.py, kaine/modules/effectors/stimulus/records.py, tests/test_stimulus_per_pass.py
   - Classification: merge candidate

3. worktree-agent-a94898e7da9879172
   - `git log`: `73ede6c5 (worktree-agent-a94898e7da9879172) feat(audition): add SpeakerEmbedder class and CAM++ model provisioning`
   - Files touched: kaine/model_paths.py, kaine/modules/audition/speaker_embedder.py, kaine/setup/speech_models.py, kaine/speech_manifest.py
   - Classification: merge candidate (ships code with no tests in the commit -> add coverage before merge)

4. worktree-agent-a9c82ff748647723d
   - `git log`: `408024bb (worktree-agent-a9c82ff748647723d) feat(social-cognition): face expression consumer, emotion fusion, and faithful templates`
   - Files touched: kaine/faithful/felt.py, kaine/faithful/templates.py, kaine/modules/social_cognition/module.py, tests/test_faithful_templates.py
   - Classification: merge candidate

5. worktree-agent-ab24b71e74d8ffe49
   - `git log`: `6add69b8 (worktree-agent-ab24b71e74d8ffe49) test: consent-denied and idempotent-fetch tests for speech models (task 9.5 partial)`
   - Files touched: tests/test_speech_models.py
   - Classification: merge candidate (tests only; low-risk)

6. worktree-agent-ae7ab9df23db422f8
   - `git log`: `c44fdd41 (worktree-agent-ae7ab9df23db422f8) test(social-cognition): preservation round-trip for agent profiles with embeddings`
   - Files touched: tests/test_social_cognition_preservation.py
   - Classification: merge candidate (tests only; low-risk)

7. worktree-agent-aebab2da16da02c47
   - `git log`: `566c9bee fix(language): redact heard speech in dialogue section of logged prompt` ; `1e886d7f feat(language): add episodic memory recall and dialogue buffer to context assembly`
   - Files touched: kaine/modules/language/context.py, kaine/modules/language/module.py, tests/test_language_context.py
   - Classification: merge candidate (privacy/redaction-sensitive; review first)

8. worktree-agent-a05b06b4cc0c0d491
   - `git log`: (empty; 0 commits ahead of main)
   - Classification: abandon-with-approval (already reachable from main)

9. worktree-agent-a17c49e711e9ce22b
   - `git log`: (empty; 0 commits ahead of main)
   - Classification: abandon-with-approval (already reachable from main)

10. worktree-agent-a3231a184d00caa48
    - `git log`: (empty; 0 commits ahead of main)
    - Classification: abandon-with-approval (already reachable from main)

## Top recommendations

1. Route the 7 unmerged source branches through the standard pipeline (feature branch -> PR -> worker first-pass review -> Claude adversarial sign-off -> merge), prioritizing `aebab2da16da02c47` (speech redaction/PII) and `a78898068c157f9f3` (feedback/preservation).
2. Require test coverage for `a94898e7da9879172` (SpeakerEmbedder) before merge; its commit adds code without tests.
3. After operator approval, delete the 10 `abandon-with-approval` merged-empty branches to reduce branch noise. Do not delete without approval; none have been deleted.
4. Reconcile branch inventory with the "60 active-unmerged" figure; this repo holds 17 total, of which 7 are unmerged.
