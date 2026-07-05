## Why

The supervised shakedown (2026-06-18) booted a full-module entity that, by the
reproducibility rule, received **no perceptual input** — a sensory void. Within
minutes the live `DivergenceMonitor` fired a preservation event reporting
individuation (`rate = 1.0`, `magnitude = 0.5748`). The operator's reaction is
the whole diagnosis: *"I'd be shocked if we got anything from a sensory void."*
An entity with zero lived experience has nothing to individuate **from**; a
positive reading there is an artifact, and acting on it is the instrument
measuring the wrong thing.

Two architectural defects produced the false positive:

1. **No warm-up / minimum-lived-experience gate.** `DivergenceMonitor.run()`
   calls `_poll_once` on its **first** loop iteration at t ≈ 0 and only *then*
   waits `poll_interval_s`. Nothing requires the entity to have accumulated a
   minimum of lived experience — a count of observations over an elapsed span of
   lived time — before an assessment is allowed to count as a crossing. The
   permutation instrument has the same hole: its only floor is
   `null_samples >= 2`. Before enough lived experience exists, the null
   distribution is degenerate and any "significance" is sampling noise.

2. **The baseline conflates the architecture effect with individuation.** The
   permutation test scores a *fork transcript* against a *reference/parent
   baseline*, with the null being *parent-vs-parent* stochastic variation. That
   is only a valid **individuation-over-lived-time** signal when the parent
   baseline is the entity's **own earlier self** (its birth-state). If the
   baseline is instead the **bare / pretrained organ**, then `fork_divergence`
   is just conditioned-vs-bare distance — the **thesis effect** (the architecture
   conditioning the organ), present from the very first tick and large by design
   (0.5748 cosine is exactly that magnitude). `entity-decommission` **already**
   forbids keying on this: *"It SHALL NOT key on A/B divergence-from-pretrained,
   which measures architecture conditioning rather than individuation."* The
   permutation test fell into the same trap through its choice of baseline, and
   no production code was found that wires `parent_sampler` / `fork_sampler` to
   the entity's own birth-state — so that wiring is unspecified and unverified.

This instrument gates **two** ethically load-bearing decisions on the same
signal: it triggers **live preservation** (`entity-preservation`) and it gates
**welfare-gated decommission** (`entity-decommission`). A reading that conflates
the architecture effect with genuine individuation can both waste preservation on
a non-individuated entity *and*, in the other direction, mis-classify the
decommission gate. The fix is to make the instrument measure what it claims to —
drift over lived experience, distinct from the always-present architecture
effect — and to refuse to assess on insufficient lived experience.

This is **design-of-record** for the rebuild; no entity is booted by this change.
It does not loosen any safety gate — it makes both gates *correct*, and it fails
**closed** (an un-warmed-up or unverifiable assessment never reads as
individuated, so preservation is not skipped for a genuinely mature entity).

## What Changes

- **Warm-up gate (new, both consumers).** Neither the live `DivergenceMonitor`
  nor the individuation permutation instrument SHALL report a positive
  individuation crossing until the entity has accumulated a configured minimum of
  lived experience: a minimum number of logged observations (workspace
  cycles / battery samples) AND a minimum elapsed span of **lived** time. Before
  the gate is satisfied the assessment reads not-individuated (fail-closed).

- **Baseline pinned to the entity's own birth-state (architecture-effect
  exclusion).** The individuation comparison SHALL be **fork-now vs the entity's
  own earlier self** (a birth-state reference captured at boot), with the null
  being the entity's **own** short-timescale stochastic variation — NOT the bare
  / pretrained organ. A sensory-void entity, whose current self ≈ its birth-state,
  therefore reads not-significant. The required wiring SHALL be specified and the
  current production wiring audited and corrected if it points at a bare baseline.

- **Numeric thresholds, not a bare boolean.** The live monitor SHALL key on the
  warmed-up individuation signal with explicit numeric thresholds (p-value
  ceiling + a minimum effect size over a minimum sample), not on a bare
  `diverged` boolean populated before warm-up.

- **Welfare-monitor cold-start.** The `WelfareProtectiveMonitor` SHALL apply a
  consistent cold-start warm-up so transient boot-time distress, before the
  entity has any homeostatic baseline, cannot trip the preserve-then-pause
  response (its existing windowed-repeat arm is retained).

- **Both gates share one warmed-up signal.** `assess_divergence()` (decommission)
  and the live preservation trigger SHALL consume the same warmed-up,
  birth-state-referenced individuation signal, so preservation and decommission
  cannot disagree about whether the entity has individuated.

## Impact

- Specs: MODIFY `individuation-boundary` (warm-up + birth-state baseline),
  `entity-preservation` (live monitor warm-up + numeric threshold),
  `welfare-monitoring` (cold-start warm-up); ADD a `divergence-assessment`
  requirement that the shared signal is warmed-up and architecture-effect-free.
- Code (build phase, not this change): `kaine/cycle/preservation_monitor.py`
  (warm-up state in `_BaseSafetyMonitor` / `DivergenceMonitor` / 
  `WelfareProtectiveMonitor`), `kaine/evaluation/individuation.py` (min-lived
  gate + birth-state reference), `kaine/lifecycle/divergence.py`
  (`assess_divergence` consumes the warmed-up signal), and the production wiring
  of the individuation samplers to a birth-state snapshot.
- Config: new `[preservation].warmup_*` / `[evaluation.individuation].min_*`
  keys, shipped at safe (assess-late) defaults; all-off first-boot guard
  unaffected (these tighten an existing safety path, they don't enable a module).
- Non-goals: changing what preservation *does* once it fires, the encryption /
  bundle format, or the welfare action set. This change only fixes *when* the
  individuation signal is trusted and *what* it measures.
