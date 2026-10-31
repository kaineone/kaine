## Context

- The research gate (`kaine/cycle/research_gate.py`) refuses an unsupervised research boot with exit 5 unless preservation, the welfare response, logging, a dry preserve and revive round trip, encryption where required, and the individuation producer all hold. It runs once, synchronously, before the event loop starts.
- The unattended gate (`kaine/cycle/unattended_gate.py`) reuses that net for conditions 1 to 5 and 9 and adds condition 6, the supervisor, through `check_supervisor_condition` in `kaine/cycle/supervisor_selftest.py`: the section parses, `enabled` is true, `max_restart_attempts >= 1`, the escalation directory and the incident log directory are writable, and a scratch supervisor detects, freezes, snapshots, restarts and releases a synthetic probe within `selftest_timeout_s`. The self-test touches no entity module and no entity state (supervisor spec, "Supervisor selftest against a synthetic probe").
- The unattended spec already says: "A condition added to the research safety net SHALL become an unattended condition in the same change; the unattended gate SHALL NOT leave any research-net condition unmapped."
- History: the unattended gate and its supervisor condition (#189, #193, #196, #199); the study overlay's individuation fix (`2026-10-28-study-overlay-individuation`, #609), where the research gate gained a condition after the overlay was written and the first real study step refused with `failed:exit:5`. This change sets the overlay key in the same change as the gate condition so that cannot repeat.
- `config/kaine.toml` ships `[supervisor].enabled = false` with the comment "first boot is operator-supervised". A research run is not a first boot: the study gestates its own seed under the research gate with nobody present.

## Decisions

### D1. Reuse the unattended condition, do not write a second one

The research net calls `check_supervisor_condition(config["supervisor"])` and records its result under the key `supervisor_armed`, with the condition's reason. The pure half (`config_requirements`) reports the config-level part (enabled, ladder) so callers that verify a layered config without a self-test keep working; `evaluate_safety_net` adds the writable-path checks and the self-test.

Alternative considered: a lighter research-only check (enabled and ladder, no self-test). Rejected: the self-test is what shows the freeze and restart path works on this install, which is the reason to require the supervisor at all, and two predicates for one condition is the drift the unattended spec forbids.

### D2. The unattended gate takes condition 6 from the net

`SAFETY_NET_CONDITIONS` gains `"supervisor_armed": 6`. `evaluate_unattended_gate` builds condition 6 from the net's check and reason, and `built` accepts only 7 and 8. The self-test runs once per boot in either mode.

Alternative considered: keep condition 6 as a separate call in unattended mode and let the net run its own. Rejected: the self-test would run twice, and the two results could disagree on a slow host.

### D3. Loss of supervision escalates in research mode

The supervisor spec applies the loss-of-supervision escalation only to unattended runs. Once the research gate requires the supervisor, a research run that loses its supervisor task is running without a condition its gate demanded. The same escalation (final snapshot, shutdown of every module, `escalation.json`, caretaker notice) applies in research mode.

Alternative considered: log and continue. Rejected under the safety-over-convenience rule: a run that the gate would have refused to start should not continue unnoticed.

### D4. Study steps enable the supervisor; restarts are recorded, not disqualifying

`build_overlay` sets `[supervisor].enabled = true` and `[supervisor.incident_log].enabled = true` with `path` relative to the step directory, like the other safety-net keys it overrides. The runner reads `state/cycle/escalation.json` in the step directory after the child exits: when present, the outcome is `failed:supervisor` and the study halts for the operator, as every failed outcome does. A completed step records `supervisor_restarts`, the count of restart transitions in the step's incident log.

A module restart is part of the architecture's own fault handling and is in the research log (supervisor spec, "Run-level freeze annotation in the research event log"). It does not make a viewing inadmissible by itself; the analysis lists viewings with a restart beside the others.

Alternative considered: treat any restart as inadmissible and rerun the step from its start bundle. Rejected for now because it doubles entity boots for a recorded fault (the project minimizes boots on ethics grounds), but the analysis flag makes the choice reviewable.

### D5. Shipped study files

Every file under `config/studies/` sets `[supervisor].enabled = true`. A test walks the directory so a new study file without it fails.

## Risks

- The supervisor's heartbeat timeout (60 s) is generous by design; a module that degrades without hanging is not caught. This change does not alter detection.
- The self-test adds a few seconds to every research boot (bounded by `selftest_timeout_s`, 10 s).
- A supervisor restart during a viewing changes that module's state to its last snapshot. The step record and the research log show it.

## Migration and ordering

- No dependency. It is the first of the pre-study gate changes because `welfare-indicator-response` modifies the same gate requirement and must include this condition in its text.
- Before the study image is frozen and before the one supervised validation boot, which exercises the gate.
- Critical path (LLM-agent implementation): about 2 to 3 hours for code and tests, about 1 hour for review. Not on the study's longest path.

## Welfare and admissibility notes

- The supervisor's freeze stacks with the welfare freeze and never lifts it (entity-preservation spec, "A welfare-protective pause survives supervisor recovery"); its liveness stands down under any other freeze. Nothing here changes that.
- The change does not alter what the entity perceives or computes when no fault occurs. A restart restores a module from its last good snapshot, which the entity does experience as a gap; that is the reason restarts are recorded per step.
- Operator question: the shipped default stays off for operator-present boots. The operator should confirm that the reason for holding the supervisor off ("first boot is operator-supervised") does not apply to research runs, which this change assumes.
