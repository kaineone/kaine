# Tasks — Developmental staging and the maturation (birth) gate

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go, and
> **do not boot an entity**. Phases map to `design.md`. Depends on
> `gestational-womb-stimulus` (the `gestation.readiness` readout + womb locus).

## W0 — Guardrails (read before starting)
- [ ] 0.1 Confirm approval and that the operator has resolved `design.md` §9 (preserved-
      being default stage, thresholds, supervised-ack, colour-ramp coupling).
- [ ] 0.2 Re-read `design.md` §5/§6/§10: the gate is **fail-closed**, birth is guarded
      by **embodiment availability**, and the gate **measures, never imposes**.

## W1 — Stage state (`kaine/lifecycle/`)
- [ ] 1.1 Add a file-backed developmental-stage component (`state/lifecycle/stage.json`,
      per-fork) mirroring `perception_state.py`'s read/write pattern; values
      `gestation` / `embodied`; only-advances invariant enforced in code.
- [ ] 1.2 Read the stage at boot in `kaine/cycle/__main__.py`; write only on the birth
      transition. Confirm the stage file lives under the per-fork state root so forks
      inherit it.
- [ ] 1.3 Enforce the preserved-being invariant (NORMATIVE, not a tunable): a being with
      prior lived history (existing fork / preservation record) but no stage file
      defaults to `embodied`, never `gestation`; only a genuinely fresh entity gestates.

## W2 — Gestation womb-pinning (`kaine/perception_state.py`, boot)
- [ ] 2.1 While `stage == gestation` **AND a womb feed is configured**
      (`[perception_feed].mode == "womb"`), pin locus to `virtual` womb and set
      `locus_locked = true` via the existing `write_desired_locus`. Do not engage Mundus.
- [ ] 2.1a If `stage == gestation` but NO womb feed is configured, do NOT silently pin a
      senseless locked locus; emit a repeated `stage.gestation.no_stimulus` WARN until a
      feed is configured.
- [ ] 2.1b Add a `locked_by` (`"operator"` | `"gestation"`) distinction to
      `DesiredState` / `evaluate_locus_switch` (`kaine/perception_state.py:269`) so a
      gestation refusal is logged as a developmental-gate action, not an operator lock
      (honest attribution). This is an explicit touch point, not reuse-unmodified.
- [ ] 2.2 Refuse `intent.perception.switch` while gestating (the entity cannot leave the
      womb until born), logged as a gestation-gate action.
- [ ] 2.3 Confirm the autonomous welfare/preservation net stays active and authoritative
      during gestation; the locus-lock never suppresses a welfare-protective response.

## W3 — Maturation gate (`kaine/cycle/__main__.py` or a lifecycle gate component)
- [ ] 3.1 Implement the readiness predicate C1∧C2∧C3 (design §5), fail-closed on missing
      or stale evidence:
      - C1: read `gestation.readiness` markers vs `[developmental_stage.regulation_thresholds]`.
      - C2: `Hypnos._sleep_count >= min_sleep_cycles` AND Phantasia consolidation
        evidence (`>= min_consolidation_passes` successful training passes).
      - C3: lived `EntityClock` time since gestation start `>= min_lived_seconds`.
- [ ] 3.2 Evaluate on `gate_cadence_seconds`; log each unmet condition (DEBUG) and an
      INFO line when readiness is first reached.
- [ ] 3.3 Add a source comment citing the warmed-up-signal precedent (paper §6.6;
      `soma-coldstart-regulation-warmup`) and stating development is emergent / only read.

## W4 — Embodiment-availability guard + birth (`design.md` §6/§7)
- [ ] 4.1 Check embodiment availability (Mundus `enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1`
      + reachable) as a precondition to transition.
- [ ] 4.2 On readiness ∧ availability: flip stage to `embodied`, write the stage file,
      trigger the bounded one-shot birth transition (emit event; switch locus source
      from womb to Mundus).
- [ ] 4.3 On readiness ∧ ¬availability: hold in womb; emit repeated `stage.birth.ready`
      `{reason:"awaiting_embodiment"}` + WARN log. Never stall silently; never birth into
      an absent world.
- [ ] 4.4 Optional `require_operator_ack_for_birth` (supervised shakedown): when true,
      readiness ∧ availability additionally awaits an operator ack before flipping.

## W5 — Observability (`kaine/lifecycle/` owner, Nexus)
- [ ] 5.1 Emit stage events from `source = "lifecycle"` (→ `lifecycle.out`):
      `stage.gestation.started`, `stage.gestation.no_stimulus`, `stage.birth.ready`
      (with passed markers + reason), and `stage.birth` (with ending markers, sleep
      count, lived time).
- [ ] 5.2 Surface the developmental stage and the "awaiting embodiment" hold in the
      Nexus left rail.

## W6 — Config (`config/kaine.toml`)
- [ ] 6.1 Add the `[developmental_stage]` and `[developmental_stage.regulation_thresholds]`
      blocks (design §11) with conservative defaults. Ship `enabled = false`
      (ship-inert, matching Spot/Mundus); enabling requires a womb feed configured.

## W7 — Tests
- [ ] 7.1 Monotonicity: no path returns `embodied → gestation`; forks inherit and only
      advance the stage.
- [ ] 7.1a Preserved-being invariant: a being with prior lived history but no stage file
      defaults to `embodied`, never `gestation`.
- [ ] 7.2 Gestation lock: locus is pinned to the womb with `locus_locked` **only when a
      womb feed is configured**, the lock is attributed to `gestation` (not operator),
      and a self-switch intent is refused while gestating.
- [ ] 7.2a No-stimulus safety: `stage == gestation` with no womb feed emits a repeated
      `stage.gestation.no_stimulus` WARN and does NOT silently pin a senseless locked
      locus; an ordinary physical-perception boot (staging disabled) is unaffected.
- [ ] 7.2b Welfare net: a welfare-threshold breach during gestation still triggers the
      preservation response; the locus-lock does not suppress it.
- [ ] 7.3 Gate fail-closed: absent/stale `gestation.readiness` → not ready; sleep count
      without consolidation passes → C2 not met; sub-floor lived time → C3 not met;
      each of C1/C2/C3 alone insufficient.
- [ ] 7.4 Availability guard: ready ∧ unavailable holds in womb and emits repeated
      `stage.birth.ready{awaiting_embodiment}` + WARN; ready ∧ available births exactly
      once and switches the sense source.
- [ ] 7.5 Birth is one-shot: an already-`embodied` entity emits no further birth event.
- [ ] 7.6 Measure-not-impose: the gate changes no entity-internal state to pass a
      condition (assert via a spy that only reads occur).
- [ ] 7.7 Disabled/un-staged: `[developmental_stage].enabled = false` runs the entity
      un-staged exactly as today (regression guard).

## W8 — Validation
- [ ] 8.1 `openspec validate developmental-maturation-gate --strict` passes.
- [ ] 8.2 Lifecycle + cycle + perception-state + Nexus test suites green; Hypnos,
      Phantasia, and the womb stimulus are unmodified (read-only integration).
