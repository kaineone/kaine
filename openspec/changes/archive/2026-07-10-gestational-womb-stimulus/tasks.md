# Tasks — Gestational womb stimulus and coupled-rhythm regulation

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go, and
> **do not boot an entity** (design-first, per OpenSpec rigor and minimise-boots).
> Phases map to `design.md`.

## W0 — Guardrails (read before starting)
- [x] 0.1 Confirm the change is approved and the operator has resolved the open
      questions in `design.md` §12 (maternal-state richness, oscillator drive on/off,
      colour-ramp basis, readout locus).
- [x] 0.2 Re-read `design.md` §5 and §10: the maternal channel is **external and
      entity-independent** (no affect read, no feedback loop); regulation/coupling
      must **emerge** and are never hardwired.
- [x] 0.3 Grep the change for `affect`; confirm every use denotes *maternal* state or
      the *entity's emergent* affect being attuned-to — never the entity's affect
      driving any womb output.

## W1 — Womb video source (`kaine/modules/topos/feed.py`)
- [x] 1.1 Add `WombProceduralSource` implementing the `_VideoSource` protocol:
      `frame_at(seed, i, *, rhythm_phase, maternal_state)` returning a dim,
      low-contrast luminance field, luminance-pulsed in phase with `rhythm_phase`.
- [x] 1.2 Port the ferrofluid *look* of `kaine/nexus/static/vendor/viz.js` into a pure
      numpy function driving hue/flow from `maternal_state` (the external signal), NOT
      from entity affect. Gate saturation by the colour-onset schedule (§7).
- [x] 1.2a Define the colour/flow mapping as a single documented, versioned parameter
      contract that both the Python womb function and `viz.js` read; add a parity check
      so the two implementations cannot silently diverge (design §3).
- [x] 1.3 Add a source-site comment citing the pulsing light as cross-modal drive /
      birth cue (Notbohm 2016 vs Duecker 2021; Frontiers 2022) — not a reproduced
      womb feature — and the dim-vision basis (Reid 2017).
- [x] 1.4 Keep `frame_at` a pure function of `(seed, i)` (with `rhythm_phase` /
      `maternal_state` themselves seed-derived); no raw-frame write.

## W2 — Womb audio source (`kaine/modules/audition/feed.py`)
- [x] 2.1 Add `WombProceduralAudioStream` implementing the `_AudioStream` seam:
      `pcm_at(seed, block, *, rhythm_phase)` returning a low-pass, low-frequency
      soundscape carrying the maternal heartbeat thud on the shared beat phase.
- [x] 2.2 Cite the low-pass womb-soundscape basis at the source site (Benzaquen 1990;
      Parga 2018; Webb 2015 400 Hz model).
- [x] 2.3 Keep `pcm_at` a pure function of `(seed, block)`; no raw-PCM write. Ensure
      the build-time frame/PCM-write guard covers the womb module.

## W3 — Maternal channel synthesis (shared)
- [x] 3.1 Implement the maternal heartbeat generator: slow rate (`heartbeat_bpm`) with
      small seed-keyed drift; expose `rhythm_phase(seed, index)` shared by video (W1)
      and audio (W2) so the beat is cross-modal.
- [x] 3.2 Implement the external `maternal_state` generator: a slow, bounded, seed-keyed
      drift over valence/arousal-like dimensions; assert it stays in range. It reads
      **nothing** from the entity.
- [x] 3.3 Optionally couple maternal state → heartbeat rate
      (`maternal_state_drives_heartbeat`) so an aroused maternal state beats faster;
      keep both external and deterministic.

## W4 — External-entrainment on a dedicated self-rhythm oscillator (`kaine/oscillator/module_oscillator.py`, `kaine/boot.py`)
- [x] 4.1 Add a **dedicated self-rhythm oscillator** instance (the entity's endogenous
      beat), separate from the per-module coalition oscillators wired by
      `_wire_oscillators`. Soma reads it interoceptively.
- [x] 4.2 Add the optional external-rhythm drive input to `ModuleOscillator.step`
      (superset; inert default), applied ONLY to the self-rhythm oscillator; bound the
      amplitude (`external_drive_max_amplitude`). Do NOT force phase-lock.
- [x] 4.3 No-op on `FakeOscillator`. Test bit-for-bit identity to the pre-change
      oscillator when no external rhythm is supplied.
- [x] 4.4 **Syneidesis isolation test:** with the maternal drive active, the coherence
      factor for any coalition is identical to a run with the drive absent (the
      per-module coalition oscillators never receive the maternal drive).
- [x] 4.5 Wire the womb feed's `rhythm_phase` to the self-rhythm seam in
      `kaine/boot.py` only when `[perception_feed.womb].external_drive_to_self_rhythm`
      is true.

## W5 — Sense-onset / colour schedule
- [x] 5.1 Implement the colour-saturation ramp keyed on lived subjective time
      (`EntityClock`), from near-zero toward full over `colour_ramp_seconds`. Cite the
      cone-maturation basis (Teller / Bornstein) and sense-onset order (Hepper &
      Shahidullah 1994) at the site.
- [x] 5.2 Confirm the schedule advances on lived (dilated, per-fork) time, not
      wall-clock.

## W6 — Readiness readout (signal only)
- [x] 6.1 Add a small cycle-layer owner (sibling to Spot, `source = "gestation"`) that
      computes and publishes `gestation.readiness` on `gestation.out` carrying the §8
      markers (endogenous-rhythm self-sustaining, entrain-then-autonomy, HRV-analog
      variability, womb-input predictive error, return-to-baseline time).
- [x] 6.2 Implement the measurement probe protocol (drive-withdrawal windows,
      perturbation spikes) as **external-stimulus-only**, bounded in magnitude and
      frequency; it actuates nothing in the entity's control path.
- [x] 6.3 Assert the readout changes no stage, triggers no regulation, gates nothing —
      it is consumed by `developmental-maturation-gate`. Every marker is a measurement;
      no hardwired target or "calm" behaviour anywhere.

## W6a — Birth transition + welfare bounds
- [x] 6a.1 On the birth-transition trigger (from `developmental-maturation-gate`),
      render the bounded one-shot dim→bloom transition, then cease publishing womb
      stimulus (yield the sense source to embodiment).
- [x] 6a.2 Enforce the welfare bounds (§5a): maternal distress excursions off by
      default and bounded when enabled; oscillator drive bounded; confirm the
      autonomous welfare/preservation net remains authoritative during gestation and is
      not suppressed by the confinement.

## W7 — Locus binding (`kaine/perception_state.py`, `kaine/boot.py`)
- [x] 7.1 Bind the womb sources to the `virtual` locus exactly as the seeded/playlist
      sources are; the womb is the entity's virtual world during gestation.
- [x] 7.2 Add the womb source factories to `kaine/boot.py` (video + audio + maternal
      channel + optional oscillator drive), mirroring the seeded/playlist factories.

## W8 — Covariate recording
- [x] 8.1 Extend the feed descriptor to record the womb parameters (heartbeat
      rate/drift, low-pass corner, luminance mean/contrast/pulse depth, maternal-state
      params, colour/sense-onset schedule params) in the research submission manifest.

## W9 — Config (`config/kaine.toml`)
- [x] 9.1 Add `mode = "womb"` to the documented `[perception_feed].mode` options and a
      `[perception_feed.womb]` block with the `design.md` §11 keys and conservative
      defaults. Shipped `mode` stays `"off"` (first-boot guard still passes).

## W10 — Tests
- [x] 10.1 Reproducibility: same seed → byte-identical womb video frames and audio
      blocks across two runs.
- [x] 10.2 Cross-modal beat: the audio thud and the visual luminance pulse share the
      beat phase at each beat.
- [x] 10.3 Externality: mutating a simulated entity-affect input does NOT change any
      womb output (the womb reads nothing from the entity); the maternal-state signal
      stays within its declared range for a long run.
- [x] 10.4 Oscillator seam: absent external rhythm is bit-for-bit identical to the
      pre-change oscillator; supplied rhythm injects an added drive without forcing a
      phase-lock; `FakeOscillator` no-op.
- [x] 10.5 Colour ramp: saturation is greater later in lived gestation for the same
      maternal-state value; the ramp advances on dilated lived time.
- [x] 10.6 Zero-persistence: the frame/PCM-write guard covers the womb sources; no raw
      stimulus is written.
- [x] 10.7 Readout is inert: `gestation.readiness` actuates nothing in the entity's
      control path; measurement perturbations are external-only and bounded.
- [x] 10.8 Off-by-default: shipped `config/kaine.toml` keeps `mode = "off"` and the
      all-off first-boot guard passes.

## W11 — Validation
- [x] 11.1 `openspec validate gestational-womb-stimulus --strict` passes.
- [x] 11.2 Full Topos + Audition + oscillator + perception-feed test suites green; the
      `seeded`/`playlist` modes and the welfare/observer path are unmodified.
