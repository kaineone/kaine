## 1. Research gate

- [x] 1.1 `evaluate_research_gate` takes `supervisor_armed`; `GateResult` gains `reasons: dict[str, str]`, filled for every failed check; `config_requirements` reports the config-level half (enabled, ladder); `evaluate_safety_net` calls `check_supervisor_condition` once and passes its result and reason. The refusal message names the condition and its reason. Tests in `tests/test_research_gate.py`: supervisor off, ladder zero, unwritable escalation path, failing self-test (a probe whose freeze never takes effect), passing net; each refuses or passes with the expected reason. The no-entity check applies to the supervisor self-test call only: during `check_supervisor_condition` no module under `kaine.modules` is newly imported (compare `sys.modules` before and after that call). The existing dry preserve→revive self-check, which builds a self-model and a registry in a scratch directory, is unchanged and outside this check.
- [x] 1.2 Mutation check: removing the supervisor term from the `ok` computation makes a test fail.

## 2. Unattended gate

- [x] 2.1 `SAFETY_NET_CONDITIONS` maps `supervisor_armed` to 6; `conditions_from_safety_net` uses `net.reasons` when present and its fixed table otherwise; `evaluate_unattended_gate` builds condition 6 from the net and accepts only 7 and 8 in `built`; `_evaluate_unattended_gate` no longer calls the self-test itself. Tests in `tests/test_unattended_gate.py`: the mapping test covers the new key; the self-test runs once per unattended boot (count calls through a stub); condition 6's reason equals the self-test's reason, not the table's.

## 3. Loss of supervision in research mode

- [x] 3.1 Both sites in `kaine/cycle/__main__.py` apply in research mode: `_run_until_stopped` (task never started or ended early) and the supervisor's `escalate_on_crash` argument. Tests: a research-mode cycle whose supervisor task raises escalates, preserves, shuts down and sends a caretaker notice; a research-mode supervisor whose `_poll_once` raises writes a final snapshot and `escalation.json` before the halt; an operator-present cycle does neither.
- [x] 3.2 Mutation check: restoring `escalate_on_crash=(ctx.supervision_mode == "unattended")` makes the poll-loop test fail.

- [x] 3.3 The welfare monitor is watched too: `_run_until_stopped` escalates through `Supervisor.escalate_welfare_monitor_lost` (module `welfare_monitor`) when the welfare response is enabled and its monitor was never built or started, its task ended, or its poll loop keeps raising (`poll_loop_failing`: three raising polls in a row and none returned for `distress_duration_s`); the caretaker gets `supervision_lost`; `status` names a lost welfare monitor. Tests in `tests/test_welfare_monitor_liveness.py` (each case, the real monitor's run loop, a monitor that ended the run itself, operator-present mode) and `tests/test_ignition_study_runner.py`.

- [x] 3.5 The welfare monitor's own bus reads (and its rest-request and record publishes) are bounded at 5 s; a read that does not answer raises `WelfareBusTimeout`, fails the poll and reaches the liveness escalation. Tests in `tests/test_welfare_monitor_liveness.py`: a bus that never answers fails the poll in warm-up and after it; the real run loop on that bus escalates; every bus read in the monitor goes through the bounded helper. An unbounded read and a timeout swallowed as a plain error each make a test fail.
- [x] 3.6 Repeated read failures on `interoception.out` or `welfare.out` (warm-up drain, distress read, gray-zone read) fail the poll on the third in a row (`_DISTRESS_READ_FAILURES_TO_FAIL_POLL`, justified at the code site); a successful read resets the count. Tests in `tests/test_welfare_monitor_liveness.py`: a bus that raises on every read fails the third poll and escalates through the real run loop (in warm-up and after); each stream alone fails the poll; one transient error and two-then-good are tolerated. Six mutants killed (no raise, each site uncounted, no tolerance, no reset).
- [x] 3.4 A hung welfare poll (one that never returns) is not escalated; design D3a gives the reason (no bound is clearly safe against a long preservation inside the poll).

## 4. Development run

- [x] 4.1 `build_overlay` enables the supervisor and its incident log with a step-relative path. Extend the merged-config test from `study-overlay-individuation` to assert every config-level gate requirement for every step kind.
- [x] 4.2 The runner records `failed:supervisor` when `escalation.json` exists and `supervisor_restarts` otherwise; `analysis.py` lists steps with restarts. Tests with a stand-in child that writes an escalation file and one that writes two restart transitions; a retried step whose previous attempt left an escalation file is not recorded as `failed:supervisor` once the boot has cleared it.
- [x] 4.3 Every `config/studies/*.toml` sets `[supervisor].enabled = true`; `tests/test_study_files_supervisor.py` walks the directory.

## 5. Docs and checks

- [x] 5.1 `docs/11-preservation.md` lists the supervisor among the research gate's conditions; the study chapter lists it among the overlay's safety keys; `docs/14-for-researchers.md` names `failed:supervisor`.
- [x] 5.2 `openspec validate research-gate-supervisor --strict` passes.
- [ ] 5.3 Lead review of the PR (gate and escalation paths sit next to the welfare net).
