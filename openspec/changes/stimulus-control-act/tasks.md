# Tasks

## 1. Design

- [x] 1.1 Record the act set, bounds, feed support, derivation stages, credit and records (proposal, design, specs).
- [x] 1.2 Record the operator's timing decision (built before the first boot as a held component, not tied to a study trigger) and keep the refusal of a yoked uncontrolled arm (design, "Timing").
- [x] 1.3 Cite prior work: `playlist-sleep-pause`, `sleep-pauses-feed`, `boredom-own-engagement`, `curiosity-interest`, `welfare-crossing-deprivation`, `act-intent-derivation`, the stir (A.6, A.7), the perceptual-locus self-switch, `active-vision`, `attention-driven-foveation`, `attention-driven-audition`, `development-run`.
- [x] 1.4 Decide the shipped stage: stage M, with the reasons against an act on today's report bars (design D4).

## 2. Effector and feeds

- [x] 2.1 `stimulus` effector with its declared actions and bounds, its request type registered only when it is built. Tests: `tests/test_effector_stimulus.py` (bounds, refusals audited, whitelist required, seek cap over awake time, channels).
- [x] 2.2 In-process control port in place of desired-state fields (design D3); the audit request is the action name only. Tests: `tests/test_effector_stimulus.py`.
- [x] 2.3 Feed support: seekable programme clock with the perceived-time end, `entity` holder with `P_max`, gain with a soft knee, channels, the feeds following a jump through the decoder seek and the audio resync, the container-duration probe. Tests: `tests/test_stimulus_programme_clock.py`, `tests/test_stimulus_feed_real.py` (real media written with PyAV, the real OpenCV and PyAV decode paths, the boot's feed factories and registry).

## 3. Cognition

- [x] 3.1 Credit window for boredom after a realized stimulus act, on both the relief and the build step. Tests: `tests/test_affect_stimulus_credit.py`, with mutation checks on the window.
- [x] 3.2 Stage-M derivation after maturation, seeded uniform draw from the allowed actions, code-site citation, installed only with the effector whitelisted. Tests: `tests/test_stimulus_stage_m.py` (through `ActionSelection`, the signer, the bus and the effectors module).
- [x] 3.3 Workspace-mediation arms refused at boot, and an invalid section refused. Tests: `tests/test_stimulus_off_in_mediation_arms.py`.

## 4. Records and checks

- [x] 4.1 Welfare record and readout, manifest field. Tests: `tests/test_welfare_stimulus_records.py`.
- [x] 4.2 Off equals absent: a seeded entity-free harness digest equal to the golden captured on origin/main d7fabdc0. Test: `tests/test_stimulus_disabled_identity.py`.
- [x] 4.3 Offline check of D6 on the affect module's trackers. Test: `tests/test_stimulus_habituation.py`; record: `docs/records/shakedowns/2026-10-31-stimulus-control-habituation.md`.
- [x] 4.4 Docs: `docs/09-modules/effectors.md`, `docs/09-modules/affect.md`, `docs/appendix-a-configuration/perception-and-sleep.md`, `docs/17-research-data/README.md`.
- [x] 4.5 Independent second review (welfare-high-risk).
- [x] 4.6 Paper change settled through the revision notes: §3.6, §6.5, §9, §11 sentences; A.4 credit; A.6 stage-M rule; Table A1 values for `Delta_sc`, `n_seek`, `P_max`, `G_step`, `G_max`.
- [ ] 4.7 One supervised validation boot on a branch before the join.

## 5. Development-run join (after `development-run` is built)

- [x] 5.1 Registry entry in `config/development_run/components.toml`: class action, readout `stimulus_control`, experience-changing with its second-review record, reversible.
- [x] 5.2 Per-pass viewings: with `programme_end = "continue"`, reset the gain and close a `stimulus_control` record at each pass end, and end each pass at its programme's perceived length.
- [x] 5.3 Operator decision on the paused share, revised on the second review's evidence (F1): a pause waits `Delta_sc` after the previous pause ended, and is taken only while a full one keeps the paused share of the trailing awake hour within 25 %. Test: `tests/test_stimulus_pause_bound.py` (the scripted cycle; stage M under sustained boredom, 5 seeds x 3 h).
- [x] 5.5 Operator decision (2026-11-01): stage M never draws `pause` until learned action selection (stage L) exists; the effector keeps `pause`, its bounds and refusals. Test: `tests/test_stimulus_stage_m.py::test_stage_m_never_draws_pause`; the sustained-boredom test now finds a paused share of 0.
- [x] 5.4 Development-run first-hours stop criterion on the paused share (text in `development-run`): during the first three awake hours after stimulus control is switched on, the run stops at the next pass end and holds for the operator's review when the `stimulus_control` record's `paused_share_last_awake_hour_max` exceeds 0.20 or `pause_share_refusals` is above 0, with the readout's `after_own_act_by_action.pause` reported alongside.

## 6. Stage L (after dependencies)

- [ ] 6.1 After `act-intent-derivation`, `drive-reduction-learning` and `learned-action-selection`: the act bar replaces the drive-led trigger and learned advantages choose the action. Tests: `tests/test_stimulus_stage_l.py`.

## 7. Second review (2026-11-01)

- [x] 7.1 F1 pausing bounded (D1); F2 stage M forms an act only when the effector is ready; F3 sha256 before the probe; F4 refused without the welfare response; F5 a natural wrap is no lag. Tests: `tests/test_stimulus_pause_bound.py`, `tests/test_stimulus_off_in_mediation_arms.py`, `tests/test_stimulus_feed_real.py`.
- [x] 7.2 Recommended: position and epoch from one reading; awake time from the programme's start; the workspace-feedback arms refused; the readout split by action and window-only credited ends counted; the full Eastwood quote and an external citation for restlessness (White 1959); commands refused while asleep or frozen; interval refusals state the shortfall.

## 8. Validation

- [x] 8.1 `openspec validate stimulus-control-act --strict` passes.
