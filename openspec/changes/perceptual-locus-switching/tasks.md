## 1. Design

- [x] 1.1 Research and predictions: `kaine-research/sensors-bodies-locus-research-2026-11-01.md`, section 8.
- [x] 1.2 The source selection, the act and arbiter, the gates, the welfare hold, stage M and its composition, the credit, the context bank, the self-model record, sleep, the event fix and the readout (proposal, design, specs).
- [x] 1.3 Prior work cited and built on:
  - the perceptual locus and its gate (spec `perceptual-locus`);
  - `stimulus-control-act` (stage M, credit, bounds, records);
  - `developmental-maturation-gate` (the lock);
  - the sleep restore (spec `perception-feed`);
  - `interest-goal-factor`;
  - `act-intent-derivation` and `learned-action-selection` (stage L).

## 2. Locus and act (one PR, after `perceptual-sources` 2.x)

- [ ] 2.1 `source` in desired state, the derived locus, and the vision gate reading the source's class. Tests: extend `tests/test_perception_state.py` and `tests/test_perception_locus.py` (physical XOR virtual preserved, no `source` with the registry off).
- [ ] 2.2 The arbiter with its ordered gates and reason labels, shared by the effector and the legacy consumer. Tests: `tests/test_perceptual_switch_arbiter.py`, one case per gate, order checks and mutation checks.
- [ ] 2.3 The `perceptual_source` effector, its declared parameter and in-process confinement profile, a refusal reported as a failed act, and the audit. Tests: through `ActionSelection`, the signer, the bus and the effectors module.
- [ ] 2.4 The operator source route and the `/locus` defaults. Tests: extend the dashboard perception tests (token required, 409 without a default, developmental lock wins).
- [ ] 2.5 The event fields and the research allowlist fix. Tests: allowlist exactness for both events, and a denial reaching the research log.
- [ ] 2.6 The welfare hold and its advisory. Tests: two of three switches followed by protective actions trigger the hold; an operator switch is not held; the operator lifts it.

## 3. Cognition (one PR)

- [ ] 3.1 The switch stage M, and the composed input-act source with the stimulus-control stage M, with the code-site citation. Tests: uniform draw over the union, at most one act per broadcast, none while developing.
- [ ] 3.2 Credit widened to `perceptual_source`. Tests: extend the stimulus-credit tests, with mutation checks on the window.
- [ ] 3.3 The context bank in vision and audition, including wraps and shadows, with copy-on-first-entry and serialisation. Tests: return after a different source leaves the stored weights unchanged; a first entry copies; bundle round-trip with no raw latent.
- [ ] 3.4 The self-model embodiment record. Tests: labels only.
- [ ] 3.5 Sleep restores the source. Tests: extend the sleep restore tests.

## 4. Records and checks

- [ ] 4.1 The `perceptual_switching` record and the adaptation-time and savings computation. Tests: synthetic report streams with a known transient.
- [ ] 4.2 Off equals absent, both harnesses (registry off; registry on with switching off).
- [ ] 4.3 Docs:
  - `docs/09-modules/perceptual-locus.md` (status, the gates, and the stale `[perception]` wording);
  - `effectors.md`, `affect.md`, `self-model.md`, `vision.md`, `audition.md`;
  - `docs/17-research-data/README.md`;
  - the `[perception]` comments in `config/kaine.toml`.
- [ ] 4.4 Independent second review (welfare-high-risk).
- [ ] 4.5 Paper revision notes: §3.5 and §3.6, A.4, A.6, Table A1 (`min_dwell_s`, `min_dwell_new_source_s`, `max_switches_per_awake_hour`, `welfare_hold_window_s`).
- [ ] 4.6 One supervised validation boot on a branch before the join.
- [ ] 4.7 `openspec validate perceptual-locus-switching --strict`.

## 5. Later

- [ ] 5.1 Stage L, after `act-intent-derivation` and `learned-action-selection`.
- [ ] 5.2 Context selection by prediction error (MOSAIC's online correction), if the readout's adaptation times show a source's world changing under its label.
