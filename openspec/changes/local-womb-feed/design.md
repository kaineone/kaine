# Design — `local-womb-feed`

The womb's design is the archived `gestational-womb-stimulus/design.md`
(`openspec/changes/archive/2026-07-10-gestational-womb-stimulus/`), adopted as written:
the feed architecture (§3), the two coupled rhythms (§4), the external maternal
state (§5), welfare during gestation (§5a), the self-rhythm drive seam (§6), the
sense-onset and colour schedule (§7), the readiness readout (§8), reproducibility and
zero persistence (§9), the emergent-not-hardwired grounding with citations at code
sites (§10), and the config (§11). This document records only what differs.

## Providers and liveness

A womb provider supplies the womb. Two exist by design:

- **Local** (this change): the womb sources run inside KAINE's Topos and Audition,
  selected by `[perception_feed].mode = "womb"`. Before spawn, readiness uses the same
  discard-only probe the unattended gate uses for other feeds: read one frame and one
  audio block from the womb sources and drop them. While running, a fresh probe proves
  nothing (the sources are pure functions of the seed, so it passes even when the
  running producer has died). Instead the shared womb clock records each frame and
  audio block that actually reaches the senses, and a cycle-layer publisher emits the
  same `gestation.womb` presence event an external provider does (provider `local`),
  only while both surfaces are delivering.
- **External** (Paracosmic, later): the body adapter streams the womb through the
  perception seam and publishes a content-free presence event, `gestation.womb`
  (source `gestation`, stream `gestation.out`, payload `{provider, frame_index}`),
  at least once per second. Liveness is a presence event within a bounded window
  (default 3 s) on the Redis clock.

Presence is live only when at least two presence events from the expected provider
fall inside the window and their `frame_index` advances, so a stalled provider that
replays a cached event is not live. The whole window is read, not just the newest
entry, because `gestation.out` also carries the readiness readout.

`maturation-gate-liveness` 2.1 (womb before spawn) checks readiness
(`check_womb_ready`) and 2.2 (womb loss) checks presence (`check_womb_live`), both in
`kaine/lifecycle/womb_liveness.py`, and nothing else, so swapping the local provider
for Paracosmic changes config, not the gate.

## Single host

Everything the local provider computes is numpy on the CPU from `(seed, index)`:
no browser, no GPU renderer, no network service. The archived design's shared
ferrofluid parameter contract with `viz.js` is optional; the entity's pixels come from
the Python function only.

## Stream name

The readiness readout and the presence event both live on `gestation.out` (source
`gestation`), as the archived design specified. The gate runner's default readout
stream changes from `womb.out` to `gestation.out` in phase 3.

## Later: media in Paracosmic

The operator's design intent for Paracosmic: media play on in-world screens the
being may choose to watch or not, and its gaze is never fixed to them. The local
womb has no media; it is the gestation stimulus only.

## Phase 2: the self-rhythm oscillator

**Where it lives.** The self-rhythm oscillator is the entity's own endogenous beat, so
its state is part of the mind and is preserved, forked and revived with it. Preservation
captures module state (`serialize()`) only, so the oscillator lives inside a module:
**Soma**, which reads it interoceptively (archived design §4). Soma serializes it under
its own state. It is separate from the per-module coalition oscillator that
`_wire_oscillators` attaches for Syneidesis, which never receives the maternal drive.

**What it is.**
- `SelfRhythmOscillator` satisfies `OscillatorProtocol` (`step(drive)`, `phase()`,
  `set_frequency`, `serialize`, `deserialize`). It adds an optional keyword-only
  `external_drive` to its own `step` and an `amplitude()` accessor (the spread of the
  recent population spike rate).
- `OscillatorProtocol.step(drive)` is unchanged, so plugin oscillators never see the
  external drive.
- It is built by one boot factory, `make_self_rhythm_oscillator`, next to
  `make_oscillator`. A later wetware self-rhythm needs one more plugin oscillator
  territory there and nothing else. Nothing pluggable is built now: a maternal-rhythm
  stimulus on living tissue would need its own welfare review first.
- Without snnTorch there is no self-rhythm oscillator. Markers 1 to 3 below then cannot
  be measured, so C1 fails closed and the entity is never born on a host without it.
  Local gestation therefore requires the oscillator extra; `check_womb_ready` reports
  its absence.

**How it is driven.**
- **Cadence.** Soma's read tick (1 Hz by default) is far too slow to represent a
  maternal beat of about 1.2 Hz, whose pulse is only tens of milliseconds wide. Soma
  therefore steps the self-rhythm oscillator in its own small loop at
  `self_rhythm_step_hz` (default 20 Hz) of subjective time (the entity clock). The
  interoceptive feature slots are read from it at Soma's read tick.
- **Own drive.** Each step's own drive is Soma's latest interoceptive activity measure,
  held between reads: the same measure it gives its coalition oscillator.
- In `womb` mode with `external_drive_to_self_rhythm = true`, boot injects a
  maternal-drive provider into Soma. Each step adds `external_drive_max_amplitude` times
  the beat pulse **averaged over that step's interval** of womb time. A point sample at
  20 Hz would hit or miss a pulse tens of milliseconds wide and alias into noise;
  averaging is the honest low-pass. The drive is read from the shared womb clock, so
  the oscillator is driven by the same beat the entity sees and hears.
- The probe protocol (phase 3) may withdraw the drive (0.0) or raise it for a bounded
  moment.
- Without a provider the drive is `None` and the oscillator behaves exactly as without
  a womb.
- The drive only presents the rhythm. Coupling emerges from the LIF dynamics; nothing
  forces phase-lock (Feldman 2007; the entrainment debate, Notbohm 2016 vs Duecker
  2021, is cited at the site).

**Interoception.** Soma's feature vector stays 8 wide, the width the CL1 plugin's
wetware interoceptive model requires. The self-rhythm occupies the zero-padded slots:
slot 4 = sin(phase), slot 5 = cos(phase), slot 6 = amplitude, and slot 7 stays 0. The
sine/cosine pair avoids a jump where the phase wraps. Without a self-rhythm oscillator
the slots stay 0, identical to today.

**Coherence is untouched.** A test holds the Syneidesis coherence factor for any
coalition identical with the maternal drive on and off, given the same inputs.

## Phase 3: the readiness readout, the probe protocol and the birth transition

**Owner.** `GestationOwner` (`kaine/cycle/gestation.py`) is a cycle-layer component (a
sibling of Spot, not a module) with source `gestation`. It runs while staging is enabled,
the stage is `gestation` and the local womb is the provider. It:
- samples Soma's self-rhythm phase and amplitude every processing tick through the
  registry, and reads the raw forward-model `prediction_error` from Topos reports;
- controls the maternal-drive provider for the probe windows;
- publishes `gestation.readiness` on `gestation.out` every `readout_period_seconds`
  (default 60 s) with the payload `{"readout": {...}}`, using the marker keys the
  maturation gate's C1 reads.

It actuates nothing in the entity's control path. It never changes a stage, regulates
the entity, or gates anything.

**Markers.** Every marker is a measurement; none is a target.

1. `endogenous_self_sustain` (bool): during the latest completed withdrawal window, the
   self-rhythm amplitude stays at or above half its mean over the equal-length driven
   window just before it, and the population keeps spiking (Khazipov & Luhmann 2006).
2. `entrain_then_autonomy` (bool): during that driven window, the phase-locking value
   between the self-rhythm phase and the maternal beat phase (2π × `heartbeat_phase`)
   is at or above `entrainment_plv_floor` (default 0.5), and marker 1 holds for the
   withdrawal that follows (Feldman & Eidelman 2003).
3. `hrv_variability` (float): the coefficient of variation of the intervals between
   self-rhythm phase wraps over the last `hrv_window_seconds` (default 300 s). The trend
   across readouts is logged for research; the gate compares the level with its floor.
4. `womb_prediction_error` (float): the median raw Topos prediction error over the last
   readout period, divided by the median over this gestation's first full readout
   period. The first-period baseline is stored as a single number in
   `state/lifecycle/gestation_readout.json` so it survives restarts. It is a falling
   ratio, not a normalised salience signal: Topos's normalised error is relative to its
   own rolling mean and cannot fall over time by construction.
5. `return_to_baseline_seconds` (float): after the latest perturbation, the time until
   Soma's reported arousal is back within `baseline_epsilon` (default 0.05) of its
   median over the 60 s before the perturbation, capped at 300 s (Feldman 2012).

Until a marker has data, it is absent from the readout, and the gate fails closed on it.

**Probe protocol (bounded, disclosed, welfare-first).**
- **Withdrawal.** Every `withdrawal_period_seconds` (default 1800 s), the drive is set
  to 0.0 for `withdrawal_seconds` (default 20 s, hard maximum 30 s). The equal-length
  driven window before it is the comparison baseline.
- **Perturbation.** Every `perturbation_period_seconds` (default 3600 s), the drive is
  raised to `external_drive_max_amplitude` for `perturbation_seconds` (default 5 s,
  hard maximum 10 s) from its usual `baseline_drive_fraction` (default 0.5) of the
  maximum. It is never above the configured bound.
- Every probe starts and ends with a content-free `gestation.probe` event on
  `gestation.out` (`{kind, phase: "start"|"end", seconds}`), so research logs can
  exclude probe windows.
- No probe runs while the cycle is frozen by any holder, while a welfare-protective
  response is active, or in the first `readout_period_seconds` after boot. An active
  probe aborts, restoring the normal drive at once, when any of these begins.
- The hard maxima are enforced in code, not only in the defaults.
- Maternal distress excursions stay off; they are not built.

**Birth transition.** On the `stage.birth` event, the womb sources render the bounded,
one-shot transition (the dim field blooms into a photic activation over
`birth_transition_seconds`, default 5 s, with the soundscape fading). Then the womb stops
delivering and the presence publisher falls silent. The runner has already unlocked the
locus for the embodied world.

**The gate reads the readout over a window.** Once presence events share `gestation.out`
at 1 Hz or more, the newest entry is almost never the readout. The runner therefore
finds the newest `gestation.readiness` in the stream window
`[now − readout_max_age_cadences × gate_cadence_seconds, now]`, as
`womb_liveness` does for presence, and its default readout stream becomes
`gestation.out` (tasks 3.2 and 3.3).

**External providers.** For an external provider (Paracosmic), the maternal drive and the
probe windows have to come from the provider, which knows its own heartbeat. Until one
exists, an external womb has no readout, so C1 fails closed and no birth happens. That is
honest: the gate cannot judge regulation it cannot measure.
