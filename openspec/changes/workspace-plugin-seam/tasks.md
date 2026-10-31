## 1. Design (this change)

- [x] 1.1 Record the three seams, what stays outside them, the checks, the context-width rule, recording, the research gate and the estimate.

## 2. Start condition

- [ ] 2.1 **Deferred:** the first module-addition study has finished, and the pre-study capacity change (continuous competition, one access per broadcast, count-yoked matched arm) has merged, so the seam wraps the rule that change leaves.

## 3. Protocols and defaults (PR 1)

- [ ] 3.1 `kaine/workspace/seams.py`: `AccessRule`, `AccessDecision`, `ContextEncoder`; `SalienceStrategy` re-exported from `kaine/workspace/strategies.py`
- [ ] 3.2 The default access rule, moved out of `Workspace._compose`; the default encoder, moved out of `featurize_events` and `BroadcastContext._null_from`
- [ ] 3.3 Decision checks and the inhibited-on-failure path with the `access_rule_failures` count
- [ ] 3.4 Tests: `tests/test_workspace_seam_bitwise.py` (recorded batches and broadcasts give identical snapshots, score tables, contexts and null contexts, in all three arms); `tests/test_workspace_access_decision_checks.py` (each malformed decision and a raising rule inhibit and count, with no fallback)

## 4. Loader, construction path and gates (PR 2)

- [ ] 4.1 `workspace.salience`, `workspace.access`, `workspace.context` in `INJECTABLE_SEAMS` handling and `workspace_injections`
- [ ] 4.2 `build_workspace` used by the cycle, the workspace-mediation runner, the oscillatory runner and the red-team harness
- [ ] 4.3 Matched and pooled arms over `AccessDecision`
- [ ] 4.4 `workspace_account` in the run manifest and the broadcast metadata
- [ ] 4.5 Research-gate check against `[study].workspace_account`; run-admissibility failure share
- [ ] 4.6 Tests: `tests/test_plugins_workspace_seams.py` (unknown, duplicate, incomplete and `None` objects refused; a rival rule used); `tests/test_workspace_arms_plugin_rule.py` (matched keeps count and inhibition; pooled unchanged); `tests/test_research_gate_workspace_account.py`; `tests/test_admissibility_access_failures.py`
- [ ] 4.7 Worker first-pass review, lead review, independent second review (welfare-high-risk)

## 5. Context width, checkpoints and calibration (PR 3)

- [ ] 5.1 Vision, audition and interoception size context weights from the encoder width; width bound 1024
- [ ] 5.2 Checkpoints record encoder id and width; mismatch stops the boot unless `[workspace.seams].reinit_context_weights`
- [ ] 5.3 Workspace feedback refuses to start with a non-default context encoder until its head is sized from the encoder (feedback is held and off)
- [ ] 5.4 Settings records carry the account; calibration and the verdict refuse mixed accounts
- [ ] 5.5 A test-only rival plugin (`tests/plugins/rival_workspace.py`: a one-member rule and a 30-component encoder) exercising every seam end to end on the mediation runner with no entity
- [ ] 5.6 Tests: `tests/test_context_width_from_encoder.py`; `tests/test_context_checkpoint_encoder_id.py` (mismatch refused, flag zeroes context weights and keeps the rest, legacy checkpoint read as default); `tests/test_calibrate_workspace_account.py`; `tests/test_privacy_plugin_context.py` (no plugin context vector in diagnostics, log or memory traces)
- [ ] 5.7 Docs: global workspace chapter, plugins chapter, configuration appendix; paper notes for §1.4, §3.1, §5.2, §8.3, A.1 and Table A1 in the paper's revision notes
- [ ] 5.8 Worker first-pass review, lead review, independent second review
