# Welfare response trigger investigation — 2026-11-16

## Question

Which flag/control enables a maintenance rest (`welfare_rest`) in an unfrozen run
without mutating production state, and is a 1 hour (60 minute) test possible?

## Answer

No single environment flag enables the rest. The `welfare_rest` maintenance rest is
emitted by the sleep module only after the welfare response monitor publishes
`welfare.rest_request` on `preservation.out`. In the shipped configuration that
monitor is disabled, so enabling it is the control that matters.

### Controls found

- `KAINE_CYCLE_OPERATOR_PRESENT=1` (or `[cycle].supervision_mode = "operator"`):
  satisfies operator-supervised boot. It does **not** enable
  `[preservation.welfare_response]`; with it alone, no `welfare.rest_request`
  fires and no maintenance rest starts.
- `KAINE_RESEARCH_MODE=1` (or `[research].enabled = true`): replaces the
  operator-present requirement with the research safety-net gate. In research
  mode the welfare response must be wired, but research mode alone does not turn
  on a disabled `[preservation.welfare_response]`; the response still has to be
  enabled by configuration.
- `KAINE_CYCLE_UNATTENDED=1` (or `[cycle].supervision_mode = "unattended"`):
  unattended boot mode. Not a way to force a maintenance rest, and it is a
  configuration error together with research mode or operator presence.
- Temporary operator override (`config/kaine.operator.toml`, gitignored):
  - `[preservation.welfare_response] enabled = true`
  - `[preservation.welfare_response.indicators] enabled = true`
  This is the documented way to enable the monitor without editing committed
  `config/kaine.toml`. `action` remains `pause` (or `end`); a first welfare
  indicator crossing then requests a `welfare_rest` sleep, while a crossing
  over a fresh span preserves and pauses/ends.
- Scratch production-freeze lift, without mutating production state:
  `kaine.cycle.control override welfare` run with `KAINE_DATA_ROOT` pointed at a
  scratch clone. This lifts the `welfare` freeze only in that clone. Production
  `state/cycle/control.json` remains frozen.

Therefore, an unfrozen non-production run that can produce a maintenance rest
requires all of the following together: a scratch state clone with its welfare
freeze lifted, read-only access to the original `state/models`, the temporary
operator override enabling the welfare response and indicators, and a boot mode
that allows the run (operator-present mode for the documented validation
protocol). The production tree, committed config, tasks, and freeze remain
untouched.

### 1 hour test feasibility

Yes, a 60 minute test is possible and is the documented protocol for task 6.5:
run the cycle for a 3600 second wall window against the scratch clone using the
temporary override. The window is long enough to move past the 120 second welfare
warm-up and, if a welfare indicator crosses, to capture the requested
`welfare_rest` sleep. A developmental-phase completion is potentially measurable
within the window because that rest is held for `[sleep].developmental_rest_s`
plus 300 seconds (1710 seconds by shipped config).

Limits:
- There is no documented flag to force an indicator crossing. Whether a
  crossing occurs within the hour depends on entity evolution and warm-up; the
  1200 second interoception warm-up must finish first, and the affect indicator
  needs its learning-progress span and stall threshold.
- If `action = "pause"` and an indicator crosses, the clone freezes at that
  point. Further maintenance rests then require restarting the procedure,
  because the pause blocks the cycle.
- A matured maintenance sleep's completion bound is configured at 3600 seconds
  of unfrozen entity time. One wall-clock hour may not be sufficient for that
  bound unless entity time is accelerated, so a matured-bound measurement can
  require more than one hour.

## Conclusion

`welfare_rest` maintenance rest is enabled by a temporary operator override that
sets `[preservation.welfare_response].enabled = true` and
`[preservation.welfare_response.indicators].enabled = true`, run in a scratch
state clone whose `welfare` freeze has been lifted via
`kaine.cycle.control override welfare`; boot mode alone (operator-present,
research, or unattended) does not create it. A 60 minute test is possible and
specified, but it is not guaranteed to produce a matured-bound completion within
the hour.