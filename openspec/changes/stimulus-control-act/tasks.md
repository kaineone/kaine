# Tasks

## 1. Design (this change)

- [x] 1.1 Record the act set, bounds, feed support, derivation stages, credit and records (proposal, design, specs).
- [x] 1.2 Argue whether the act gates the study, with the evidence, and fix the pull-forward trigger (design, "Does this gate the study?").
- [x] 1.3 Cite prior work: `playlist-sleep-pause`, `sleep-pauses-feed`, `boredom-own-engagement`, `curiosity-interest`, `welfare-crossing-deprivation`, `act-intent-derivation`, the stir (A.6, A.7), the perceptual-locus self-switch, `active-vision`, `attention-driven-foveation`, `attention-driven-audition`.

## 2. Before any code

- [ ] 2.1 CTO decision on the schedule: build ahead behind the disabled switch (recommended), and whether the disabled code enters the pilot image.
- [ ] 2.2 The pull-forward trigger is written into the pilot welfare check of the study plan before the pilots.
- [ ] 2.3 Paper change settled: §3.6, §6.5, §9, §11 sentences; A.4 credit; A.6 stage-M rule; Table A1 values for `Delta_sc`, `n_seek`, `P_max`, `G_step`, `G_max`.

## 3. Effector and feeds

- [ ] 3.1 `stimulus` effector with its declared actions and bounds; request type reachable through the registered effectors. Tests: `tests/test_effector_stimulus.py` (bounds, refusals audited, whitelist required).
- [ ] 3.2 Desired-state fields (pause flag, seek count, gain, channel). Tests: `tests/test_perception_state_stimulus_fields.py` (flags only).
- [ ] 3.3 Feed support: `entity` holder with `P_max`, wrapping seek, perceived-time end, gain, channels. Tests: `tests/test_playlist_entity_pause.py`, `tests/test_playlist_seek_wrap.py`, `tests/test_playlist_end_perceived_time.py`, `tests/test_audio_feed_gain.py`.

## 4. Cognition

- [ ] 4.1 Credit window for boredom after a realized stimulus act. Tests: `tests/test_affect_stimulus_credit.py`, with a mutation check on the window.
- [ ] 4.2 Stage-M derivation after maturation, seeded draw from the allowed actions, code-site citation. Tests: `tests/test_stimulus_stage_m.py`.
- [ ] 4.3 Workspace-mediation arms pinned off with a boot refusal. Tests: `tests/test_stimulus_off_in_mediation_arms.py`.

## 5. Records and checks

- [ ] 5.1 Welfare record and manifest fields. Tests: `tests/test_welfare_stimulus_records.py`.
- [ ] 5.2 Disabled identity: with the switch off, a seeded synthetic-feed run produces bit-identical broadcasts, intents and welfare records to the current build. Test: `tests/test_stimulus_disabled_identity.py`.
- [ ] 5.3 Offline synthetic-feed check of D6: sustained skipping drives the alert excess toward zero. Recorded under `docs/records/`.
- [ ] 5.4 Docs: `docs/09-modules/effectors.md`, the perception-feed pages, `docs/17-research-data/README.md`.
- [ ] 5.5 One supervised validation boot on a branch before any use.

## 6. Stage L (after dependencies)

- [ ] 6.1 After `act-intent-derivation`, `drive-reduction-learning` and `learned-action-selection`: the act bar replaces the drive-led trigger and learned advantages choose the action. Tests: `tests/test_stimulus_stage_l.py`.
- [ ] 6.2 `openspec validate stimulus-control-act --strict` passes.
