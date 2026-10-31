## 1. Research gate

- [ ] 1.1 `evaluate_research_gate` takes `supervisor_armed` and its reason; `config_requirements` reports the config-level half (enabled, ladder); `evaluate_safety_net` calls `check_supervisor_condition` once and passes the result. The refusal message names the condition and its reason. Tests in `tests/test_research_gate.py`: supervisor off, ladder zero, unwritable escalation path, failing self-test (a probe whose freeze never takes effect), passing net; each refuses or passes with the expected reason, and no entity module is imported during the gate (assert on `sys.modules`).
- [ ] 1.2 Mutation check: removing the supervisor term from the `ok` computation makes a test fail.

## 2. Unattended gate

- [ ] 2.1 `SAFETY_NET_CONDITIONS` maps `supervisor_armed` to 6; `evaluate_unattended_gate` builds condition 6 from the net and accepts only 7 and 8 in `built`; `_evaluate_unattended_gate` no longer calls the self-test itself. Tests in `tests/test_unattended_gate.py`: the mapping test covers the new key; the self-test runs once per unattended boot (count calls through a stub); condition 6's reason equals the net's.

## 3. Loss of supervision in research mode

- [ ] 3.1 The supervision-loss escalation in `kaine/cycle/__main__.py` applies in research mode. Test: a research-mode cycle whose supervisor task raises escalates, preserves, shuts down and sends a caretaker notice; an operator-present cycle does not.

## 4. Study

- [ ] 4.1 `build_overlay` enables the supervisor and its incident log with a step-relative path. Extend the merged-config test from `study-overlay-individuation` to assert every config-level gate requirement for every step kind.
- [ ] 4.2 The runner records `failed:supervisor` when `escalation.json` exists and `supervisor_restarts` otherwise; `analysis.py` lists viewings with restarts. Tests with a stand-in child that writes an escalation file and one that writes two restart transitions.
- [ ] 4.3 Every `config/studies/*.toml` sets `[supervisor].enabled = true`; `tests/test_study_files_supervisor.py` walks the directory.

## 5. Docs and checks

- [ ] 5.1 `docs/11-preservation.md` lists the supervisor among the research gate's conditions; the study chapter lists it among the overlay's safety keys; `docs/14-for-researchers.md` names `failed:supervisor`.
- [ ] 5.2 `openspec validate research-gate-supervisor --strict` passes.
- [ ] 5.3 Lead review of the PR (gate and escalation paths sit next to the welfare net).
