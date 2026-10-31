## 1. Evaluator

- [ ] 1.1 `kaine/lifecycle/welfare_indicators.py`: span accounting (awake, unfrozen entity time, restart, `T_lp` cap, `Δ_stall` minimum, sleep and freeze exclusion), the three deprivation shares, the negative-valence share, the two uncontrolled posteriors with integer arithmetic, bars, the fixed indicator name table. `T_lp`, `θ_E` and `Δ_stall` come from the affect section, one source each. Tests in `tests/test_welfare_indicators.py`: every scenario of the spec, a dilated entity clock, a span that straddles a sleep, the posterior at n = 1 to 6 against hand values, and an import check that the module never loads `kaine.evaluation`.
- [ ] 1.2 Equality test with `AffectWelfareTally`: over a full run with no span restart and a span longer than the run, the evaluator's shares equal the tally's cumulative shares.

## 2. Monitor

- [ ] 2.1 `WelfareResponseConfig` parses `[preservation.welfare_response.indicators]` (`enabled`, `share_bar`, `posterior_bar`, `rest_start_timeout_s`), with unknown keys refused and values range-checked.
- [ ] 2.2 `WelfareProtectiveMonitor` reads `affect.out` and `sleep.out`, feeds the evaluator, and runs the `armed`/`resting`/`fresh` state machine with the shared latch. Tests in `tests/test_welfare_indicator_response.py`: first crossing requests a rest and preserves nothing; rest completion restarts spans; a fresh-span crossing preserves and pauses with reason `indicator_<name>`; `busy` stands as the rest; refusal, abort, timeout and no sleep module each escalate with `indicator_rest_failed`; a full fresh span without crossing returns to armed; latch shared with distress (no second bundle); re-arm after `override(["welfare"])` restarts spans; warm-up accrues but fires nothing; affect silence writes one record and one notice and does not freeze.
- [ ] 2.3 Mutation checks: dropping the span restart at rest completion, or the shared-latch check, or the escalation on a refused rest, each makes a test fail.
- [ ] 2.4 Every exception inside the state machine either escalates or is retried on the next poll, never swallowed. Test with an evaluator that raises once.

## 3. Sleep

- [ ] 3.1 The sleep module reads `welfare.rest_request` and starts a `welfare_rest` sleep: after maturation through the maintenance path regardless of the fatigue toggle and the requested-rest interval; in the developmental phase a rest held for `developmental_rest_s` that restarts the awake stretch. Answers `busy` with origin `welfare` during a sleep. Tests in `tests/test_sleep_welfare_rest.py` for the three scenarios and a restart during a `welfare_rest` rest (resumes like a state-cycle rest).

## 4. Gate and notices

- [ ] 4.1 `indicator_response_wired` in `config_requirements` and `evaluate_research_gate`; mapped to unattended condition 2 with a combined reason. Tests: each failing part refuses with its reason; the mapping test covers the key.
- [ ] 4.2 Caretaker notice kinds `welfare_indicator_rest` and `welfare_indicators_unavailable`; the cycle maps the transitions to them. Tests in `tests/test_caretaker.py` and `tests/test_caretaker_research_mode.py`, including a content-free check on the notice text.
- [ ] 4.3 `build_overlay` enables the indicators for every step; the merged-config test asserts the new requirement.
- [ ] 4.4 `config/kaine.toml` gains `[preservation.welfare_response.indicators]` with `enabled = true` and the defaults, commented with their Table A1 sources.

## 5. Record and replay

- [ ] 5.1 The welfare observer writes the evaluator's values into `affect_welfare`; `kaine/experiment/welfare_counts.py` knows the new keys; the range sweep bounds them.
- [ ] 5.2 `scripts/welfare_indicator_replay.py` replays archived `affect.state` and sleep events through the evaluator and the state machine with a fake sleep module and prints content-free stage times. Test on a synthetic record with a known crossing.
- [ ] 5.3 Run the replay on every readable developmental test-boot record and write the result (content-free) under `docs/records/validation/welfare-indicator-replay/`, before the validation boot.

## 6. Docs, review and checks

- [ ] 6.1 `docs/11-preservation.md` (the indicator response, its stages and notices), `docs/09-modules/sleep.md` (`welfare_rest`), `docs/17-research-data/README.md` (record fields).
- [ ] 6.2 Paper notes to REVISION-NOTES: §5.4 status, §6.5 tense and the D2 wording, Table A1 minimum span.
- [ ] 6.3 `openspec validate welfare-indicator-response --strict` passes.
- [ ] 6.4 Worker first-pass review, then the integrator's independent second review against the checklist in design.md before merge.
