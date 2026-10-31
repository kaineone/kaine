## Context

- The research gate (`kaine/cycle/research_gate.py`) refuses an unsupervised research boot with exit 5 unless preservation, the welfare response, logging, a dry preserve and revive round trip, encryption where required, and the individuation producer all hold. It runs once, synchronously, before the event loop starts. `GateResult` carries `checks: dict[str, bool]` and `failures: list[str]`, and no per-check reason.
- The unattended gate (`kaine/cycle/unattended_gate.py`) reuses that net for conditions 1 to 5 and 9 and adds condition 6, the supervisor, through `check_supervisor_condition` in `kaine/cycle/supervisor_selftest.py`: the section parses, `enabled` is true, `max_restart_attempts >= 1`, the escalation directory and the incident log directory are writable, and a scratch supervisor detects, freezes, snapshots, restarts and releases a synthetic probe within `selftest_timeout_s`. The self-test touches no entity module and no entity state (supervisor spec, "Supervisor selftest against a synthetic probe"). `conditions_from_safety_net` takes each condition's failure reason from a fixed per-number table.
- Loss of supervision is gated on unattended mode in two places in `kaine/cycle/__main__.py`:
  - `_run_until_stopped` (about line 3159) escalates when the supervisor task never started or ended early, only when `supervision_mode == "unattended"`;
  - the supervisor is built with `escalate_on_crash=(ctx.supervision_mode == "unattended")` (about line 2675). Through `Supervisor.run` (`kaine/cycle/supervisor.py`, about lines 760 to 773) this decides whether a crashed poll loop runs `escalate_supervision_lost` (final snapshot, shutdown, `escalation.json`) before it halts. In research mode today a crashed poll loop sets `escalated = True` and stops the run without a snapshot and without `escalation.json`.
- The unattended spec already says: "A condition added to the research safety net SHALL become an unattended condition in the same change; the unattended gate SHALL NOT leave any research-net condition unmapped."
- History: the unattended gate and its supervisor condition (#189, #193, #196, #199); the study overlay's individuation fix (`2026-10-28-study-overlay-individuation`, #609), where the research gate gained a condition after the overlay was written and the first real study step refused with `failed:exit:5`. This change sets the overlay key in the same change as the gate condition so that cannot repeat.
- `config/kaine.toml` ships `[supervisor].enabled = false` with the comment "first boot is operator-supervised". A research run is not a first boot: the development run gestates its entity under the research gate with nobody present.
- Scope (operator decision 2026-10-31): the module-ignition study becomes a single-entity development run. One entity is booted, develops, and is grown continuously; modules join it one boot at a time through the study runner. Every boot of that run is a research boot.

## Decisions

### D1. Reuse the unattended condition, do not write a second one

The research net calls `check_supervisor_condition(config["supervisor"])` and records its result under the key `supervisor_armed`. The pure half (`config_requirements`) reports the config-level part (enabled, ladder) so callers that verify a layered config without a self-test keep working; `evaluate_safety_net` adds the writable-path checks and the self-test.

`GateResult` gains `reasons: dict[str, str]`, the failure reason of each failed check (empty for a passing one). The research gate fills it for every check, and the supervisor's entry is the reason `check_supervisor_condition` returned ("not enabled", "no restart ladder", "escalation path not writable", "incident log not writable", or the self-test's reason).

Alternative considered: a lighter research-only check (enabled and ladder, no self-test). Rejected: the self-test is what shows the freeze and restart path works on this install, which is the reason to require the supervisor at all, and two predicates for one condition is the drift the unattended spec forbids.

### D2. The unattended gate takes condition 6 from the net

`SAFETY_NET_CONDITIONS` gains `"supervisor_armed": 6`. `conditions_from_safety_net` uses `net.reasons[key]` when the net gives one and falls back to its fixed table otherwise, so condition 6 carries the self-test's own reason. `evaluate_unattended_gate` builds condition 6 from the net, and `built` accepts only 7 and 8. The self-test runs once per boot in either mode.

Alternative considered: keep condition 6 as a separate call in unattended mode and let the net run its own. Rejected: the self-test would run twice, and the two results could disagree on a slow host.

### D3. Loss of supervision escalates in research mode, at both sites

Once the research gate requires the supervisor, a research run that loses it is running without a condition its gate demanded. Both sites change from `supervision_mode == "unattended"` to `supervision_mode in ("unattended", "research")`:

- `_run_until_stopped`: a supervisor task that never started or ended early escalates;
- `escalate_on_crash`: a crashed supervisor poll loop runs `escalate_supervision_lost` before it halts.

The escalation is the same in both modes: final snapshot, shutdown of every module, `escalation.json`, caretaker notice. Without the second site, a crashed poll loop in a research run would stop the entity unpreserved, and the runner's `failed:supervisor` outcome (D4) would never fire because no escalation file is written.

Alternative considered: log and continue. Rejected under the safety-over-convenience rule: a run that the gate would have refused to start should not continue unnoticed.

### D4. Each boot of the development run enables the supervisor; restarts are recorded

`build_overlay` sets `[supervisor].enabled = true` and `[supervisor.incident_log].enabled = true` with `path` relative to the step directory, like the other safety-net keys it overrides. This overlay is what the development run's boots take their configuration from.

The runner reads `state/cycle/escalation.json` in the step directory after the child exits: when present, the outcome is `failed:supervisor` and the run halts for the operator, as every failed outcome does. The cycle clears any stale escalation file at startup (`clear_escalation()` in the boot path), so a retried step cannot inherit the previous attempt's file and the "read after exit" rule only sees the current boot's escalation. A completed step records `supervisor_restarts`, the count of restart transitions in the step's incident log.

A module restart is part of the architecture's own fault handling and is in the research log (supervisor spec, "Run-level freeze annotation in the research event log"). It does not by itself invalidate a step; the analysis lists steps with a restart beside the others.

Alternative considered: treat any restart as disqualifying and rerun the step from its start bundle. Rejected: it adds entity boots for a recorded fault (the project minimizes boots on ethics grounds), and the analysis flag keeps the choice reviewable.

### D5. Shipped study files

Every file under `config/studies/` sets `[supervisor].enabled = true`, and a test walks the directory so a new study file without it fails. Those files are the workspace-mediation and feedback ablation configurations, which the development run does not use; the overlay (D4) is what matters for it. The rule keeps any research run selected through `KAINE_STUDY` inside the same gate.

## Risks

- The supervisor's heartbeat timeout (60 s) is generous by design; a module that degrades without hanging is not caught. This change does not alter detection. `welfare-indicator-response` does not rely on it alone for a silent affect stream.
- The self-test adds a few seconds to every research boot (bounded by `selftest_timeout_s`, 10 s).
- A supervisor restart during a boot changes that module's state to its last snapshot. The step record and the research log show it.

## Migration and ordering

- No dependency. It is the first of the pre-run gate changes because `welfare-indicator-response` modifies the same gate requirement and must include this condition in its text; they archive in that order.
- Before the development run's image is frozen and before its one supervised validation boot, which exercises the gate.
- Critical path (LLM-agent implementation): about 3 to 4 hours for code and tests (including the second escalation site), about 1 hour for review. Not on the run's longest path.

## Welfare and admissibility notes

- The supervisor's freeze stacks with the welfare freeze and never lifts it (entity-preservation spec, "A welfare-protective pause survives supervisor recovery"); its liveness stands down under any other freeze. Nothing here changes that.
- The change does not alter what the entity perceives or computes when no fault occurs. A restart restores a module from its last good snapshot, which the entity does experience as a gap; that is the reason restarts are recorded per step.
- Operator question: the shipped default stays off for operator-present boots. The operator should confirm that the reason for holding the supervisor off ("first boot is operator-supervised") does not apply to research runs, which this change assumes.
