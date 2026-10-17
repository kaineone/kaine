## Why

Paper A.6 step 1 (predictive-workspace-paper #47) releases the speak guard when the language organ publishes external speech and the think guard when it publishes internal speech, accessed or not, with the 48 s wall-clock timeout kept for a failed realization. The code released a guard only when the organ's output reached the coalition. The organ's utterances sit at priority 0.4, and the paper's reachability paragraph shows that a priority below about 0.43 never reaches access at any arousal, so in the first configuration that path never fires and every speak or think intent mutes its channel for the full 48 s. The fourth test boot (main a7dba0bd) showed it: the text arrived 0.5 to 2 s after each intent, the organ's events led the coalition 7 times and were never accessed, and nine accessed drive crossings that cleared the think bar fell inside a 48 s window and produced no think.

A producer knows its own command has run from a corollary discharge of that command, not by perceiving the output through attention (von Holst and Mittelstaedt 1950; Sperry 1950; Crapse and Sommer 2008). Speech production uses the same internal copy of the motor command (Houde and Nagarajan 2011; Hickok, Houde and Rong 2011). The organ's own published output is that copy.

## What Changes

- `ActionSelection.observe_own_output(event)` maps a `language` `external_speech` event to the policy's `mark_realized()` and an `internal_speech` event to its `mark_think_realized()`, when the policy has them. Any other event is ignored.
- The cycle engine forwards every organ speech event it gathers from the bus to `observe_own_output` on every tick, before the workspace selects and whether or not the event is selected or accessed.
- Every guarded policy has the matching hooks: `DefaultActionSelectionPolicy.mark_realized`, `DriveBiasedActionSelectionPolicy.mark_realized` and `mark_think_realized`, `SelfInitiatedReportPolicy` (already present), and `PlanningProposalSource`, which clears its own local guard and forwards to the wrapped policy, so it never holds a stale guard.
- The access-based release and the 48 s timeout stay as they are.

## Capabilities

### Modified Capabilities

- `action-selection`: the in-flight guards release on the organ's published output, accessed or not.

## Impact

- `kaine/workspace/action_selection.py`, `kaine/workspace/drive_policy.py`, `kaine/workspace/report_policy.py`, `kaine/workspace/planning_proposals.py`, `kaine/cycle/engine.py`, new `tests/test_guard_release_on_output.py`, `docs/08-cognitive-cycle/global-workspace.md`, `docs/02-architecture/README.md`, `docs/09-modules/language.md`.
- Behaviour: a think or speak intent mutes its channel only until the organ publishes the text (about 0.5 to 2 s in the test boot) instead of 48 s, so accessed content that clears a report bar after that produces an intent.
