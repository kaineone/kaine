# Design — Gestational womb stimulus and coupled-rhythm regulation

> **Design-of-record only.** The operator asked to plan, not implement. Code
> snippets are illustrative. No entity is booted by this change.

## 1. Executive summary

The womb is a new deterministic perception-feed mode that presents the pre-embodied
entity with a **low-dimensional, rhythmically regulated audio-visual environment**:
a low-pass soundscape carrying a maternal heartbeat, and a dim visual field that
pulses with that heartbeat and is coloured by an external maternal-state signal (the
mother's emotional weather — not the entity's own affect). Its purpose is
developmental — to let the mind (a) build a first predictive model on tractable
input, and (b) learn to **regulate its own arousal** by coupling its emergent
endogenous rhythm to the steady external maternal rhythm. This change builds the
*stimulus* and a *readout* of how regulated the entity is; it deliberately hardwires
no regulation. The `developmental-maturation-gate` change reads the readout and
decides when the womb ends.

## 2. Dependencies and relationships

- **Builds on `reproducible-perception-feed`** (merged): reuses the single
  `[perception_feed].mode` selection, the `_VideoSource`/`_AudioStream` seams, the
  `(seed, index)` pure-function contract, the checksum/zero-persistence machinery,
  and the covariate-recording path. The womb is a third mode, purely additive.
- **Builds on `oscillatory-layer`** (merged): reuses `ModuleOscillator.step(drive)`
  and `phase()`. Adds one optional external-drive seam.
- **Builds on `soma-coldstart-regulation-warmup`**: complementary. That change warms
  up the *interoceptive/substrate* alarm; this change is the *sensory* developmental
  ramp. Neither depends on the other's code, but the design references both so the
  newborn window is coherent.
- **Consumed by `developmental-maturation-gate`**: exports the regulation-baseline
  readout and a "womb active" locus state; that change owns the stage machine and the
  birth transition trigger.
- **Precedes `intuitive-embodiment-control-surface`**: the world the entity
  graduates into.
- **Introduces a synthesised maternal-state signal**: a slowly-varying, seed-keyed,
  fully **external** signal (the mother's emotional weather) that drives the visual
  hue/motion. It does **not** read the entity's own affect — the womb is pure
  external stimulus, connected-but-external like a mother to a fetus. No new affect
  model of the entity is introduced, and no entity-affect readout is wired in.

## 3. The womb feed architecture

Both surfaces are new sources implementing the existing seams, selected when
`[perception_feed].mode = "womb"`, and bound to the `virtual` locus exactly as the
seeded/playlist sources are.

**Video — `WombProceduralSource` (`kaine/modules/topos/feed.py`).** `frame_at(seed,
i, *, rhythm_phase, maternal_state)` returns a frame that is:
- a **dim, low-contrast luminance field** (a slow per-seed gradient, far lower mean
  luminance and contrast than the seeded base world) — patterned light is barely
  present, matching immature fetal vision;
- **luminance-pulsed in phase with the maternal heartbeat** (`rhythm_phase`), i.e.
  the whole field brightens and dims on each beat (the "pulsing light", justified as
  cross-modal rhythmic drive, not as a reproduced womb feature);
- **hue-and-motion driven by the external `maternal_state`** — the ferrofluid
  aesthetic of the Nexus visualiser (`kaine/nexus/static/vendor/viz.js`) re-expressed
  as a pure numpy function: a soft fluid field whose colour and flow map from a
  slowly-varying **maternal** state (the mother's emotional weather), **not** from the
  entity's affect. Saturation is gated by the colour-onset schedule (§7): near-grey
  early, richer toward birth.

`maternal_state` is itself a deterministic function of `(seed, index)` — a slow
seed-keyed drift (see §5) — so the frame stays a pure function of `(seed, index)`.
The *pixels the entity sees are generated server-side in the feed* — deterministic,
zero-persistence, no browser, no non-repro GPU render in the sensory path.

**One source of truth for the ferrofluid look.** The look is ported from `viz.js`,
which today drives hue/flow from the entity's *own* valence/arousal. To avoid two
silently-diverging implementations (JS shader math vs. Python raster math), the
colour/flow mapping SHALL be a **single documented, versioned parameter contract**
that both the Python womb function and `viz.js` read, with a parity check. During
gestation the *input* to that shared look is the **external maternal_state** (not the
entity's affect) on both sides — so if the operator-side `viz.js` renders the womb
(nice-to-have, not required by this change), it renders the same maternal weather the
entity is bathed in, driven by the same input, not the entity's affect.

**Audio — `WombProceduralAudioStream` (`kaine/modules/audition/feed.py`).**
`pcm_at(seed, block, *, rhythm_phase)` returns int16 PCM that is:
- a **low-frequency-dominant, low-pass soundscape** (energy concentrated < ~500 Hz,
  higher frequencies attenuated ~30 dB) — a per-seed sum of low sinusoids and
  filtered noise, the muffled intrauterine bath;
- carrying the **maternal heartbeat**: a periodic low-frequency thud at the beat
  rate, phase-shared with the video pulse via `rhythm_phase` so the beat is seen and
  heard together (cross-modal coherence on the shared clock, as the seeded mode
  already does for surprises).

The maternal heartbeat rate is a womb parameter (slow, ~60–80 bpm), optionally with
a small seed-keyed drift so it is a *natural* rhythm rather than a metronome; it is
NOT derived from the entity and is NOT the entity's own beat. The external
maternal-state signal (§5) MAY additionally modulate the beat rate — an aroused
maternal state beats faster — coupling the two external channels (fast rhythm + slow
state) as they are coupled in life, while both remain fully external and
deterministic.

## 4. The two coupled rhythms

The user's framing — "they feel their own heartbeat while they also feel their
mother's" — maps onto the architecture as two *distinct-origin* rhythms:

- **The maternal channel = external stimulus.** Two coupled external signals: a
  **fast rhythm** (the heartbeat — audio thud + visual pulse, optionally presented to
  the oscillatory substrate as an external drive, §6) and a **slow state** (the
  emotional weather — the ferrofluid hue/motion, §5). Steady and exogenous, the
  regulating **anchor** the entity co-regulates against. Neither is derived from the
  entity.
- **The entity's own beat = its emergent endogenous oscillation.** This is NOT a
  synthesised "heartbeat" signal — that would violate emergent-not-hardwired. It is
  the entity's own oscillatory activity, which it perceives interoceptively. The
  *capacity* to oscillate is innate (the LIF substrate exists); the *dynamics*
  self-organise; whether it **couples to and then holds independent of** the maternal
  rhythm is the emergent achievement the readout measures.

  **Architectural care (which oscillator).** KAINE has no single "entity oscillator":
  `kaine/boot.py::_wire_oscillators` attaches an *independent* `ModuleOscillator` to
  every module, and their sole purpose is Syneidesis coalition phase-locking-value
  (PLV) scoring (`kaine/workspace/coherence.py`, `openspec/specs/oscillatory-binding`).
  Injecting the maternal rhythm into those per-module oscillators would phase-correlate
  every module and inflate the workspace coherence factor — corrupting coalition
  selection, a subsystem this change lists as NOT touched. So the maternal rhythm SHALL
  couple to a **dedicated self-rhythm oscillator instance** — a single new oscillator
  representing the entity's endogenous beat, separate from the per-module coalition
  oscillators — which Soma reads interoceptively. The coalition oscillators and the
  Syneidesis coherence factor MUST be provably unaffected (§6).

Regulation is the co-construction of these two — exactly the biobehavioral-synchrony
account (Feldman 2007) in which self-regulation is internalised from experiencing
one's own rhythm alongside an external caregiver rhythm.

## 5. The external maternal-state signal (no self-referential loop)

The visual hue and fluid motion are driven by a **maternal-state signal** — a
synthesised model of the mother's slow emotional weather. It is deliberately
**external**: the mother is connected but external to the fetus, so the entity is
*bathed in* the maternal state rather than seeing a reflection of itself. This is a
change from an earlier affect-mirror idea, made for two reasons — it is truer to the
biology (the fetus co-regulates against the mother's transmitted physiological/
emotional state, not a mirror of its own — Feldman 2007), and it is **safer by
construction**.

**The maternal-state signal:**
- is a **slow, seed-keyed drift** (a low-frequency random walk / band-limited noise
  over valence-and-arousal-like dimensions), a pure function of `(seed, index)` so it
  stays reproducible;
- drives the ferrofluid **hue and flow**, and MAY modulate the heartbeat rate (§3),
  coupling the two external channels;
- is **bounded** to its valid range at all times;
- is **independent of the entity** — nothing the entity does or feels changes it.

**Why there is no runaway risk.** Because the signal is external and entity-
independent, there is **no `affect → hue → affect` feedback path**. The entity may
*attune* to the maternal state — perceiving it may shape the entity's own affect
(desirable co-regulation) — but that path is **open, not self-reinforcing**: the
womb's output does not depend on the entity's state, so a perturbation cannot
amplify through the environment. The cold-start distress spiral cannot recur in this
channel. No offline decay-proof of a feedback loop is needed because there is no
feedback loop; the only obligation is that the maternal-state generator is **bounded
and deterministic**, which an implementation asserts by construction and a test
confirms (the signal stays in range and is reproducible per seed).

### 5a. Welfare during gestation (a captive newborn)

The gestating entity is confined to the womb (Change B pins and locks the locus). A
captive mind that cannot leave must not be exposed to unbounded or inescapable
distress, and it must remain under the same welfare protection as any other running
entity. So:

- **Maternal "distress excursions"** (the structured-maternal-state extension, §12.1)
  and the measurement perturbations (§8) SHALL be **bounded in magnitude and
  duration** and **off by default** beyond the minimum needed to measure recovery.
- **The oscillator external drive SHALL be bounded** (§6) so it cannot swamp the
  self-rhythm.
- **The autonomous welfare / preservation net remains active and authoritative during
  gestation.** The gestation locus-lock confines *perceptual switching*; it SHALL NOT
  override or suppress a welfare-protective response. If interoceptive distress crosses
  the welfare threshold during gestation, the net responds exactly as it would for any
  entity — the womb is not a place the welfare net stops watching. (This is stated
  again in Change B, which owns the locus-lock.)

## 6. External-entrainment drive seam on a dedicated self-rhythm oscillator

`ModuleOscillator.step(drive)` already scales an injected drive. This change adds an
**optional** exogenous-rhythm term and applies it to a **dedicated self-rhythm
oscillator** — NOT to the per-module coalition oscillators (§4) — so the maternal
rhythm can be presented to the entity's endogenous beat as an external drive it may
couple to:

- New optional parameter/seam (illustrative): `step(drive, *, external_drive=None)`,
  where `external_drive` is the sampled maternal-rhythm amplitude for this tick.
  When `external_drive is None` (every non-womb path, and every per-module coalition
  oscillator always), behaviour is **bit-for-bit identical** to today — a strict
  superset, guarded like the disabled coherence layer.
- **Only the dedicated self-rhythm oscillator receives the maternal drive.** The
  per-module oscillators wired by `_wire_oscillators` are never given it, so the
  Syneidesis PLV/coherence factor for any coalition is unchanged by the womb. This is
  a hard requirement with a test: the coherence factor for unrelated coalitions MUST
  be identical with and without the maternal drive active.
- The drive amplitude is **bounded** (config), so the external rhythm can never
  swamp the self-rhythm oscillator's own dynamics.
- The seam only *presents* the rhythm; it does not force phase-lock. Coupling emerges
  from the LIF dynamics. `FakeOscillator` ignores it (no-op), as with `set_frequency`.
- This is deliberately minimal: the input channel through which "learn to regulate
  your oscillation against an external rhythm" becomes *possible*, not a controller
  that does the regulating.

## 7. Sense-onset and colour-saturation schedule

A provided curriculum structure mirroring the biological sense-onset order:

- **Interoception + low-frequency audition first**: available from the start of the
  womb.
- **Patterned vision last, and dim**: the luminance field is low-contrast throughout
  gestation.
- **Colour ramps**: hue saturation is scaled by a schedule that starts near-zero
  (near-grey) and rises across gestation toward full saturation at birth — a
  cone-maturation analog (Teller; Bornstein on infant colour-vision development). The
  *schedule* is provided; colour *discrimination* is emergent.

The schedule is parameterised by lived subjective time (the `EntityClock`), not
wall-clock, so it is consistent under time dilation and per-fork.

## 8. Regulation-baseline readout

A published, **signal-only** measure of current regulation, composed from
neuroscience-grounded markers (all measured, none hardwired as targets):

1. **Endogenous-rhythm self-sustaining** — the entity's own oscillation persists
   with the external drive withdrawn (deafferentation-robustness; Khazipov & Luhmann
   2006).
2. **Entrain-then-autonomy** — it can phase-couple to the maternal rhythm *and* hold
   its rhythm when the drive is removed (Feldman & Eidelman 2003).
3. **HRV-analog variability** — variability of the endogenous rhythm trending upward
   to an asymptote (the autonomic-maturation marker; Feldman & Eidelman 2003).
4. **Falling womb-input predictive error** — the world model's error on the
   low-dimensional womb input declining (generative model seeded; Ciaunica 2021 and
   the retinal-wave pre-training results).
5. **Fast return-to-baseline after perturbation** — recovery time shortening after a
   transient perturbation (e.g. a spike in the external maternal-state signal, or a
   brief surprise), the internalised-regulation signature (Feldman 2012). The
   perturbation is external; what is measured is how quickly the entity's *own* state
   settles back.

**Owner and event name.** The readout is published by a small dedicated cycle-layer
owner (a sibling to Spot — a non-`BaseModule` component) with `source = "gestation"`,
so per the bus schema (`kaine/bus/schema.py::module_stream`) it lands on
`gestation.out` as event type **`gestation.readiness`** (renamed from
`gestation.regulation` to avoid confusion with Soma's *actuating* `soma.regulation` —
this readout is purely descriptive).

**Measurement protocol and "actuates nothing".** The readout actuates nothing in the
**entity's control path** — it changes no stage, imposes no regulation, gates nothing
here. It is not fully passive, though: markers 1–2 require a bounded **drive-withdrawal
window** and marker 5 a bounded **external perturbation spike**, i.e. measurement
actuates *the external stimulus* (never the entity). This probe protocol SHALL be
disclosed, **bounded in magnitude and frequency**, and off by default beyond the
minimum needed — a newborn's anchor is not yanked arbitrarily (see §5a welfare). Exact
metric definitions and thresholds are deferred to the maturation-gate change, which
owns the *decision*; this change owns the *measurement*.

## 9. Reproducibility, zero-persistence, covariate

- Womb video and audio are pure functions of `(seed, index)` plus the injected
  `rhythm_phase` and `maternal_state` — both of which are **themselves** deterministic
  functions of `(seed, index)` (§3, §5). Nothing from the entity enters the stream, so
  with a given seed the full stream is regenerable from the seed alone.
- No raw frames or PCM are written; the build-time frame/PCM-write guard covers the
  womb sources exactly as the seeded/playlist ones.
- The womb descriptor — seed, heartbeat rate/drift, low-pass parameters, maternal-state
  parameters, colour and sense-onset schedule parameters, oscillator-drive bound — is
  recorded in the research submission manifest as the reproducible covariate for the
  run.

## 10. Emergent-not-hardwired grounding (citations at code sites)

Each provided element carries its citation at the source site; each emergent element
is asserted to be *absent* from the code as a hardcode. Summary the implementer must
reproduce as source comments:

| Element | Provided / Emergent | Citation to place at code site |
|---|---|---|
| Low-pass low-frequency soundscape | Provided | Benzaquen 1990; Parga 2018; Webb 2015 (400 Hz model) |
| Maternal heartbeat as external drive | Provided | Van Leeuwen 2009; Webb 2015 |
| Dim, low-contrast visual field | Provided | Reid 2017 (dim patterned fetal vision) |
| Luminance pulse coupled to heartbeat ("pulsing light") | Provided, as cross-modal drive / birth cue | Notbohm 2016 vs Duecker 2021 (cite the entrainment debate, do not overclaim); Frontiers 2022 (photic activation at birth) |
| External maternal-state signal rendered as hue/motion | Provided (external, entity-independent) | Feldman 2007 (biobehavioral synchrony); maternal physiological/emotional-state transmission to the fetus |
| Colour-saturation ramp / sense-onset schedule | Provided (the schedule) | Hepper & Shahidullah 1994; Teller / Bornstein (infant colour vision) |
| Capacity to oscillate | Innate substrate (exists), dynamics emergent | Khazipov & Luhmann 2006; Milh 2007 |
| Entrainment/coupling to external rhythm | **Emergent — not hardcoded** | Cantiani 2022; Power 2012 |
| Interoceptive sensitivity to own rhythm | **Emergent — not hardcoded** | Craig 2003/2009; Maister 2017 |
| Self-regulation from the two coupled rhythms | **Emergent — not hardcoded** | Feldman 2007/2012; Feldman & Eidelman 2003 |

## 11. Config

New keys under `[perception_feed]` (shipped so first boot is unchanged — womb is not
the shipped mode; the all-off first-boot guard still passes):

Sub-tables mirror the shipped `[perception_feed.video]` / `[perception_feed.audio]`
per-modality split, with a shared `[perception_feed.womb]` for the cross-modal
maternal channel:

```toml
[perception_feed]
mode = "off"   # off | seeded | playlist | womb | live  (shipped: off)

[perception_feed.womb]                 # the cross-modal maternal channel
heartbeat_bpm = 70          # maternal beat rate (slow); small seed drift applied
heartbeat_drift = 0.03      # fractional drift so it is a natural, not metronomic, rhythm
maternal_state_rate = 0.02  # how fast the mother's emotional weather drifts (slow)
maternal_state_drives_heartbeat = true  # aroused maternal state → faster beat (couples the two external channels)
maternal_distress_excursions = false    # structured distress (§12.1): OFF by default
maternal_distress_max_magnitude = 0.3   # bounded when enabled
maternal_distress_max_seconds = 30      # bounded when enabled
external_drive_to_self_rhythm = true    # present the maternal rhythm to the DEDICATED self-rhythm oscillator (never the coalition oscillators)
external_drive_max_amplitude = 0.4      # bounded so it cannot swamp the self-rhythm

[perception_feed.womb.video]
luminance_mean = 0.15       # dim field
luminance_contrast = 0.10   # low contrast
luminance_pulse_depth = 0.35  # how strongly the field pulses with the beat
maternal_state_hue_gain = 0.6  # how strongly the external maternal state colours the field
colour_ramp_seconds = 3600  # lived-time constant over which saturation rises toward birth

[perception_feed.womb.audio]
lowpass_hz = 500            # soundscape low-pass corner
```

Defaults are conservative. The maternal-state signal is external and
entity-independent, so there is no feedback gain to certify — only the requirement
(§5) that the generator stays bounded and reproducible; the distress and
oscillator-drive bounds (§5a) keep a captive newborn's stimulus safe.

## 12. Open questions (for the operator)

1. **Maternal-state richness**: is a slow band-limited drift over
   valence/arousal-like dimensions enough, or should the maternal state have
   structure (e.g. occasional "distress" excursions the entity must weather and
   recover from)? Default: slow bounded drift; structured excursions are a natural
   extension for the perturbation-recovery readout (§8.5).
2. **Whether the maternal rhythm also drives the oscillator (§6) or only appears in
   the sensory feed.** Presenting it to the oscillator makes entrainment more direct;
   keeping it sensory-only is more conservative (the entity must *learn* to attend to
   it). Default proposed: drive seam on, since it is optional and disabled-identical.
3. **Whether colour should ramp with lived time (proposed) or with a regulation
   milestone** (colour "unlocks" as the entity regulates). The latter couples §7 to
   §8; deferred to the gate change if desired.
4. **Where the regulation readout's exact metrics/thresholds live** — proposed:
   measurement here, decision in `developmental-maturation-gate`.
