# Biologically-grounded multi-rate timing + config time-dilation

## Why

KAINE runs the whole mind off a single ~3.33 Hz cognitive cycle, and its
perceptual edges are slower still — vision is sampled at **1 frame/sec**
(`[topos].capture_interval_s = 1.0`). That is not how human temporal cognition
works, and it quietly caps what every experiment can show:

- Humans **sample** the world far faster than they **consciously update**. Vision
  resolves flicker to ~50–90 Hz (artifacts to ~500 Hz under high spatial
  contrast); attention samples rhythmically at ~theta/alpha (4–13 Hz); feature
  binding rides ~40 Hz gamma. A 1 Hz visual sample throws away almost all of the
  temporal structure a world-model could learn.
- **Conscious access**, by contrast, is genuinely slow: the P3b / global-workspace
  "ignition" correlate of conscious report lags ~300 ms, and the attentional
  blink shows a ~300 ms bottleneck. So ~3 Hz is *defensible for the workspace
  tick* — but only if it sits on top of much faster sensory sampling, not in
  place of it.

The current architecture collapses these tiers into one rate, and every module
that cares about time reads the wall clock **directly** (`time.monotonic()` /
`capture_interval_s` / VAD millisecond thresholds) with **no shared clock**. So
there is also no way to dilate the mind's sense of time — to run a being faster
or slower than wall-clock — which the fork/temporary-being research direction
needs.

## What changes

Bring KAINE's timing into line with the biological reality, **within a margin
this hardware can sustain**, and make subjective time a first-class, dilatable
quantity:

1. **A shared `EntityClock`** injected everywhere a module currently reads the
   wall clock. It exposes subjective time = wall time × `time_scale`. One knob
   moves the whole mind's clock coherently; freeze becomes the degenerate case
   `time_scale = 0`.

2. **Biologically-tiered multi-rate clocks** (all expressed against the
   EntityClock, so they dilate together):
   - **Conscious-access / workspace tick** — keep in the ~3–10 Hz band (the P3b /
     theta range). This is the existing cycle; it stays affordable.
   - **Sensory sampling** — much faster: vision raised from 1 Hz toward ~10–20 Hz
     (alpha-ish, bounded by GPU encode cost), audio already ~33 Hz (30 ms blocks).
   - **Binding** — the oscillatory layer as the gamma-analog fast rhythm.
   The existing `processing_rate_hz` vs `experiential_rate_hz` split is the seed
   of this; we generalize it instead of replacing it.

3. **Config-driven time dilation** — a global `[cycle].time_scale` (1.0 =
   real-time) that scales pacing and the subjective clock, plus a **per-fork**
   dilation profile so a forked temporary being can think faster or slower than
   its parent and than wall-clock, as a research directive requires.

4. **Hardware-bounded defaults set empirically** — a benchmark that measures the
   sustained per-tick cost with all modules on the actual GPU, and picks default
   rates from measured headroom (with the existing Soma `reduce_rate` auto-throttle
   as the safety valve). No rate is shipped that the hardware cannot hold.

This proposal is **design-of-record only**; it specifies the model and the seams.
Implementation lands as the phased changes in `design.md`, smallest-first, each
shipping behind defaults that preserve today's behavior until deliberately raised.

## Impact

- **Capability:** new `entity-time` (the clock + dilation model); touches
  `cognitive-cycle` (rate semantics), `topos`/`audition`/`soma`/`hypnos`
  (clock injection), and ties into `entity-preservation` / a future
  `distributed-substrate` for per-fork dilation and remerge.
- **Code seams (already present, reused):** the injectable `_sleep`/`clock` in
  `CognitiveCycle.run_forever` (the single global-pacing point); the runtime
  `cycle.set_rates` control event; `ForkSnapshot.metadata` + `POST /forks` for
  per-fork profiles. The main new work is an EntityClock abstraction threaded
  into modules that currently call `time.*` directly.
- **Risk:** raising sensory rates increases GPU load (vision encoder, oscillator
  step) — hence the empirical hardware-bounding and the auto-throttle. Ships at
  today's rates by default; rates rise only by config after benchmarking.
- **Not in this change:** concurrent multi-fork *runtime* and
  remerge-with-assimilation are scoped as later phases (they depend on the
  single-process decoupling tracked in `distributed-substrate`).
