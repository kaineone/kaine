## 1. Design

- [x] 1.1 Research and predictions: `kaine-research/sensors-bodies-locus-research-2026-11-01.md`, section 8.
- [x] 1.2 The source selection, the act and arbiter, the gates, the welfare hold, stage M and its composition, the credit, the context bank, the self-model record, sleep, the event fix and the readout (proposal, design, specs).
- [x] 1.3 Prior work cited and built on:
  - the perceptual locus (spec `perceptual-locus`);
  - `stimulus-control-act`;
  - `developmental-maturation-gate`;
  - the sleep restore (spec `perception-feed`);
  - `interest-goal-factor`;
  - `fork-merge-module-weights` (#638);
  - `act-intent-derivation` and `learned-action-selection`.
- [x] 1.4 Revised after the adversarial review (`kaine-research/paper-audit-2026-10-31/SENSORS-LOCUS-SPEC-REVIEW.md`, PLS-1 to PLS-15), with the PM's decisions on PLS-1, PLS-2, PLS-3, PLS-6, PLS-7 and PLS-8.
- [ ] 1.5 Propose the `effector-confinement` amendment (a profile class that publishes one declared request to one named stream) in that change, jointly with `stimulus-control-act`, for its own review.

## 2. Locus and act (one PR, after `perceptual-sources` 2.x)

- [ ] 2.1 Moved to `perceptual-sources` task 2.9: the single desired-state model (re-review R-PS-1). Here, the arbiter and the operator source route write through its `update_desired`.
- [ ] 2.2 The arbiter with its ordered gates (selectable before available) and reason labels, inhibition read from the broadcast (inhibited until the first snapshot), the return-to-programme exemption, and the legacy intent refused. Tests: `tests/test_perceptual_switch_arbiter.py`, one case per gate, order checks and mutation checks.
- [ ] 2.3 The `perceptual_source` effector through the confined executor, after 1.5: a signed request on `perceptual_locus.requests`, verified by the arbiter, with its own hash-chained audit. Tests: through `ActionSelection`, the signer, the bus and the effectors module; a forged request refused.
- [ ] 2.4 The operator source route, the `/locus` defaults, and the operator off-holder. Tests: extend the dashboard perception tests (token required, 409 without a default, developmental lock wins, `screen` only with the opt-in).
- [ ] 2.5 The event fields and the research allowlist fix. Tests: allowlist exactness for both events, and a denial reaching the research log.
- [ ] 2.6 The welfare hold: into-sources only; return always allowed; recurring distress returns home with `welfare_hold`; escalation through the unattended welfare path. Tests: each rule, and that the hold never refuses a return.
- [ ] 2.7 The main spec's `[perception]` sentence corrected to `[perceptual_locus]` when the change is archived.

## 3. Cognition (one PR)

- [ ] 3.1 The switch stage M, and the composed input-act source with the stimulus-control stage M, with the code-site citation. Tests: uniform draw over the union, at most one act per broadcast, none while developing.
- [ ] 3.2 Credit: learning progress only, with alert excess excluded inside the adaptation period. Tests: extend the stimulus-credit tests, with mutation checks on the window.
- [ ] 3.3 The offline habituation check for switch bursts (vision and audition together), with a dated record under `docs/records/shakedowns/`.
- [ ] 3.4 The context bank in vision and audition, including the mechanics below. Tests: a return leaves the stored weights unchanged; a first entry carries no buffer or latent; a merge takes the whole bank from the named parent; the guard test runs with a populated bank.
  - `forward_model_bank` in `MODULE_WEIGHT_GROUPS` and `MODULE_WEIGHT_PARAMETERS`;
  - first-entry copies from `state_dict()` with empty buffers and windows;
  - no alert until the window holds a quarter of its length;
  - wraps and shadows rebuilt around the bound model.
- [ ] 3.5 The self-model embodiment record. Tests: labels only.
- [ ] 3.6 Sleep's off-holder: built in `perceptual-sources` task 2.9.

## 4. Records and checks

- [ ] 4.1 The `perceptual_switching` record, with adaptation measured on raw error and the savings ratio. Tests: synthetic report streams with a known transient; a window refill alone must not count as adaptation.
- [ ] 4.2 Off equals absent, both harnesses (registry off; registry on with switching off), with goldens captured on the merge base and a manual clock.
- [ ] 4.3 Docs:
  - `docs/09-modules/perceptual-locus.md` (status, the gates, the stale `[perception]` wording);
  - `effectors.md`, `affect.md`, `self-model.md`, `vision.md`, `audition.md`;
  - `docs/17-research-data/README.md`;
  - the `[perceptual_locus]` comments in `config/kaine.toml`.
- [ ] 4.4 Independent second review (welfare-high-risk).
- [ ] 4.5 Paper revision notes:
  - §3.5 and §3.6, A.4, A.6;
  - Table A1 (`min_dwell_s`, `min_dwell_new_source_s` as a provisional value, `max_switches_per_awake_hour`, `welfare_hold_window_s`, `welfare_return_s`).
- [ ] 4.6 One supervised validation boot on a branch before the join, after 3.3.
- [ ] 4.7 `openspec validate perceptual-locus-switching --strict`.

## 5. Later

- [ ] 5.1 Stage L, after `act-intent-derivation` and `learned-action-selection`.
- [ ] 5.2 Context selection by prediction error (MOSAIC's online correction), if the readout shows a source's world changing under its label.
