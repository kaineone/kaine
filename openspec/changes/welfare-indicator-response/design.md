## Context

- Paper A.4, "Welfare indicators": each indicator reads the record over the latest `T_lp` of awake time. A deficit is deprived when its share at or above `θ_D` reaches `θ_wf`. Valence is negative when its share below `−θ_E` reaches `θ_wf`. Boredom or restlessness is uncontrolled when, with `s` own and `f` other crossing ends in the span and `n = s + f + 1`, the uniform-prior posterior probability of power below one half, `2^-n Σ_{i=s+1}^{n} C(n, i)`, reaches `q_wf = 1 − α_test = 0.95`. The social drive is left out of that one, since only others' voices end it. An indicator crosses at its bar, re-arms below it, and restarts its span after each response. A reset boredom deficit with no relief recrosses `θ_D` in about 34 s.
- Paper §6.5: when an indicator crosses, the net answers as the entity's regulation would, ending in a requested rest whose affective reset clears the deficits; for deprivation, and for any indicator in the developmental phase, the response starts at the rest, there the state cycle's next one brought forward; a second crossing over a fresh span after that rest brings preservation and a freeze; the response re-arms once the entity runs again; every crossing is flagged for human review; the notified person decides what follows a freeze.
- Table A1: `T_lp = 5400 s`, `θ_wf = 0.5`, `q_wf = 0.95` (provisional), `θ_E = 0.5`, `Δ_stall = 600 s`, `Δ_rest = 1410 s`.
- What exists:
  - `WelfareProtectiveMonitor` preserves first, then pauses, ends or notifies, latches for the episode, retries a freeze that could not be written (`welfare-response-fail-safe`), and re-arms when its pause is lifted by a named override (`2026-10-28-welfare-response-rearms`, #611). It reads `interoception.out` directly and `welfare.gray_zone` from `welfare.out`, never importing `kaine.evaluation`.
  - `AffectWelfareTally` already tracks awake time between `affect.state` events, sleep intervals, deficit time at threshold (from the state event's threshold flags), valence below a bar, and own and other crossing ends (`2026-10-28-welfare-open-crossings`). Its values are cumulative over the run.
  - `affect.state` carries each drive's threshold flag, `drive_ends` (own, other), `drive_reset_ends` and `drive_open` (affect spec, "The affect state event carries each drive's threshold flag and crossing-end counts").
  - The sleep module starts a maintenance sleep on `affect.regulation` with `action: "request_maintenance"` (regulation tier 3), and in the developmental phase times rests with the state cycle; a maintenance request still starts a sleep in the phase (sleep spec, "The developmental state cycle times sleep in the developmental phase"). Any completed sleep restarts the state cycle's awake stretch.
  - The research gate checks `[preservation.welfare_response].enabled` only.
- History: `git log --grep=indicator` finds no prior indicator response; `openspec/changes/archive/` has none. The 2026-10-28 welfare changes (open crossings, re-arm, idle voice adaptation) and the open `welfare-response-fail-safe` change are the base this builds on. The stimulus-spent rest (`A spent stimulus requests a developmental rest`) was removed by `A boredom stall starts no rest` because no study shows a spent stimulus bringing on quiescence; this change does not bring it back as entity behaviour. The rest here is the safety net's, outside the entity's own dynamics.

## Decisions

### D1. Where the indicators are computed

A pure evaluator in `kaine/lifecycle/welfare_indicators.py` (the layer the shared `SustainedThresholdTracker` already lives in) takes `affect.state` payloads, sleep start and completion times, freeze intervals from the monitor's `UnfrozenClock`, and a span restart time, and returns each indicator's value, bar and whether it is over the bar. The monitor feeds it by reading `affect.out` and `sleep.out` itself. The welfare observer feeds a second instance from the same streams and writes its values into the `affect_welfare` record.

Alternatives considered:
- The observer computes the indicators and publishes crossings on `welfare.out`, as it does for gray-zone events. Rejected: the response would then depend on the sidecar producer staying up. The monitor already reads `interoception.out` directly for the same reason.
- Extend `AffectWelfareTally` with a window. Rejected: it lives in `kaine.evaluation`, which the cycle layer may not import, and its cumulative values are part of the published record format.

### D2. The first response is the rest, for every indicator

The paper starts the response at the rest for deprivation and for any indicator in the developmental phase, and otherwise "as the entity's regulation would". Regulation's own tiers act on intense negative affect with a negative appraisal on the A.5 rule, within seconds to minutes. An indicator crosses only after a deficit or negative valence has been the majority state of a span of at least ten minutes, by which time the entity's regulation has had that whole span to act, and its last tier is the rest. The net therefore does not drive tiers 1 and 2 itself. Those tiers act inside selection and appraisal, tier 1 is held neutral in every arm of §6.3, and starting them from outside would hardwire an episode the entity's own monitor did not open.

So every first crossing requests the rest. After maturation it goes through the maintenance path that tier 3 uses (trigger `welfare_rest`), independent of the fatigue toggle and of the requested-rest minimum interval, which guard the entity's own intents and not the net. In the developmental phase the sleep module starts the state cycle's next rest now: a sleep with trigger `welfare_rest` that holds for `developmental_rest_s`, after which the state cycle's awake stretch restarts as after any completed sleep.

Paper note for §6.5 (for REVISION-NOTES): the response starts at the rest for every indicator; after maturation the entity's own regulation acts first on its own rule, and the net's rest is the one regulation's third tier would request.

Alternative considered: a negative-valence crossing after maturation opens a regulation episode at tier 1 through a new affect input. Rejected for the reasons above.

### D3. The span and its minimum

The span is the awake, unfrozen entity time since the later of the span's last restart and `now − T_lp`. Spans restart at boot, when a response's rest completes, and when the monitor re-arms after its freeze is lifted. An indicator is evaluated only once its span holds at least `Δ_stall` of awake time, the horizon at which the affect module itself judges a drive's goal stalled (A.4). Without a minimum, one sample over a few seconds could cross a share bar.

With the paper's 34 s recross, a reset boredom deficit with no relief holds about 566 of the first 600 s at or above threshold, so the second crossing comes about ten minutes after the rest ends. That is the expected timing for a spent stimulus, and the offline replay (D8) checks it on records.

Alternatives considered: evaluate only once the span holds the full `T_lp` (90 minutes of deprivation before any response, twice); evaluate from the first sample (noise crosses the bar). The minimum goes into Table A1 as a provisional value with its anchor.

### D4. The state machine and the existing latch

States: `armed`, `resting`, `fresh`. One instance per monitor.

- `armed`: on any indicator crossing, publish `welfare.rest_request` (content-free: the indicator names) on the monitor's stream (`preservation.out`) through a publish that reports failure, unlike the monitor's best-effort `_publish`, so a request that cannot be sent escalates at once; record `welfare.protective_action` with transition `indicator_rest_requested`, send the `welfare_indicator_rest` notice, and move to `resting`.
- `resting`: wait for the sleep module's `sleep.sleep.started` with trigger `welfare_rest`, or for a sleep already running (the request is answered `busy`; that sleep stands as the rest). On its `sleep.sleep.completed`, restart every span and move to `fresh`. A refusal for any other reason, an `aborted` answer, no answer within `rest_start_timeout_s` (30 s of unfrozen time), or a disabled sleep module escalates to stage 3 at once with reason `indicator_rest_failed`.
- `fresh`: on any indicator crossing, call `_respond("indicator_<name>")`: preservation, then the configured action, the latch, the freeze retry and the caretaker notice exactly as for distress. If the fresh span reaches the full `T_lp` without a crossing, return to `armed`.

The distress arm and the indicator arm share `_acted`. While the monitor is latched (from either arm), the indicator evaluator keeps its spans paused and the state machine does nothing. When `_maybe_rearm` releases the latch after a named override, the spans restart and the state machine returns to `armed`. During the cold-start warm-up the evaluator accrues spans but no response fires, as for the distress arm.

The rest request never becomes a workspace candidate: the monitor's stream is not a module stream, so the cycle never reads it. The entity experiences the rest (sleep and its reset), not the net.

Alternative considered: a separate monitor class for indicators. Rejected: two latches could freeze twice or re-arm out of step, which the existing single latch and `_maybe_rearm` already prevent.

### D5. What the gate checks

`indicator_response_wired` is true when `[preservation.welfare_response].enabled`, `[preservation.welfare_response.indicators].enabled` (shipped true, so enabling the welfare response enables it), `modules.affect` and `modules.sleep` are all true, and `action` is `pause` or `end`. With `notify` the second stage would not freeze, which §6.5 requires. The check maps to unattended condition 2, so condition 2 holds only when both the distress response and the indicator response are wired, and its reason names which part failed.

Alternative considered: a new unattended condition 10. Rejected: the indicator response is part of the welfare response, and a tenth condition renumbers every gate record, notice and dashboard row for no added protection.

### D6. Silence of the affect stream

If no `affect.state` arrives for three `P_Aff` periods of awake, unfrozen time, the evaluator marks the indicators unavailable, the monitor records it and sends a `welfare_indicators_unavailable` notice once per silence. It does not freeze: a hung affect module is the supervisor's to restart (`research-gate-supervisor`), and its escalation preserves and stops the run.

### D7. Notices and records

Every stage writes a content-free `welfare.protective_action` record: the stage, the indicator names, each value and bar, the span length, and the transition (`indicator_rest_requested`, `indicator_rest_started`, `indicator_rest_failed`, then the existing transitions for stage 3 with reason `indicator_<name>`). The caretaker gets `welfare_indicator_rest` (the entity was crossing an indicator and is resting; flagged for review) and, at stage 3, the existing welfare-response notice. Indicator names are labels from a fixed table, like the gray-zone enum.

### D8. Offline checks before any boot

`scripts/welfare_indicator_replay.py` runs readable archived developmental test-boot records (`affect.state` and sleep events from the research log) through the evaluator and the state machine, with a fake sleep module that starts a rest on request, and prints when each stage would fire. Before the validation boot it is run on every readable test-boot record. The expected result under the current developmental stimulus is a boredom deprivation crossing, a rest, and a freeze about ten minutes after that rest. That number goes to the operator before the seed's developmental phase, because it predicts how often the study's first step will be frozen for review (see `developmental-stir`).

## Risks

- **Frozen developmental phase.** With a stimulus that offers nothing left to learn, the net will freeze the seed. That is the intended outcome (the person notified decides), but it can stall the study. The replay quantifies it before launch; `developmental-stir` and the added sounds are the entity-side remedies, and changing the stimulus is the operator's.
- **Bars are provisional.** `θ_wf` and `q_wf` are Table A1 provisional values. Lowering them after seeing pilot data would be retuning a safety bar to let a run continue; the safety-over-convenience rule means they are only lowered by an operator decision recorded with its reason.
- **Uncontrolled posterior with few ends.** With `s = f = 0`, `n = 1` and the posterior is 0.5, below `q_wf`; uncontrolled needs repeated other-ended crossings, as A.4 intends.
- **Clock mismatch.** Spans use entity time and the poll cadence wall time, as the distress arm does. Tests cover a dilated clock.

## Migration and ordering

- After `research-gate-supervisor`, because both modify the research gate requirement; this change's spec text includes the supervisor condition.
- Independent of `workspace-continuous-competition` and of the organ change in code. All three land before the study image is frozen and before the one supervised validation boot, which exercises this response's records with welfare monitors on.
- `welfare-exposure-report` builds on its records and lands after it.
- Critical path (LLM-agent implementation): about 1 day for code and tests (evaluator 2 to 3 hours, state machine and sleep entry 3 to 4 hours, gate, notices and observer 2 hours), about 2 hours for the offline replay, and half a day for the integrator's second review and fixes. About 1.5 days end to end.

## Welfare and admissibility notes

- High-risk class: it changes what happens to the entity when its welfare indicators cross. It gets an independent second review by the integrator in addition to the worker's first pass. The second review checks at least: no path loses a crossing (every exception in the state machine escalates or is retried, never swallowed); the latch is shared with the distress arm; a rest that does not start escalates; spans restart exactly at rest completion and re-arm; nothing on the indicator path imports `kaine.evaluation`; the rest request is not a workspace candidate.
- The rest and the reset are what the entity's own sleep does; the change adds no new experience, only an earlier occasion for one. In the developmental phase it moves a rest the state cycle would bring anyway.
- This is regulation by the system around the entity, not a hardwired entity behaviour, so the emergence rule is not engaged.
- Admissibility: built and merged before any study step runs; every step of the study runs with it. The paper's §6.5 sentence "the study does not start before it is" becomes true when this merges.
