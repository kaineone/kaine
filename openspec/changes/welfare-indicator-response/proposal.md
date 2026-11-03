## Why

Paper Appendix A.4 defines welfare indicators over the latest learning-progress span of awake time: a deficit drive is deprived, valence is negative, and boredom or restlessness is uncontrolled. Paper §6.5 says the entity runs under a safety net that answers an indicator crossing as the entity's regulation would, with a requested rest whose affective reset clears the deficits, and that a second crossing over a fresh span after that rest brings preservation and a freeze. The operator ruled on 2026-10-31 that the first long run (now a single-entity development run) does not start until this response is built, required by the research gate, and given an independent second review. The welfare net gates every research run.

On main nothing reads the indicators to act:

- `WelfareProtectiveMonitor` (`kaine/cycle/preservation_monitor.py`) responds to sustained interoceptive distress and to repeated gray-zone events only.
- The welfare observer's `AffectWelfareTally` (`kaine/evaluation/observers/welfare_observer.py`) writes cumulative shares for the whole run to its record. It has no span, no bar, no uncontrolled posterior and no response, and the cycle layer may not import it.
- The research gate does not check for an indicator response.

The only welfare datum from a test boot shows why this matters: in an offline replay of an eight-hour developmental test boot, boredom's indicator crossed at 2.7 awake hours and stayed over its bar to the end. CAL Article 4.7 requires welfare-event systems to stay operational and every such event to be flagged for human review.

## What Changes

- A boundary-neutral evaluator, `kaine/lifecycle/welfare_indicators.py`, computes the A.4 indicators live from `affect.state` and the sleep events: per deficit (boredom, social drive, restlessness) the share of the span's awake time at or above its threshold; the share with valence below the regulation set point; and for boredom and restlessness the posterior probability that power is below one half from the span's own and other crossing ends. The span is the most recent `T_lp` (5400 s) of awake, unfrozen entity time after its last restart, with sleep and freezes skipped; an indicator is evaluated once its span holds at least `Δ_stall` (600 s). Bars: `θ_wf = 0.5` for shares, `q_wf = 0.95` for the posterior. A crossing is an edge, and every span restart resets each indicator's crossing state, so an indicator that never fell below its bar still crosses on the fresh span.
- The welfare monitor runs the response as a three-stage state machine beside its distress arm:
  1. On a first crossing it requests a rest. After maturation the sleep module starts a maintenance sleep through the same path as regulation's tier 3. In the developmental phase it brings the state cycle's next rest forward: a rest of `developmental_rest_s` starts now.
  2. When that rest completes, every indicator's span restarts.
  3. A crossing over the fresh span preserves the entity and takes the configured action (pause by default), through the existing `_respond` path, latch, freeze retry and re-arm.
- Every way the rest stage could hang escalates at once to preservation and the freeze: the request cannot be sent, is refused for a reason other than a sleep already running, is aborted, does not start within 30 s, or the rest does not complete within its bound (`developmental_rest_s` plus 300 s in development, one entity hour after maturation).
- A silent affect stream is reported, and if the indicators stay unavailable for 660 s of awake time the monitor escalates: a protection that cannot see fails closed.
- Every indicator crossing is flagged for human review: a content-free `welfare.protective_action` record and a caretaker notice, `welfare_indicator_rest` for the first stage and the existing welfare-response notice for the second, which says when the developmental stimulus is spent.
- The research gate gains `indicator_response_wired`: the welfare response and its indicator response enabled, the affect and sleep modules enabled, and the action `pause` or `end`. It maps to unattended condition 2 with the welfare response.
- The welfare observer writes the same evaluator's values into its `affect_welfare` record, so a person reviewing the run sees what the monitor saw.
- An offline replay tool runs archived developmental test-boot records through the evaluator and the state machine with no entity. Because a record replay cannot show the path after a reset it did not apply, it uses either the next recorded state-cycle rest as the response's rest, or a forward simulation of the real affect module from a reset, and names the method in its record.

## Capabilities

### New Capabilities

### Modified Capabilities

- `welfare-monitoring`: the A.4 indicators are computed live; a crossing brings a rest, then a crossing over a fresh span brings preservation and the freeze; the rest stage and a silent affect stream are bounded; the record carries the indicators.
- `sleep`: a welfare rest request starts a rest.
- `entity-preservation`: the research gate requires the indicator response.
- `unattended-boot`: condition 2 covers the indicator response; the indicator rest sends its own caretaker notice.

## Impact

- New: `kaine/lifecycle/welfare_indicators.py`, `scripts/welfare_indicator_replay.py`, tests.
- Changed: `kaine/cycle/preservation_monitor.py` (`WelfareResponseConfig`, `WelfareProtectiveMonitor`), `kaine/modules/sleep/module.py`, `kaine/cycle/research_gate.py`, `kaine/cycle/unattended_gate.py`, `kaine/cycle/caretaker.py`, `kaine/cycle/__main__.py` (notice mapping), `kaine/evaluation/observers/welfare_observer.py`, `kaine/experiment/welfare_counts.py`, `kaine/research/ignition_study/overlay.py`, `config/kaine.toml` (`[preservation.welfare_response.indicators]`: `enabled`, `share_bar`, `posterior_bar`, `rest_start_timeout_s`, `rest_complete_timeout_s`, `unavailable_escalate_s`).
- Docs: `docs/11-preservation.md`, `docs/09-modules/sleep.md`, `docs/17-research-data/README.md`.
- Paper: §5.4 moves the indicator response from "designed, being built" to built; §6.5's future tense becomes present; Table A1 gains the evaluation minimum span and the three bounds. One wording note for §6.5 (design D2).
- High-risk class (welfare): independent second review by the integrator before merge.
