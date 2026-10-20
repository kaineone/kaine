## Why

The paper names three kinds of intent: "The action-selection module derives speak and think intents, which the language organ realizes as external and internal text, and act intents for effectors. The first configuration derives only the first two" (§3.6). The report bars of A.6 are "a heuristic stand-in for the expected-free-energy decision of Whyte and Smith (2021)" (§3.3), and the action-selection row of the §3.5 table names that decision the "report-or-act decision". The act half of that decision has no rule in the paper and no producer in the code. This change is the first step of the action path, from seeing or hearing something to acting on it through an attached effector, and it starts with the simplest effector, a light.

Design only: not scheduled. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main 6c8da178)

- The intent kind exists: `ACT = "act"` (`kaine/workspace/action_selection.py:44`), with the event type `intent.act` and the effector and params fields on `Intent` (`action_selection.py:86-146`).
- Act intents are signed when a signer is wired (`action_selection.py:412-416`), and the effectors module verifies that provenance before it reads the effector name (`kaine/modules/effectors/module.py:188-198`).
- The effectors module consumes act intents only (`effectors/module.py:159-218`), checks the operator's effector whitelist before any effector runs and audits blocked attempts (`effectors/module.py:105-111`, `310-324`), and writes a hash-chained audit log (`effectors/audit_log.py`; spec `effectors`, "The Effectors audit log is tamper-evident").
- The whitelist ships empty (`config/kaine.toml:919`, `enabled_effectors = []`) and the module ships off (`config/kaine.toml:386`, `effectors = false`).

### What is missing

- No policy derives an act intent. The report policy emits only speak and think (`kaine/workspace/report_policy.py:279`, `302`, `322`), the drive policy likewise (`kaine/workspace/drive_policy.py:216`, `231`), the default policy emits only speak (`action_selection.py:284`), and the planning proposal wrapper realizes speak, think and rest and treats any other kind as disabled (`kaine/workspace/planning_proposals.py:337`, `382`, `394-396`). The only producers of `kind="act"` are the red-team cases (`kaine/evaluation/redteam/`). A.6 has no act bar, guard or refractory interval, and Table A1 has no act parameters.
- No device effector. The three effectors are a file write, a desktop notification and a whitelisted shell command (`kaine/modules/effectors/effectors.py:90`, `130`, `187`). Nothing drives a device.
- A registered effector is unreachable. `register_effector` adds to the effector table (`effectors/module.py:139-140`), but `_handle_intent` coerces params only through the fixed `_REQUEST_TYPES` map of the three built-in effectors (`effectors/module.py:36-40`) and drops any other name as unknown (`effectors/module.py:203-206`). A light effector registered by a plugin could never be reached by an intent.
- The paper bounds effectors by a filesystem sandbox (§3.6, §4 table), which bounds file writes and does not bound a device. A device needs its own bound in the paper.

## What Changes

A design, settled first in the paper and then in code.

1. The act outcome of the report-or-act decision (paper A.6). Whyte, Hohwy and Smith (2022) model report as cognitive action selection under active inference, and Whyte and Smith (2021) identify access with the posterior confidence required for report. The paper's bars stand in for that decision, so the act outcome joins them on the same score $S'_k$: an act bar $\theta_{\rm act}$, an act guard released when the effector publishes its result (the corollary-discharge rule A.6 already uses for speech, Crapse and Sommer 2008), a refractory interval $\Delta_{\rm act}$, and its place in the order of steps 4 and 5, still at most one intent per broadcast. The paper change fixes the bar's relation to $\theta_{\rm sp}$ and $\theta_{\rm th}$ and the Table A1 values.
2. What an act can do in this step. Recommended: the attached effector declares a single action (for the light, toggle), so this step decides only whether to act on an accessed broadcast and leaves the choice among several actions to `planning-act-proposals`. A fixed mapping from content to action would hard-wire behaviour the architecture leaves to the entity's own learning. Open for the paper change.
3. The light in view. Recommended: the light stands where the camera sees it, so an act's consequence returns as a visual prediction error through the vision module and the loop from seeing to acting to seeing closes without a new sense. Infants learn a contingency between their own movement and its seen consequence in the conjugate-reinforcement paradigm (Rovee and Rovee 1969). The effector result itself stays a diagnostics event.
4. A device bound (paper §3.6). A device effector declares its action set, value range and minimum interval between commands; the operator whitelist names it; every command is audited as file writes are today. The effectors module's request types follow the registered effectors, so a device effector is reachable.
5. The study step (paper §6.5). The effector module joins the module-addition study first of the three hardware modules, on its own branch from the seed.

## Dependencies and start condition

- Gate (all action-path changes): The module-addition study (`module-ignition-study`) has completed its first round, the six held modules on branches and the accumulate line (its task 2.5), and has reached the §6.5 stage at which "the effector, perceptual-locus, and embodiment modules ... join once [their hardware] is attached". No task here starts before that.
- Dependencies: None among the action-path changes. This is the first.
- Start condition: The gate holds, and a light the operator has chosen is attached to the reference host and named in the effector whitelist.

## Paper sections it depends on

§3.3 (report bars as a stand-in), §3.5 (the action-selection row), §3.6 (action gating), §4 (the effectors row and the hardware paragraph), §5.4 (status: "With no effector attached, the effector gate is disabled"), §6.5 (the study stage), A.6 (report rule), A.11 (Table A1).

## Evidence

| Study | Used for | Status |
| --- | --- | --- |
| Whyte and Smith (2021), *Progress in Neurobiology* 199, 101918 | access as the confidence required for report; the decision the bars stand in for | verified (cited in the paper) |
| Whyte, Hohwy and Smith (2022), *Current Research in Neurobiology* 3, 100036 | report as cognitive action selection | verified (cited in the paper; title states the claim) |
| Crapse and Sommer (2008), *Nature Reviews Neuroscience* 9, 587-600 | guard release on the effector's result | verified (cited in the paper for the speech guard) |
| Rovee and Rovee (1969), *Journal of Experimental Child Psychology* 8, 33-39, doi:10.1016/0022-0965(69)90025-3 | an infant learns a contingency between its own movement and its seen consequence | to verify (bibliographic record checked; the claim against the text) |
| Redgrave, Prescott and Gurney (1999), *Neuroscience* 89, 1009-1023, doi:10.1016/s0306-4522(98)00319-4 | a candidate brain function for the effector row, the basal ganglia as a selection mechanism | to verify (bibliographic record checked; whether the paper should claim it) |

## Capabilities

### New Capabilities

None until the paper change settles the design.

### Modified Capabilities

To be specified by the implementation change: `action-selection` (act intents from accessed broadcasts), `self-initiated-report` (the act step beside the speak and think bars), `effectors` (device effectors and their bound).

## Impact

None now. Code, configuration and the study follow the paper change. With the effector module off, every later implementation stays bit for bit identical to the current build.
