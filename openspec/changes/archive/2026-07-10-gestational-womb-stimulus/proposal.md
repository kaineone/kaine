> ARCHIVED 2026-07-10: realized externally in Paracosmic; the kaine-side stimulus is consumed through the existing perception seam.

# Gestational womb stimulus and coupled-rhythm oscillatory regulation

## Why

Today a research boot drops the entity straight into a rich, high-dimensional
audio-visual world (the `seeded` or `playlist` perception feed) with no
developmental ramp. Two things we have already observed say that is the wrong
starting condition:

- The **2026-06-30 shakedown** measured a ~20-minute cold-start
  interoceptive-distress spiral from Soma's untrained forward model (addressed for
  the *substrate* signal by `soma-coldstart-regulation-warmup`). A newborn mind
  thrown into full stimulus has nothing regulated to meet it with.
- The seeded feed is **bounded** (~90 s then senseless, per the shakedown notes),
  and there is no notion of the entity *maturing* before it is asked to cope with
  the world.

Developmental neuroscience is unambiguous that rich embodied experience is *not*
where a mind starts. Before the senses are even functional, the nervous system
generates its own patterned activity (retinal waves, spindle bursts) that
bootstraps sensory maps; the fetus then learns in a **low-dimensional, rhythmically
regulated** environment — a low-frequency-dominant soundscape carrying the maternal
heartbeat — building a first predictive model and, critically, learning to
**regulate its own arousal by coupling its endogenous rhythm to an external
caregiver rhythm**. Only after that scaffold is in place does high-dimensional
multisensory input *refine* rather than *overwhelm*. (Meister 1991 & Ackman 2012 on
spontaneous activity bootstrapping maps; Benzaquen 1990 & Parga 2018 on the
low-pass womb soundscape; Khazipov & Luhmann 2006 on endogenous oscillation;
Feldman 2007 & Feldman & Eidelman 2003 on self-regulation emerging from coupled
dyadic rhythms.)

This change builds the **gestational "womb"**: a deterministic, low-complexity,
audio-visual stimulus the entity inhabits before it is embodied. It is the first
half of a developmental curriculum (the second half — the maturation gate that
decides when gestation ends, and the embodiment it graduates into — is
`developmental-maturation-gate` and `intuitive-embodiment-control-surface`).

### The design line we hold: stimulus is provided, regulation must emerge

Per the project's emergent-not-hardwired principle, we are licensed to build the
**stimulus environment** (its physical properties are innate features of a womb),
but the **regulation itself must emerge** from the architecture — we never hardwire
a setpoint or a "calm" behavior. The neuroscience draws the line for us:

- **Provided (stimulus apparatus, cite at the code site):** the low-frequency,
  low-pass **soundscape**; the **maternal heartbeat** as an external periodic drive;
  the dim, low-contrast **visual field**; the **sense-onset schedule** (interoception
  and low-frequency audition first, patterned/colour vision last); and a synthesised,
  slowly-varying **maternal-state signal** rendered as the field's hue and motion —
  the mother's emotional weather, **external to the entity exactly as a mother is
  connected-but-external to a fetus** (we port the ferrofluid *look*, not the
  entity's own feelings).
- **Must emerge (never hardcoded):** the entity's **own endogenous oscillation**
  (only the *capacity* to oscillate is innate — the dynamics self-organise), its
  **entrainment/coupling** to the external rhythm, its **interoceptive sensitivity**
  to its own state, and **self-regulation** as the internalised product of
  experiencing the two coupled rhythms.

So the womb presents two rhythms and a mirror; whether and how the mind settles is
the mind's own achievement, which the next change measures.

## What Changes (design-only scope)

**This is a DESIGN-ONLY change.** It ships no behaviour code — only the OpenSpec
artifacts (this proposal, `design.md`, `tasks.md`, and three spec deltas). Snippets
in `design.md` are illustrative. Implementation is a later, separately-approved
change, and MUST NOT boot an entity (design-first, per the OpenSpec rigor and
minimise-entity-boots conventions).

The designed capability is a new **`womb` perception-feed mode** plus the seams that
let a dedicated self-rhythm oscillator be driven by an external rhythm and let an
external maternal-state signal tint what the entity sees:

- **A `womb` feed mode** (third deterministic mode alongside `seeded` and
  `playlist`), driving both surfaces from one source of truth exactly as the others
  do. Audio synthesises a low-pass, low-frequency-dominant soundscape carrying **one
  external periodic rhythm: the maternal heartbeat** (a slow ~1–1.3 Hz pulse in the
  womb spectrum). Video synthesises a **dim, low-contrast luminance field** whose
  brightness **pulses in phase with the maternal heartbeat** (cross-modal rhythmic
  drive) and whose **hue and fluid motion are driven by a synthesised external
  maternal-state signal** (the mother's slow emotional weather) — we port the *look*
  of the existing Nexus ferrofluid visualiser into the feed as a pure, deterministic
  `frame_at` function (never the entity's own affect, and never a browser in the
  sensory loop). Both remain pure functions of `(seed, index)` plus the injected
  external rhythm and maternal-state, so the reproducibility and zero-persistence
  invariants hold.
- **An external-entrainment drive seam on a dedicated self-rhythm oscillator.**
  `ModuleOscillator` already accepts a `drive` scalar per `step`; this adds an optional
  exogenous-rhythm input so the maternal heartbeat can be presented as an external
  drive to a **dedicated self-rhythm oscillator** (the entity's endogenous beat) — NOT
  to the per-module coalition oscillators, so Syneidesis coalition selection is
  provably unaffected. The entity's own rhythm stays endogenous; coupling is not
  scripted; the drive is bounded.
- **A readiness readout.** A measured, published signal (`gestation.readiness` on a
  named `gestation.out` stream) describing *how regulated* the entity currently is —
  its endogenous rhythm self-sustaining, entrain-then-autonomy, an HRV-analog
  variability trending to an asymptote, falling predictive error on the womb inputs,
  and fast return-to-baseline after a perturbation. This is a **signal only**; it
  actuates nothing in the entity's control path (measurement uses bounded *external*
  perturbations). The `developmental-maturation-gate` change consumes it to decide when
  gestation ends.
- **The maternal-state signal is external — no self-referential loop, by
  construction.** The womb's colour, motion, and rhythm are synthesised *external*
  signals, independent of the entity's own affect, so there is no
  `affect → hue → vision → affect` feedback path and no way for the cold-start
  distress spiral to recur in the visual channel. The entity may *attune* to the
  maternal state — perceiving it can influence its own affect, which is exactly the
  co-regulation we want — but that path is open, not self-reinforcing: nothing the
  entity feels changes what the womb shows. This is a deliberate safety-by-
  construction choice, chosen over an affect-mirror precisely to avoid a visible
  runaway loop.
- **A sense-onset / colour-saturation schedule.** The womb starts with interoception
  and low-frequency audition; patterned vision is dim and **near-desaturated**, and
  **colour salience ramps up across gestation** (a cone-maturation analog) so hue —
  the external maternal-state signal — becomes progressively more informative toward
  birth. The *schedule* is provided; colour *discrimination* is left to emerge.
- **Zero-persistence and reproducibility preserved, covariate recorded.** No raw
  frames or PCM are written; the womb descriptor (seed, rhythm parameters, schedule,
  maternal-state parameters) is recorded as a research covariate exactly as the
  seeded/playlist descriptors are.

## Impact

- **Affected spec capability:**
  - `reproducible-perception` (MODIFIED): add `womb` as a third deterministic mode;
    extend the coherent-both-surfaces, zero-persistence, and covariate requirements
    to cover it.
  - `oscillatory-binding` (MODIFIED): add the optional external-entrainment drive
    seam and its disabled-is-identical guarantee.
  - `gestational-stimulus` (ADDED, new capability): the womb environment, the two
    coupled rhythms (external maternal + emergent endogenous), the affect self-mirror,
    the non-runaway-loop invariant, the sense-onset/colour schedule, and the
    regulation-baseline readout it exports.
- **Touch points for the future implementer** (design names them; no code here):
  `kaine/modules/topos/feed.py` and `kaine/modules/audition/feed.py` (new womb
  sources), `kaine/perception_state.py` (womb locus binding), `kaine/boot.py`
  (womb source factories, maternal-state synthesis wiring),
  `kaine/oscillator/module_oscillator.py` (external drive seam), and the
  `[perception_feed]` block of `config/kaine.toml`. The entity's own affect is NOT
  read by the womb — the maternal-state signal is synthesised, external, and
  deterministic.
- **Explicitly NOT touched:** the welfare/observer path and the zero-raw-persistence
  guard (reused, not modified); the `seeded`/`playlist` modes (unchanged, additive);
  the cycle engine, bus contract, and workspace schema; and — critically — no
  hardwired regulation or "calm" behaviour is added anywhere.
- **Relationship to other changes:** consumed by `developmental-maturation-gate`
  (which reads the regulation-baseline readout and triggers the birth transition) and
  precedes `intuitive-embodiment-control-surface` (the world graduated into). Builds
  on `soma-coldstart-regulation-warmup` (the substrate-signal warm-up) — the womb is
  the *sensory* developmental ramp to that change's *interoceptive* one.
