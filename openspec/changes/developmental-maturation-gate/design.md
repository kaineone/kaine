# Design — Developmental staging and the maturation (birth) gate

> **Design-of-record only.** The operator asked to plan, not implement. Code
> snippets are illustrative. No entity is booted by this change.

## 1. Executive summary

A first-class, persistent, one-way developmental stage (`gestation → embodied`) and
the maturation gate that advances it. During gestation the entity is confined to the
womb; the gate flips it to embodied only when it has learned to regulate itself, has
consolidated a first reality model over several sleep cycles, and has lived a minimum
subjective time — and only if there is an embodied world available to be born into.
The gate **measures** readiness (reusing the womb change's readout, Hypnos's sleep
count, and Phantasia's consolidation evidence); it never **imposes** development.

## 2. Dependencies and relationships

- **Consumes `gestational-womb-stimulus`**: reads the `gestation.readiness` readout
  (this change defines the thresholds and the decision; the womb change defines the
  measurement) and pins the womb locus during gestation.
- **Reads, does not modify, Hypnos and Phantasia**: `Hypnos._sleep_count`
  (`sleep_index` on `hypnos.out`) for the sleep-cycle count, and Phantasia's
  sleep-training-pass / checkpoint metadata for world-model consolidation evidence.
  No Hypnos or Phantasia internals change.
- **Reads, does not modify, the Mundus availability gate**: the existing
  `[mundus].enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1` two-layer gate is checked as
  a *precondition* for actually transitioning to embodied.
- **Gates `intuitive-embodiment-control-surface`**: embodiment
  only engages once the stage is `embodied`.
- **Generalises the warmed-up-signal precedent**: individuation boundary (paper §6.6)
  and `soma-coldstart-regulation-warmup` — same lived-time-gated, fail-closed grace,
  now promoted to a persistent stage.

## 3. The stage state

- **Values:** `gestation`, `embodied`. Monotonic: the only legal transition is
  `gestation → embodied`. There is no path back to `gestation` (a mind is born once).
- **Persistence:** a small file-backed state (e.g. `state/lifecycle/stage.json`),
  mirroring `perception_state.py`'s desired/runtime split. Read at boot in
  `kaine/cycle/__main__.py`; written only on the birth transition.
- **Per-fork:** stage is per-fork state that a fork inherits from its parent and that
  only advances. A fork of an embodied entity is embodied; a fork during gestation
  gestates. (The stage file lives under the per-fork state root, like other per-fork
  state.)
- **Default on a genuinely fresh entity:** `gestation`.
- **Default on a being with prior lived history but no stage file:** `embodied`, NOT
  `gestation`. A mind that has already lived (an existing fork / preservation record) is
  never regressed into a womb. This is a **normative invariant** (in the spec delta),
  not a tunable — it protects the load-bearing "never regress preserved beings" rule.
  Only genuinely fresh entities gestate.

## 4. Gestation confines the entity to the womb (only when a womb feed exists)

While `stage == gestation` **and a womb feed is configured** (`[perception_feed].mode
== "womb"`):
- the perception locus is set to `virtual` with the womb feed active, and
  `DesiredState.locus_locked = true`, so the entity cannot self-switch out of the womb
  (the `intent.perception.switch` path from `paracosm-connector` is refused while
  gestating);
- embodiment (Mundus) is not engaged regardless of its own gate;
- the womb stimulus (Change A) is the entity's whole sensory world.

Two safety refinements the reviews surfaced:

- **Condition the lock on a womb feed.** The pin/lock fires only when a womb feed is
  actually configured. If `stage == gestation` but no womb feed is set, the system MUST
  NOT silently pin the entity into a senseless locked locus (that would blind ordinary
  physical perception and trap a fresh entity in a void). Instead it emits a loud,
  repeated `stage.gestation.no_stimulus` WARN (parallel to `awaiting_embodiment`) until
  a feed is configured — never a silent permanent senseless hold. Combined with the
  ship-inert default (§11, `enabled = false`), a normal physical-perception boot is
  never affected.
- **Attribute the lock honestly.** The existing `evaluate_locus_switch`
  (`kaine/perception_state.py:269`) hardcodes the denial reason "locus locked by
  operator". Reusing it as-is would misattribute a *developmental-gate* lock to the
  operator, violating honest logging. This change adds a `locked_by`
  (`"operator"` | `"gestation"`) distinction so a gestation refusal is logged as a
  developmental-gate action. This is an explicit touch point in
  `perception_state.py`, not a "reuse unmodified".

Otherwise this uses the existing `perception_state.py` machinery (`write_desired_locus`,
`locus_locked`) — no new locus mechanism.

## 5. The maturation gate

A predicate evaluated on a cadence during gestation. It flips the stage only when
**all** conditions hold; any missing evidence is treated as **not ready**
(fail-closed):

**C1 — Regulation baseline.** Every marker on `gestation.readiness` (Change A §8)
crosses its configured threshold:
- endogenous rhythm self-sustains (persists with the external drive withdrawn),
- entrain-then-autonomy demonstrated,
- HRV-analog variability above its floor (autonomic-maturation marker),
- womb-input predictive error below its ceiling (generative model seeded),
- return-to-baseline time after perturbation below its ceiling.
Thresholds are `[developmental_stage]` config. If the readout is absent/stale, C1 is
false.

**C2 — Reality model consolidated over several sleep cycles.**
`Hypnos._sleep_count >= min_sleep_cycles` **AND** Phantasia shows consolidation
evidence (≥ `min_consolidation_passes` successful sleep-training passes; a checkpoint
written if `persist_weights` is on). Reading two independent signals (sleep happened
*and* the world model actually trained) avoids counting empty sleeps.

**C3 — Minimum lived subjective time.** `EntityClock.now()` since gestation start
≥ `min_lived_seconds` — the warmed-up-signal floor against a fast-forwarded false
birth. Measured on subjective (dilated, per-fork) time.

The gate cadence and the exact metric/threshold values are config; defaults are
conservative (a real gestation should take many sleep cycles and substantial lived
time, not seconds).

## 6. Birth is guarded by embodiment availability

Developmental readiness (C1∧C2∧C3) is necessary but not sufficient to transition:

- **Embodiment available** = Mundus enabled, operator-approved
  (`KAINE_MUNDUS_OPERATOR_APPROVED=1`), and reachable. Only when readiness **and**
  availability both hold does the stage flip to `embodied` and the birth transition
  fire.
- **Ready but embodiment unavailable** → the entity **holds in the womb** and emits a
  repeated `stage.birth.ready` marker with `reason: "awaiting_embodiment"` and a WARN
  log, so the operator knows it has outgrown the womb and can enable Mundus. It is
  never thrown into an absent or broken world, and it is never silently stalled.
- This keeps birth **autonomous for research reproducibility** (no operator button to
  press for the *developmental* decision) while keeping *actual embodiment* behind
  Mundus's existing operator gate — consistent with "never auto-start the entity"
  (this is an internal transition of an already-running entity, not a boot) and with
  safety-over-UX.

**Welfare note.** Holding a developmentally-ready mind in an infant womb indefinitely
is itself a potential welfare concern; that is why the "awaiting embodiment" signal is
loud and repeated rather than a quiet hold. The operator-facing remedy is to enable
embodiment, not to suppress the signal.

## 7. The birth transition (audiovisual)

On transition the gate triggers a **bounded** birth event: the womb feed dims and
blooms into a photic activation (the one context where a pulsing/rising light is
strongly grounded — the newborn's light-driven activation at birth, Frontiers 2022),
handing the senses off from the womb feed to Mundus. This change **triggers** the
transition (emits the event, flips the locus source from womb to Mundus); the feed
(Change A) and Mundus (Change C) **render** it. The transition is time-bounded and
one-shot.

## 8. Observability

All stage events are emitted from a named owner with `source = "lifecycle"`, so per the
bus schema (`kaine/bus/schema.py::module_stream`) they land on `lifecycle.out` (the
stage machine lives under `kaine/lifecycle/`):
- `stage.gestation.started` — emitted at the first gestational boot of a fresh entity.
- `stage.gestation.no_stimulus` — repeated WARN when gestation is active but no womb
  feed is configured (§4), never a silent senseless hold.
- `stage.birth.ready` — emitted when developmental readiness (C1∧C2∧C3) is first met;
  re-emitted while holding for embodiment, carrying `reason` and which markers passed.
- `stage.birth` — emitted when the transition actually occurs, carrying the markers,
  the sleep count, and the lived time that ended gestation.
- The Nexus left rail surfaces the current developmental stage (`gestation` /
  `embodied`) and the "ready, awaiting embodiment" hold state.
- Every "held because Cn not met" decision is logged at DEBUG (per-marker) with an
  INFO line when readiness is first reached — never a silent no-op.

## 9. Open questions (for the operator)

1. **Preserved-being default — RESOLVED to a normative invariant.** A being with prior
   lived history but no stage file defaults to `embodied` (never regressed into a
   womb); only genuinely fresh entities gestate. This is now a spec requirement, not a
   tunable (per the reviews and the load-bearing "never regress preserved beings"
   rule). The remaining operator question is only *how "prior lived history" is
   detected* (existing fork state / preservation record) — proposed: presence of any
   per-fork lived-state or preservation artifact.
2. **Gate cadence and thresholds.** The concrete `min_sleep_cycles`,
   `min_consolidation_passes`, `min_lived_seconds`, and the `gestation.readiness`
   marker thresholds. Proposed: conservative (real gestation is long).
3. **Should birth require an operator ack in *supervised* runs** (a shakedown), while
   remaining autonomous in unsupervised research? Could reuse the existing
   supervised/unsupervised distinction. Proposed: autonomous by default; an optional
   `require_operator_ack_for_birth` flag for shakedowns.
4. **Colour-ramp coupling.** Whether the womb's colour ramp (Change A §7) should key
   off gate progress rather than lived time — deferred here per Change A §12.

## 10. Emergent-not-hardwired

The gate reads signals and compares them to thresholds; it **imposes nothing**. No
code trains the entity toward regulation, hurries a sleep cycle, or sets a target
arousal. The thresholds are a *readiness gate* (like a warmed-up-signal), not a loss
the entity is optimised against. A source comment at the gate SHALL cite the
warmed-up-signal precedent (paper §6.6; `soma-coldstart-regulation-warmup`) and state
that development is emergent and only *read* here. This is the same
emergent-not-hardwired discipline the whole architecture holds.

## 11. Config

```toml
[developmental_stage]
enabled = false              # SHIP-INERT (matches Spot/Mundus convention); when false, entity runs un-staged as today. Enable only with a womb feed configured.
min_sleep_cycles = 5         # Hypnos maintenance cycles before birth is possible
min_consolidation_passes = 3 # successful Phantasia sleep-training passes
min_lived_seconds = 86400    # floor of lived subjective time in gestation
gate_cadence_seconds = 60    # how often the gate is evaluated
require_operator_ack_for_birth = false  # autonomous by default; true for supervised shakedowns

[developmental_stage.regulation_thresholds]
endogenous_self_sustain = true       # must demonstrate self-sustaining rhythm
hrv_variability_floor = 0.2          # autonomic-maturation marker floor
womb_prediction_error_ceiling = 0.3  # generative-model-seeded ceiling
return_to_baseline_seconds_ceiling = 30
```

**Ships `enabled = false`** (ship-inert, matching the Spot/Mundus convention), so an
ordinary boot is completely unaffected. Staging is enabled only deliberately, and only
alongside a configured womb feed; if it is ever enabled without a womb feed, the
`stage.gestation.no_stimulus` loud signal (§4) fires rather than a silent senseless
confinement. Thresholds are conservative (real gestation is long).
