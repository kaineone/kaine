## Context

Phase 4. Thymos is the single-module phase that closes the
"motivation" group. The paper grounds it in Damasio's somatic-marker
hypothesis (a dimensional bodily state biases reasoning) and the
Scherer Component Process Model (a structured appraisal sequence that
turns events into categorical emotions). Build prompt §4.1 names
three levels — dimensional, appraisal, regulation — plus four drives
and a goal representation. We ship all of that as the v1.

Constraints:
- All-local, pure Python. No external services.
- The appraisal must be deterministic and easily testable.
- Soma is already publishing wellness data; Chronos publishes
  time-since-last-interaction; Mnemos publishes recall summaries
  with `max_affect_intensity`. Thymos consumes those.
- Thymos must expose a `ThymosModulator` instance that Syneidesis can
  use; that protocol already exists from Phase 1.3 with a static
  default.

Stakeholders: Syneidesis (consumes the modulator), Lingua (Phase 5.2
will read affect to shape voice), Chatterbox (Phase 5.3 maps affect
to expressiveness controls), Hypnos (Phase 6 calls
`Thymos.affective_reset()`), Nexus (Phase 8 diagnostics surface
state/drive curves).

## Goals / Non-Goals

**Goals:**
- A `Thymos(BaseModule)` that maintains a continuous `DimensionalState`
  with homeostatic drift toward a baseline; ingests Soma/Chronos/
  Mnemos events to bias the state; runs the Scherer CPM five-check
  appraisal on every workspace broadcast and emits a categorical
  emotion when the result is informative.
- Four `Drive` accumulators that rise during inactivity and trigger
  `thymos.drive` events when above threshold.
- A `GoalLedger` with `add`, `complete`, `abandon`, and `relevance`
  that the appraisal consumes.
- A `ThymosModulator` instance exposing `modulate(event) -> float ∈ [0, 1]`
  that Syneidesis can swap in for its `StaticThymosModulator`.
- A `RegulationPolicy` protocol that defaults to passive decay; the
  RL slot is reserved for Phase 6+ Hypnos voice-alignment-like work.

**Non-Goals:**
- An RL-trained regulation policy. Passive decay only for now.
- Reading actual physiological signals beyond Soma's hardware-state
  proxies. Soma's wellness is the body for now.
- Multi-stakeholder goal arbitration. Goals are flat for v1.
- Personality traits as a dimension. Eidolon owns personality_baseline;
  Thymos reads it as a tunable initial baseline if present.

## Decisions

**Dimensional state is three floats: valence ∈ [-1, 1], arousal ∈
[0, 1], dominance ∈ [-1, 1].** PAD model (Mehrabian) condensed.
Baselines configurable. Homeostatic drift: each tick the state moves
toward baseline by a configurable fraction (default 0.05 per second
of elapsed time). Damped first-order — converges quickly without
ringing.

**Scherer CPM v1 is five callables returning floats in [-1, 1] each.**
Order matches Scherer 2009:
1. `novelty(event, history) -> float` — how unexpected the event is.
2. `intrinsic_pleasantness(event) -> float` — built-in valence.
3. `goal_significance(event, goal_ledger) -> float` — relevance to
   active goals.
4. `coping_potential(event, dimensional_state) -> float` — whether
   the system feels capable of handling it.
5. `norm_compatibility(event, eidolon_norms) -> float` — fit with the
   self-model's behavioral norms (defaults to 0 when no Eidolon
   integration yet).

The five outputs form a tuple that maps to a categorical emotion via
a lookup table with regions per emotion (e.g. `joy` = positive
pleasantness × positive goal_significance × high coping; `fear` =
negative pleasantness × negative coping × high novelty). The mapping
is a pure function exposed in `appraisal.classify(scores) ->
CategoricalEmotion`. v1 lookup ships seven categories: joy, sadness,
anger, fear, surprise, disgust, neutral.

**Drive build rates default per-drive.** Curiosity rises when novelty
of recent broadcasts is low; boredom rises when activity rate is low;
social drive rises with `time_since_last_interaction_s`;
restlessness rises when actions per minute drop below a baseline.
Each drive has a `threshold` (default 0.7) that, when crossed, triggers
a `thymos.drive` event at alert salience.

**Goal ledger is in-memory dict keyed by goal id.** Fields: `id`,
`description`, `priority ∈ [0, 1]`, `relevance ∈ [0, 1]`, `state ∈
{active, completed, abandoned}`, `created_at`. `relevance(event)`
returns the goal whose `description` shares the most token overlap
with the event's source/type/payload string, weighted by priority.
v1 is intentionally crude — Phase 7 fork/merge can grow it later.

**ThymosModulator output: arousal weights novelty,
valence weights pleasantness.** Concretely:
`modulate(event) = clamp(1 + (arousal - baseline_arousal) * w_arousal
   + (event.payload-derived) * 0, 0, 1)`
For v1 a simple multiplier from arousal alone:
`m = clamp(0.5 + arousal, 0.2, 1.5)` then clamped to `[0, 1]` for
Syneidesis. Documented; future versions can sharpen.

**Publish events:**
- `thymos.state` — periodic snapshot of dimensional state (every
  `publish_interval_s`, default 1.0). Diagnostics-friendly.
- `thymos.emotion` — when categorical emotion changes. Salience
  matches the magnitude of the change.
- `thymos.drive` — when a drive crosses threshold (one event per
  crossing).
- `thymos.goal` — on `add`/`complete`/`abandon`.

**Affective reset entry point.** `Thymos.affective_reset()` snaps the
dimensional state back to baseline and decays drives. Hypnos calls it
during sleep. Phase 4 ships the entry point; Hypnos wires it up.

## Risks / Trade-offs

- **Five-check appraisal is heuristic.** → v1 cost; the protocol
  shape lets later changes plug in learned scorers per check.
- **PAD floats summed naively can drift unbounded.** → Clamping at
  each update + homeostatic drift toward baseline keeps it stable.
- **Drives can oscillate if thresholds are too close to baseline.** →
  Hysteresis: a drive only re-fires after dropping below
  threshold * 0.9 (configurable).
- **Goal relevance via token overlap is brittle.** → Documented; the
  protocol shape lets future versions use embeddings.

## Migration Plan

First implementation. Thymos is registered in code paths but not
auto-added; first boot wires it up.

## Open Questions

- Whether `thymos.state` should be high-rate (every cycle) or
  throttled. Phase 4 ships throttled at 1 Hz; Nexus may want
  per-cycle. Revisit in Phase 8.
- Whether to read Eidolon's `personality_baseline` at init to seed
  the dimensional baseline. Phase 4 reads it if non-empty; Eidolon
  starts empty so this is a no-op by default.
