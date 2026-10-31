## 1. Research gate

- [ ] 1.1 `evaluate_research_gate` takes `supervisor_armed`; `GateResult` gains `reasons: dict[str, str]`, filled for every failed check; `config_requirements` reports the config-level half (enabled, ladder); `evaluate_safety_net` calls `check_supervisor_condition` once and passes its result and reason. The refusal message names the condition and its reason. Tests in `tests/test_research_gate.py`: supervisor off, ladder zero, unwritable escalation path, failing self-test (a probe whose freeze never takes effect), passing net; each refuses or passes with the expected reason. The no-entity check applies to the supervisor self-test call only: during `check_supervisor_condition` no module under `kaine.modules` is newly imported (compare `sys.modules` before and after that call). The existing dry preserve→revive self-check, which builds a self-model and a registry in a scratch directory, is unchanged and outside this check.
- [ ] 1.2 Mutation check: removing the supervisor term from the `ok` computation makes a test fail.

## 2. Unattended gate

- [ ] 2.1 `SAFETY_NET_CONDITIONS` maps `supervisor_armed` to 6; `conditions_from_safety_net` uses `net.reasons` when present and its fixed table otherwise; `evaluate_unattended_gate` builds condition 6 from the net and accepts only 7 and 8 in `built`; `_evaluate_unattended_gate` no longer calls the self-test itself. Tests in `tests/test_unattended_gate.py`: the mapping test covers the new key; the self-test runs once per unattended boot (count calls through a stub); condition 6's reason equals the self-test's reason, not the table's.

## 3. Loss of supervision in research mode

- [ ] 3.1 Both sites in `kaine/cycle/__main__.py` apply in research mode: `_run_until_stopped` (task never started or ended early) and the supervisor's `escalate_on_crash` argument. Tests: a research-mode cycle whose supervisor task raises escalates, preserves, shuts down and sends a caretaker notice; a research-mode supervisor whose `_poll_once` raises writes a final snapshot and `escalation.json` before the halt; an operator-present cycle does neither.
- [ ] 3.2 Mutation check: restoring `escalate_on_crash=(ctx.supervision_mode == "unattended")` makes the poll-loop test fail.

## 4. Development run

- [ ] 4.1 `build_overlay` enables the supervisor and its incident log with a step-relative path. Extend the merged-config test from `study-overlay-individuation` to assert every config-level gate requirement for every step kind.
- [ ] 4.2 The runner records `failed:supervisor` when `escalation.json` exists and `supervisor_restarts` otherwise; `analysis.py` lists steps with restarts. Tests with a stand-in child that writes an escalation file and one that writes two restart transitions; a retried step whose previous attempt left an escalation file is not recorded as `failed:supervisor` once the boot has cleared it.
- [ ] 4.3 Every `config/studies/*.toml` sets `[supervisor].enabled = true`; `tests/test_study_files_supervisor.py` walks the directory.

## 5. Docs and checks

- [ ] 5.1 `docs/11-preservation.md` lists the supervisor among the research gate's conditions; the study chapter lists it among the overlay's safety keys; `docs/14-for-researchers.md` names `failed:supervisor`.
- [ ] 5.2 `openspec validate research-gate-supervisor --strict` passes.
- [ ] 5.3 Lead review of the PR (gate and escalation paths sit next to the welfare net).
