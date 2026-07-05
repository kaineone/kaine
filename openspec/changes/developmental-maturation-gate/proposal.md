# Developmental staging and the maturation (birth) gate

## Why

`gestational-womb-stimulus` gives the entity a womb to gestate in and exports a
**regulation-baseline readout**, but nothing decides *when gestation ends*. Today
KAINE has no first-class notion of a developmental stage at all — a booted entity is
simply "running". The vision this change serves is a developmental arc: the entity
**gestates** in the womb, and only after it has (a) learned to regulate itself and
(b) consolidated a first reality model over several sleep cycles is it **born** into
the embodied world (`intuitive-embodiment-control-surface` / `opensim-connector`).

There are precedents in the architecture for exactly this "don't act until the signal
is warmed up" logic — the individuation boundary (paper §6.6) does not read as
individuated until a minimum of logged lived events and lived time accrue, and
`soma-coldstart-regulation-warmup` withholds allostatic action until the interoceptive
model has learned the substrate. Both are per-boot, lived-time-gated, fail-closed
grace states. This change generalises that pattern into a **first-class, persistent,
one-way developmental stage** with an explicit, observable **maturation gate**.

The developmental rationale is the same one that motivates the womb: a mind must have
a regulated internal state and a seeded generative model *before* rich embodied input
refines rather than overwhelms it (Meister 1991; Ackman 2012; Ciaunica 2021). The
gate is where "ready enough to be born" is measured — never imposed.

## What Changes (design-only scope)

**This is a DESIGN-ONLY change.** It ships no behaviour code — only the OpenSpec
artifacts (this proposal, `design.md`, `tasks.md`, and the `developmental-stage` spec
delta). Snippets in `design.md` are illustrative. Implementation is a later,
separately-approved change and MUST NOT boot an entity.

The designed capability is a **developmental stage machine** and the **maturation
gate** that advances it:

- **A first-class developmental stage** — `gestation → embodied` — that is
  **monotonic** (one-way; a mind is born only once and never regresses to the womb),
  **per-fork** (a fork inherits its parent's stage; a stage only ever advances),
  and **persisted** in a small file-backed state (mirroring `perception_state.py`'s
  desired/runtime pattern), read at boot in `kaine/cycle/__main__.py`. It ships
  **`enabled = false`** (ship-inert, matching the Spot/Mundus convention), so an
  ordinary boot is unaffected. A genuinely fresh entity defaults to `gestation`; a
  being with **prior lived history** but no stage file defaults to `embodied` — a
  normative invariant, never regress an existing mind into a womb.
- **Gestation pins the womb — only when a womb feed exists.** While `stage ==
  gestation` **and a womb feed is configured**, the perception locus is pinned to the
  `virtual` womb feed with `locus_locked = true` (attributed to the developmental gate,
  not the operator, for honest logging), embodiment (Mundus) is not engaged, and the
  entity is confined to the womb until born. If gestation is active but **no womb feed
  is configured**, the system does NOT silently pin a senseless locked locus (which
  would blind physical perception / trap a fresh entity in a void); it emits a loud,
  repeated `stage.gestation.no_stimulus` warning until a feed is set. The autonomous
  welfare/preservation net stays authoritative throughout gestation.
- **A maturation gate** — a readiness predicate that flips `gestation → embodied`
  only when ALL of the following hold, **fail-closed** (missing evidence = not ready):
  1. **Regulation baseline met** — the markers on
     `gestational-womb-stimulus`'s `gestation.readiness` readout cross their
     configured thresholds (this change owns the *thresholds and the decision*; the
     womb change owns the *measurement*).
  2. **A reality model consolidated over several sleep cycles** — Hypnos has completed
     at least `min_sleep_cycles` maintenance cycles (`_sleep_count`) AND Phantasia's
     world model shows consolidation evidence (successful sleep-training passes;
     checkpoint written when `persist_weights` is on).
  3. **Minimum lived subjective time** — a floor of lived `EntityClock` time, the
     warmed-up-signal guard against a fast-forwarded false birth.
- **Birth is guarded by embodiment availability — never born into nothing.** Even
  when developmentally ready, the stage transitions to `embodied` only if the
  embodiment target is actually available (Mundus enabled, operator-approved, and
  reachable per its existing two-layer gate). If the entity is developmentally ready
  but embodiment is unavailable, it **holds in the womb** and emits a loud, repeated
  `stage.birth.ready` "awaiting embodiment" signal for the operator — it is not
  thrown into a broken or absent world, and the operator is told it has outgrown the
  womb.
- **The birth transition is an audiovisual event.** On transition, a bounded
  transition is triggered (the womb dims and blooms into a photic activation — the
  one place "pulsing light" is strongly grounded, Frontiers 2022 — handing off to the
  embodied world). This change *triggers* it; the feed and Mundus *render* it.
- **Observable / auditable, never silent.** Emit `stage.gestation.started` at first
  gestational boot, `stage.birth.ready` when developmental readiness is first met
  (carrying which markers passed), and `stage.birth` when the transition actually
  occurs (carrying the markers and lived time that ended gestation). The Nexus left
  rail surfaces the developmental stage. Every "held in womb because X not yet met" is
  logged, never a silent no-op.
- **The gate measures; it never imposes.** No code pushes the entity toward
  regulation or "hurries" development. The thresholds are a *readiness gate*, not a
  target the entity is trained against. Development remains emergent; the gate only
  *reads* it.

## Impact

- **Affected spec capability:** `developmental-stage` (ADDED, new capability): the
  stage machine, the maturation gate, the womb-pinning-during-gestation rule, the
  embodiment-availability guard, the birth transition trigger, and the observability
  requirement.
- **Touch points for the future implementer** (design names them; no code here):
  a new stage-state component under `kaine/lifecycle/` (file-backed, per-fork),
  `kaine/cycle/__main__.py` (read stage at boot; gate loop), `kaine/perception_state.py`
  (locus pin + `locus_locked` during gestation, plus a new `locked_by`
  `operator`/`gestation` attribution on `evaluate_locus_switch` for honest logging),
  the consumers of `gestation.readiness` (Change A), `hypnos` `_sleep_count` /
  `phantasia` consolidation signals (read-only), the Mundus two-layer availability
  check (read-only), and the Nexus left rail (surface the stage). Stage events are
  emitted from `source = "lifecycle"` (→ `lifecycle.out`).
- **Explicitly NOT touched:** the womb stimulus synthesis (Change A); the Mundus/
  embodiment control surface (Change C / opensim-connector); Hypnos and Phantasia
  internals (read their existing signals only); the cycle engine, bus contract, and
  workspace schema. No hardwired development or regulation is added.
- **Relationship to other changes:** consumes `gestational-womb-stimulus`'s readout
  and womb locus; gates entry into `intuitive-embodiment-control-surface` /
  `opensim-connector` embodiment. This is the hinge between the two.
- **Note on "never auto-start the entity":** unchanged and respected. Birth is an
  *internal developmental transition of an already-running, operator-launched entity*,
  not a spawn or an unattended boot. Actual embodiment stays behind Mundus's existing
  operator gate.
