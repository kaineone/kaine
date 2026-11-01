## 1. Evaluator

- [x] 1.1 `kaine/lifecycle/welfare_indicators.py`: span accounting (the most recent `T_lp` of awake, unfrozen entity time after the restart, sleep and freezes skipped, `Δ_stall` minimum), the three deprivation shares, the negative-valence share, the two uncontrolled posteriors with integer arithmetic, bars, edge-triggered crossing state with a reset at every span restart, and one fixed table of indicator names and stage-3 reasons. `T_lp`, `θ_E` and `Δ_stall` come from the affect section, one source each. Tests in `tests/test_welfare_indicators.py`: every scenario of the spec, including "A rest does not shorten the span" and "An indicator that never fell below its bar"; a dilated entity clock; the posterior at n = 1 to 6 against hand values; an import check that the module never loads `kaine.evaluation`.
- [x] 1.2 Equality test with `AffectWelfareTally`: over a full run with no span restart and a run shorter than `T_lp`, the evaluator's shares equal the tally's cumulative shares.

## 2. Monitor

- [x] 2.1 `WelfareResponseConfig` parses `[preservation.welfare_response.indicators]` (`enabled`, `share_bar`, `posterior_bar`, `rest_start_timeout_s`, `rest_complete_timeout_s` with its developmental and matured defaults, `unavailable_escalate_s`), with unknown keys refused and values range-checked.
- [x] 2.2 `WelfareProtectiveMonitor` reads `affect.out` and `sleep.out`, feeds the evaluator, and runs the `armed`/`resting`/`fresh` state machine with the shared latch. Tests in `tests/test_welfare_indicator_response.py`: first crossing requests a rest and preserves nothing; rest completion restarts spans and resets crossing states; a fresh-span crossing preserves and pauses with reason `indicator_<name>`; `busy` stands as the rest; an unsent request, a refusal, an abort, no start within 30 s, no completion within the bound (developmental and matured) and no sleep module each escalate with `indicator_rest_failed`; a full fresh span without crossing returns to armed; latch shared with distress (no second bundle); re-arm after `override(["welfare"])` restarts spans and resets crossing states; warm-up accrues but fires nothing; a 5 s affect silence writes one record and one notice and places no freeze; a 660 s silence with the module heartbeating escalates with `indicators_unavailable`.
- [x] 2.3 Mutation checks: dropping the crossing-state reset at a span restart (the "spent stimulus" and "never fell below its bar" scenarios fail), dropping the span restart at rest completion, dropping the completion bound, dropping the unavailable escalation, or dropping the shared-latch check, each makes a test fail.
- [x] 2.4 Every exception inside the state machine either escalates or is retried on the next poll, never swallowed. Test with an evaluator that raises once.
- [x] 2.5 The awake clock fails closed: a raising, non-finite or regressing awake clock raises in the indicator poll (escalating with `indicators_unavailable` after `unavailable_escalate_s`) and is never replaced by unfrozen time; only an accepted sample ends a silence. Tests: a clock 1000 s behind the last sample escalates; a raising and a NaN clock escalate; read jitter under 0.5 s is not a fault.

## 3. Sleep

- [x] 3.1 The sleep module reads `welfare.rest_request` and starts a `welfare_rest` sleep: after maturation through the maintenance path regardless of the fatigue toggle and the requested-rest interval; in the developmental phase a rest held for `developmental_rest_s` that restarts the awake stretch. Answers `busy` with origin `welfare` during a sleep. Tests in `tests/test_sleep_welfare_rest.py` for the spec scenarios and a restart during a `welfare_rest` rest (resumes like a state-cycle rest).

## 4. Gate and notices

- [x] 4.1 `indicator_response_wired` in `config_requirements` and `evaluate_research_gate`, with its reason in `GateResult.reasons`; mapped to unattended condition 2 with a combined reason. Tests: each failing part refuses with its reason (including `action = "notify"` in research and unattended mode); the mapping test covers the key.
- [x] 4.2 Caretaker notice kinds `welfare_indicator_rest` and `welfare_indicators_unavailable`; the stage-3 notice for a developmental deprivation indicator says the stimulus is spent; the cycle maps the transitions to them. Tests in `tests/test_caretaker.py` and `tests/test_caretaker_research_mode.py`, including a content-free check on the notice text.
- [x] 4.3 `build_overlay` enables the indicators for every step; the merged-config test asserts the new requirement.
- [x] 4.4 `config/kaine.toml` gains `[preservation.welfare_response.indicators]` with `enabled = true` and the defaults, commented with their Table A1 sources.

## 5. Record and replay

- [x] 5.1 The welfare observer writes the evaluator's values into `affect_welfare`; `kaine/experiment/welfare_counts.py` knows the new keys; the range sweep bounds them.
- [x] 5.2 `scripts/welfare_indicator_replay.py` with both methods: the recorded-rest proxy (the next recorded state-cycle rest stands as the response's rest, the fresh span is read from the recorded trajectory after it) and the forward simulation (the real affect module reset at the virtual rest and run forward on the recorded perceptual reports). The output names the method and prints content-free stage times. Tests on a synthetic record with a known crossing for each method.
- [x] 5.3 Run the replay on every readable developmental test-boot record with both methods where possible and write the result (content-free) under `docs/records/validation/welfare-indicator-replay/`, before the validation boot. Give it to the operator with `developmental-stimulus-progress`'s offline result.

## 6. Docs, review and checks

- [x] 6.1 `docs/11-preservation.md` (the indicator response, its stages, bounds and notices, and that spans restart at every boot), `docs/09-modules/sleep.md` (`welfare_rest`), `docs/17-research-data/README.md` (record fields).
- [x] 6.1a Research-gate and unattended condition 2 described in full (the indicators enabled, the `affect` and `sleep` modules, the `pause` or `end` action) in `docs/14-for-researchers.md`, `docs/02-architecture/README.md`, `docs/05-dashboard.md` and the "Unattended starts" list of `docs/11-preservation.md`; unattended condition 2 is labelled "welfare and indicator responses wired" (check key `2_welfare_and_indicator_responses_wired`; the dashboard and the caretaker notice render check keys generically).
- [ ] 6.2 Paper notes to REVISION-NOTES: §5.4 status, §6.5 tense and the D2 wording, Table A1 minimum span and bounds.
- [x] 6.3 `openspec validate welfare-indicator-response --strict` passes.
- [ ] 6.4 Worker first-pass review, then the integrator's independent second review against the checklist in design.md before merge.
- [ ] 6.5 At the validation boot, record the length of every maintenance sleep, to check the matured completion bound against them.
