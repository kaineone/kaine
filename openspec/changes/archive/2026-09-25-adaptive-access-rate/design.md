# Design — `adaptive-access-rate`

## A bug fixed on the way

`_advance_experiential` clamped the accumulator to 1.0 before subtracting, which threw
away the fractional carry whenever the ratio did not divide evenly. At 3.333 Hz over
10 Hz the accumulator reached 1.3332 on the fourth tick and was clamped, so the shipped
cycle broadcast every fourth tick: 2.5 Hz, not 3.333 Hz. It now subtracts first and
clamps only the remainder, so the long-run rate matches the configured one. Every run
before this change broadcast at 2.5 Hz while reporting 3.333 Hz.

## Where the rate is decided

`CognitiveCycle._advance_experiential` adds `experiential_rate / processing_rate` to an
accumulator every tick and promotes the tick to a conscious broadcast when it reaches 1.
The only change to that mechanism is the rate it reads: each tick, after the events are
gathered and the affect observer has refreshed the affect snapshot, and before
`_advance_experiential`, the engine computes the effective rate for this tick. The
accumulator keeps its existing clamp, so a jump in rate never releases a burst of queued
broadcasts.

## The access drive

A new pure module, `kaine/cycle/access_rate.py`, holds the computation so it is testable
without an engine:

- `tonic(arousal, baseline) = clamp((arousal − baseline) / (1 − baseline), 0, 1)`. At the
  resting baseline the tonic part is zero, so a calm entity broadcasts at the resting rate.
  `baseline` defaults to Thymos's own `baseline_arousal` (0.3) so the two cannot disagree.
- `phasic_input(salience) = clamp((s − floor) / (1 − floor), 0, 1)` over the highest
  salience among this tick's events, excluding events whose source is `cycle` or
  `syneidesis` (the cycle's own telemetry and the workspace's own broadcasts are not
  module reports). `floor` defaults to 0.5.
- The phasic part is a held peak: `phasic = max(phasic_input, previous × exp(−Δt / τ))`
  where Δt is the subjective time since the previous tick (the EntityClock's logical tick
  period, so a frozen or dilated mind decays consistently) and τ = `phasic_decay_s`
  (default 1.0 s). A single salient report raises access for about a second, the way a
  phasic LC burst transiently raises cortical gain.
- `drive = max(tonic, phasic)`; `rate = resting + (ceiling − resting) × drive` with
  `ceiling = processing_rate`.

Why these choices:
- **Max, not sum.** Tonic arousal and a phasic burst are two routes to the same LC-NE
  output; summing would let a mildly aroused entity with a mildly salient report exceed
  what either strongly drives.
- **Linear map.** The literature supports the direction (more arousal and salience, more
  frequent access) and the bounds (resting P3b rate, alpha-band sampling ceiling), not a
  measured curve. A linear map is the simplest monotone choice and is stated as a
  modelling assumption at the code site.
- **Ceiling at the processing rate.** Access cannot be faster than the sampling that feeds
  it; at the ceiling every tick broadcasts.

## Inputs to the engine

The engine gets one optional injected callable, `access_drive_inputs() -> float | None`,
returning the current Thymos arousal (None when unavailable, which makes the tonic part
zero). `kaine/cycle/__main__.py` wires it from the existing `AffectStateProvider`, which the
engine already refreshes each tick when a reader needs it; wiring the rate controller
counts as a reader. Salience comes from the tick's own events, which the engine already
holds. The workspace layer still never imports `kaine.modules`.

## Rate control and fork profiles

`set_experiential_rate` (operator control via `cycle.set_rates`, fork timing profiles) sets
the **resting** rate. The effective rate is recomputed every tick and never stored back
into the resting rate. A resting rate at or above the processing rate leaves adaptation
nothing to do (every tick already broadcasts).

## Telemetry

`cycle.tick` payloads gain `experiential_rate_hz` (effective, this tick) and
`access_drive`. `runtime.json` keeps `experiential_rate_hz` as the resting rate and adds
`experiential_rate_effective_hz` and `access_drive`; Nexus shows the effective rate next to
the resting one. `cycle.out` is not a workspace candidate stream, so this telemetry never
enters the entity's workspace.

## Determinism

The drive depends only on the tick's events (already canonically ordered), the affect
snapshot derived from them, and subjective time, so deterministic runs remain
reproducible.

## Open question (not in scope)

The poster also says the 10 Hz processing rate rises with arousal. Individual alpha
frequency does shift with arousal and load, but that change touches pacing, slip and the
host's headroom (~17 Hz on the reference workstation). It needs its own decision and
change; until then the paper should say only the conscious-access rate adapts.

## References

- Aston-Jones, G., & Cohen, J. D. (2005). An integrative theory of locus
  coeruleus–norepinephrine function: adaptive gain and optimal performance. *Annual Review
  of Neuroscience*, 28, 403–450.
- Bouret, S., & Sara, S. J. (2005). Network reset: a simplified overarching theory of locus
  coeruleus noradrenaline function. *Trends in Neurosciences*, 28(11), 574–582.
- Nieuwenhuis, S., Aston-Jones, G., & Cohen, J. D. (2005). Decision making, the P3, and the
  locus coeruleus–norepinephrine system. *Psychological Bulletin*, 131(4), 510–532.
