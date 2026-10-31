## Why

The module supervisor detects a hung or dead module, freezes the cycle, snapshots the last good state and restarts the module; past its restart limit it snapshots, shuts the cycle down and escalates. Only the unattended boot requires it (unattended condition 6). A research run, which also runs with no person present, starts with the supervisor off unless the operator config turns it on, and the shipped config and the study overlay leave it off. Paper §3.7 and §5.4 therefore describe the supervisor as running "when the operator enables it" (audit item M17, TRIAGE T1-5), and a module that hangs in the middle of a study viewing stays hung until a person looks.

The unattended gate already has the check, its self-test and its failure reasons. The research gate does not call them.

## What Changes

- The research safety net gains one condition, `supervisor_armed`: `[supervisor].enabled` is true, the restart ladder has at least one rung, the escalation path and the incident log are writable, and the supervisor's self-test passes within `selftest_timeout_s`. It is the same predicate as unattended condition 6, computed by the same function (`check_supervisor_condition`), before any entity module is built.
- The unattended gate takes condition 6 from the research net's result instead of running the self-test a second time. Every research-net check still maps to a numbered unattended condition.
- The research gate's refusal message names the supervisor condition and its reason; the exit code stays 5.
- Loss of supervision mid-run (the supervisor's task exits for any reason other than shutdown) escalates in research mode as it does in unattended mode: final snapshot, shutdown, `escalation.json`, caretaker notice.
- The module-ignition study overlay sets `[supervisor].enabled = true` and keeps the incident log on, with paths relative to the step's working directory. Every shipped study file under `config/studies/` sets `[supervisor].enabled = true`.
- The study runner names a step that ended in a supervisor escalation `failed:supervisor` and halts the study for the operator; a step with supervisor restarts that completed carries their count in its step record.
- `config/kaine.toml` keeps `[supervisor].enabled = false` for operator-present boots.

## Capabilities

### New Capabilities

### Modified Capabilities

- `entity-preservation`: the research boot gate requires the supervisor armed and self-tested.
- `unattended-boot`: condition 6 is the research net's supervisor check, evaluated once.
- `supervisor`: loss of supervision escalates in research mode too.
- `module-ignition-study`: every step runs the supervisor; a supervisor escalation is its own step outcome.
- `configuration-loading`: shipped study files enable the supervisor.

## Impact

- Code: `kaine/cycle/research_gate.py` (`evaluate_research_gate`, `config_requirements`, `evaluate_safety_net`, the message), `kaine/cycle/unattended_gate.py` (`SAFETY_NET_CONDITIONS`, `evaluate_unattended_gate`), `kaine/cycle/__main__.py` (`_evaluate_unattended_gate`, the supervision-loss escalation), `kaine/research/ignition_study/overlay.py`, `kaine/research/ignition_study/runner.py`, `config/studies/*.toml`.
- Tests: `tests/test_research_gate.py`, `tests/test_unattended_gate.py`, the study overlay tests, the runner outcome tests, a test over every shipped study file.
- Docs: `docs/11-preservation.md` (gate conditions), the study chapter, `docs/14-for-researchers.md`.
- Paper: §3.7 and §5.4 can say that research runs require the supervisor once this lands.
- No new dependency and no new configuration key.
