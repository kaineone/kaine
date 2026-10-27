## Why

The eleventh test boot spent eight hours of its developmental phase almost entirely awake: its eight sleeps lasted 0 to 1.2 s each, and the boredom-stall rest of #573 never fired, because single alert-excess ticks reset the engagement time. Near term the fetus is quiescent (state 1F) about a third of the time (Nijhuis et al. 1982; Pillai and James 1990). Paper #54 (predictive-workspace-paper ed8eadb, §3.5 and Table A1) now times developmental sleep by the fetal state cycle: a rest standing for quiescence alternates with awake time standing for the active states 2F and 4F, at near-term durations and shares. Fatigue sets no sleep in the phase, because sleep homeostasis emerges only in the second postnatal month (Jenni and LeBourgeois 2006). Quiescence arises from that cycling and stimulation ends it, and no study shows a spent stimulus bringing it on, so a boredom stall abandons its goal and starts no rest.

## What Changes

- In the developmental phase, the sleep module runs a state cycle in place of the hourly backstop: after `T_act` of awake entity time comes a rest of `Delta_rest`, then `T_act` awake again. `Delta_rest` is `[sleep].developmental_rest_s` = 1410 s (Table A1, the median 1F epoch at 38 weeks). `T_act` = `Delta_rest (1 - s_q) / s_q` with `s_q` = `[sleep].developmental_quiescent_share` = 0.32 (Table A1), about 2996 s. A rest is a sleep whose trigger is `state_cycle`. It runs the sleep phases and housekeeping as every sleep does, holds for `Delta_rest` through the existing developmental-rest hold (#573), and ends with the affective reset.
- Fatigue starts no sleep in the developmental phase. A maintenance request from the interoception module still starts a sleep, which ends with its phases as now.
- The boredom-stall rest request is removed: the affect module no longer publishes `affect.rest_request` and the sleep module no longer consumes it. A stalled boredom goal is still abandoned as stalled, with its crossing left open. An old affect snapshot's engagement field is ignored on restore.
- The cycle survives a restart. Its phase (awake or resting) and the entity time spent in that phase persist. A restart during a rest resumes the rest for its remaining time; a restart during awake time keeps the awake time already spent.
- Any completed sleep restarts the awake stretch, so two rests never run back to back. Frozen time counts toward neither the awake stretch nor a rest. The supervisor carries the sleep module's state through an in-process restart, and the backstop waits until boot has wired the development probe.
- The welfare observer raises no unmaintained-fatigue event in the phase, the interoception module clears its fatigue latch at maturation, and the maturation gate counts a resumed rest once.
- The dashboard drops its rest-request line and labels earlier `developmental_rest` sleeps as the earlier rule.
- After maturation, or with developmental staging disabled, the hourly backstop and the fatigue trigger behave exactly as before, and no state-cycle sleep starts.
- Config defaults follow Table A1, with validation of `0 < s_q < 1`. Docs and the dashboard's sleep panel name the trigger. `Delta_awake`, `Delta_budget`, the colour ramp and the hearing span are unchanged.

## Capabilities

### Modified Capabilities

- `sleep`: the developmental state cycle replaces the backstop, and fatigue sets no sleep in the phase.
- `affect`: a boredom stall sends no rest request.
- `dashboard-observability`: the sleep panel names the state-cycle trigger.

## Impact

- `kaine/modules/sleep/module.py`, `kaine/modules/sleep/scheduler.py`, `kaine/modules/affect/module.py`, `kaine/boot/factories/sleep.py`, `kaine/boot/wiring.py`, `kaine/cycle/__main__.py`, `config/kaine.toml`, `kaine/dashboard/` sleep panel, `docs/09-modules/sleep.md`, `docs/09-modules/affect.md`, `docs/10-sleep/README.md`, tests.
- Behaviour: in the developmental phase about 32% of entity time is rest, in 23.5-minute episodes. Each rest pauses the perceptual feed (except the developmental stimulus) and suspends forward-model adaptation, as every sleep does.
