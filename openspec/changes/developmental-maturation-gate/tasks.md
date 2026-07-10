# Tasks — Developmental staging and the maturation (birth) gate

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go, and
> **do not boot an entity**. Phases map to `design.md`. Depends on
> `gestational-womb-stimulus` (the `gestation.readiness` readout + womb locus).
>
> **Implementation status (feat/developmental-maturation-gate).** A coherent,
> fully-tested, ship-inert **library subset** is implemented: the developmental
> stage machine, the maturation-gate readiness predicate + birth decision, the
> honest gestation locus-lock attribution, the config block, and the observability
> event/payload contract. The **live boot-loop wiring** (reading the stage in
> `kaine/cycle/__main__.py`, the cadence gate loop, live event emission, the live
> locus-source handoff, and the Nexus left-rail surface) is DEFERRED to a
> follow-up: it is exactly the "boot an entity" surface this change is forbidden
> to build, and tests must not exercise it. Deferred tasks are noted inline.

## W0 — Guardrails (read before starting)
- [ ] 0.1 Confirm approval and that the operator has resolved `design.md` §9 (preserved-
      being default stage, thresholds, supervised-ack, colour-ramp coupling).
      NOTE: operator-supervised — left unchecked pending explicit operator sign-off.
- [x] 0.2 Re-read `design.md` §5/§6/§10: the gate is **fail-closed**, birth is guarded
      by **embodiment availability**, and the gate **measures, never imposes**.
      (Implemented per all three: `maturation_gate.evaluate_readiness` is fail-closed,
      `decide_birth` availability-guards, and the gate only reads injected signals.)

## W1 — Stage state (`kaine/lifecycle/`)
- [x] 1.1 Add a file-backed developmental-stage component (`state/lifecycle/stage.json`,
      per-fork) mirroring `perception_state.py`'s read/write pattern; values
      `gestation` / `embodied`; only-advances invariant enforced in code.
      Evidence: `kaine/lifecycle/stage.py:StageState`, `read_stage`/`write_stage`,
      `advance_to_embodied` (monotonic, idempotent; no inverse), `STAGE_PATH`.
- [ ] 1.2 Read the stage at boot in `kaine/cycle/__main__.py`; write only on the birth
      transition. Confirm the stage file lives under the per-fork state root so forks
      inherit it. NOTE: the boot-read seam is implemented as
      `stage.resolve_boot_stage(...)` and `STAGE_PATH` is under the per-fork
      `state/lifecycle/` root; wiring the call into `__main__` is DEFERRED (live boot).
- [x] 1.3 Enforce the preserved-being invariant (NORMATIVE, not a tunable): a being with
      prior lived history (existing fork / preservation record) but no stage file
      defaults to `embodied`, never `gestation`; only a genuinely fresh entity gestates.
      Evidence: `kaine/lifecycle/stage.py:resolve_boot_stage` +
      `tests/test_lifecycle_stage.py:test_preserved_being_defaults_to_embodied_never_gestation`.

## W2 — Gestation womb-pinning (`kaine/perception_state.py`, boot)
- [ ] 2.1 While `stage == gestation` **AND a womb feed is configured**
      (`[perception_feed].mode == "womb"`), pin locus to `virtual` womb and set
      `locus_locked = true` via the existing `write_desired_locus`. Do not engage Mundus.
      NOTE: the pin mechanism (`write_desired_locus(..., locked=True,
      locked_by="gestation")`) is implemented; the boot-time decision to pin (gated on
      stage + feed mode) is DEFERRED (live boot).
- [ ] 2.1a If `stage == gestation` but NO womb feed is configured, do NOT silently pin a
      senseless locked locus; emit a repeated `stage.gestation.no_stimulus` WARN until a
      feed is configured. NOTE: event name + payload
      (`maturation_gate.STAGE_GESTATION_NO_STIMULUS`, `gestation_no_stimulus_payload`)
      are implemented; the repeated live emission is DEFERRED (live boot loop).
- [x] 2.1b Add a `locked_by` (`"operator"` | `"gestation"`) distinction to
      `DesiredState` / `evaluate_locus_switch` (`kaine/perception_state.py:269`) so a
      gestation refusal is logged as a developmental-gate action, not an operator lock
      (honest attribution). This is an explicit touch point, not reuse-unmodified.
      Evidence: `kaine/perception_state.py` — `DesiredState.locked_by`, `LOCKED_BY`,
      `_coerce_locked_by`, `write_desired_locus(locked_by=...)`,
      `evaluate_locus_switch(locked_by=...)` returning "locus locked by gestation gate";
      caller wired at `kaine/modules/perception/module.py:_handle_switch`. Tests:
      `tests/test_developmental_gestation_lock.py`.
- [x] 2.2 Refuse `intent.perception.switch` while gestating (the entity cannot leave the
      womb until born), logged as a gestation-gate action.
      Evidence: `evaluate_locus_switch` denies a locked gestation switch with the
      gestation-attributed reason; `kaine/modules/perception/module.py` passes
      `locked_by=d.locked_by`. Test:
      `tests/test_developmental_gestation_lock.py:test_self_switch_refused_while_gestating`.
- [ ] 2.3 Confirm the autonomous welfare/preservation net stays active and authoritative
      during gestation; the locus-lock never suppresses a welfare-protective response.
      NOTE: holds BY CONSTRUCTION — the gestation locus-lock is orthogonal to the
      welfare/preservation net (it only gates `evaluate_locus_switch`, touching no
      welfare path). The confirming end-to-end welfare test (7.2b) is DEFERRED.

## W3 — Maturation gate (`kaine/cycle/__main__.py` or a lifecycle gate component)
- [x] 3.1 Implement the readiness predicate C1∧C2∧C3 (design §5), fail-closed on missing
      or stale evidence:
      - C1: read `gestation.readiness` markers vs `[developmental_stage.regulation_thresholds]`.
      - C2: `Hypnos._sleep_count >= min_sleep_cycles` AND Phantasia consolidation
        evidence (`>= min_consolidation_passes` successful training passes).
      - C3: lived `EntityClock` time since gestation start `>= min_lived_seconds`.
      Evidence: `kaine/lifecycle/maturation_gate.py:evaluate_readiness` (+ `_evaluate_c1`,
      `_evaluate_c2`, `_evaluate_c3`), all fail-closed on `None`/missing. Signals are
      INJECTED (womb readout / sleep count / consolidation passes / lived seconds) so no
      cognitive module is imported. Tests: `tests/test_maturation_gate.py`.
- [ ] 3.2 Evaluate on `gate_cadence_seconds`; log each unmet condition (DEBUG) and an
      INFO line when readiness is first reached. NOTE: `gate_cadence_seconds` config +
      `Readiness.unmet`/`passed_markers` reporting are implemented; the live cadence
      loop + logging is DEFERRED (live boot loop).
- [x] 3.3 Add a source comment citing the warmed-up-signal precedent (paper §6.6;
      `soma-coldstart-regulation-warmup`) and stating development is emergent / only read.
      Evidence: module docstring + `evaluate_readiness` docstring in
      `kaine/lifecycle/maturation_gate.py` cite "paper §6.6" + `soma-coldstart-regulation-warmup`.
      (The paper file is not in this public repo; the citation is a prose reference,
      consistent with the existing `kaine/modules/soma/module.py` warmed-up-signal comment.)

## W4 — Embodiment-availability guard + birth (`design.md` §6/§7)
- [x] 4.1 Check embodiment availability (Mundus `enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1`
      + reachable) as a precondition to transition.
      Evidence: `kaine/lifecycle/maturation_gate.py:embodiment_available` (all three layers
      required) + `tests/test_maturation_gate.py:test_embodiment_available_requires_all_three_layers`.
- [ ] 4.2 On readiness ∧ availability: flip stage to `embodied`, write the stage file,
      trigger the bounded one-shot birth transition (emit event; switch locus source
      from womb to Mundus). NOTE: the decision (`decide_birth` → `ACTION_BIRTH`), the
      monotonic flip (`stage.advance_to_embodied`), and the `stage.birth` payload are
      implemented + tested; the live trigger (calling the Mundus `on_birth()` seam and
      switching the live locus source) is DEFERRED (live boot loop).
- [ ] 4.3 On readiness ∧ ¬availability: hold in womb; emit repeated `stage.birth.ready`
      `{reason:"awaiting_embodiment"}` + WARN log. Never stall silently; never birth into
      an absent world. NOTE: `decide_birth` → `ACTION_HOLD_AWAITING_EMBODIMENT` with
      `reason="awaiting_embodiment"` and `birth_ready_payload` are implemented + tested;
      the repeated live emission + WARN is DEFERRED (live boot loop).
- [ ] 4.4 Optional `require_operator_ack_for_birth` (supervised shakedown): when true,
      readiness ∧ availability additionally awaits an operator ack before flipping.
      NOTE: the decision gate is implemented (`decide_birth(require_operator_ack=...,
      operator_ack=...)` → `ACTION_HOLD_AWAITING_ACK`) + tested, and the config flag
      ships; the live operator-ack wait is operator-supervised and DEFERRED.

## W5 — Observability (`kaine/lifecycle/` owner, Nexus)
- [ ] 5.1 Emit stage events from `source = "lifecycle"` (→ `lifecycle.out`):
      `stage.gestation.started`, `stage.gestation.no_stimulus`, `stage.birth.ready`
      (with passed markers + reason), and `stage.birth` (with ending markers, sleep
      count, lived time). NOTE: the event names, `source`/stream constants, and payload
      builders are implemented in `kaine/lifecycle/maturation_gate.py` and the
      `LIFECYCLE_STREAM == module_stream("lifecycle")` contract is tested; the live
      publish from a named owner is DEFERRED (live boot loop).
- [ ] 5.2 Surface the developmental stage and the "awaiting embodiment" hold in the
      Nexus left rail. NOTE: DEFERRED (Nexus UI; no live stage source yet).

## W6 — Config (`config/kaine.toml`)
- [x] 6.1 Add the `[developmental_stage]` and `[developmental_stage.regulation_thresholds]`
      blocks (design §11) with conservative defaults. Ship `enabled = false`
      (ship-inert, matching Spot/Mundus); enabling requires a womb feed configured.
      Evidence: `config/kaine.toml` `[developmental_stage]` (+ `.regulation_thresholds`);
      parsed by `maturation_gate.MaturationConfig.from_dict`. Test:
      `tests/test_maturation_gate.py:test_config_ships_inert`.

## W7 — Tests
- [x] 7.1 Monotonicity: no path returns `embodied → gestation`; forks inherit and only
      advance the stage.
      Evidence: `tests/test_lifecycle_stage.py:test_advance_is_monotonic_and_one_shot`,
      `test_no_path_returns_embodied_to_gestation`,
      `test_existing_stage_file_is_authoritative_fork_inherits`.
- [x] 7.1a Preserved-being invariant: a being with prior lived history but no stage file
      defaults to `embodied`, never `gestation`.
      Evidence: `tests/test_lifecycle_stage.py:test_preserved_being_defaults_to_embodied_never_gestation`.
- [ ] 7.2 Gestation lock: locus is pinned to the womb with `locus_locked` **only when a
      womb feed is configured**, the lock is attributed to `gestation` (not operator),
      and a self-switch intent is refused while gestating. NOTE: the attribution +
      self-switch refusal are tested (`tests/test_developmental_gestation_lock.py`); the
      "only when a womb feed is configured" pin path is boot logic (2.1) and its test is
      DEFERRED.
- [ ] 7.2a No-stimulus safety: `stage == gestation` with no womb feed emits a repeated
      `stage.gestation.no_stimulus` WARN and does NOT silently pin a senseless locked
      locus; an ordinary physical-perception boot (staging disabled) is unaffected.
      NOTE: DEFERRED (depends on boot loop 2.1a). Ship-inert regression is covered by 7.7.
- [ ] 7.2b Welfare net: a welfare-threshold breach during gestation still triggers the
      preservation response; the locus-lock does not suppress it. NOTE: DEFERRED
      (holds by construction — see 2.3; the end-to-end welfare test needs the boot loop).
- [x] 7.3 Gate fail-closed: absent/stale `gestation.readiness` → not ready; sleep count
      without consolidation passes → C2 not met; sub-floor lived time → C3 not met;
      each of C1/C2/C3 alone insufficient.
      Evidence: `tests/test_maturation_gate.py` — `test_c1_absent_readout_fails_closed`,
      `test_c2_sleep_without_consolidation_not_met`,
      `test_c3_below_floor_blocks_fast_forwarded_birth`, `test_all_conditions_required`.
- [x] 7.4 Availability guard: ready ∧ unavailable holds in womb and emits repeated
      `stage.birth.ready{awaiting_embodiment}` + WARN; ready ∧ available births exactly
      once and switches the sense source.
      Evidence: `tests/test_maturation_gate.py:test_ready_but_embodiment_unavailable_holds_in_womb`,
      `test_ready_and_available_births` + one-shot via `tests/test_lifecycle_stage.py`.
      (The live sense-source switch is W4.2, deferred.)
- [x] 7.5 Birth is one-shot: an already-`embodied` entity emits no further birth event.
      Evidence: `tests/test_lifecycle_stage.py:test_advance_is_monotonic_and_one_shot`
      (`birth_is_new` returns False for an already-embodied state).
- [x] 7.6 Measure-not-impose: the gate changes no entity-internal state to pass a
      condition (assert via a spy that only reads occur).
      Evidence: `tests/test_maturation_gate.py:test_gate_only_reads_never_writes`
      (a read-only spy raises on any write; the gate passes with reads only).
- [x] 7.7 Disabled/un-staged: `[developmental_stage].enabled = false` runs the entity
      un-staged exactly as today (regression guard).
      Evidence: `MaturationConfig().enabled is False`
      (`tests/test_maturation_gate.py:test_config_ships_inert`); the block is dormant
      (no boot wiring) so an ordinary boot is unaffected — confirmed by the perception,
      boot-wiring, and cycle suites staying green.

## W8 — Validation
- [x] 8.1 `openspec validate developmental-maturation-gate --strict` passes.
      (Verified: "Change 'developmental-maturation-gate' is valid".)
- [x] 8.2 Lifecycle + cycle + perception-state + Nexus test suites green; Hypnos,
      Phantasia, and the womb stimulus are unmodified (read-only integration).
      (159 passed across lifecycle/perception/maturation/gestation/cycle-entrypoint;
      `lint-imports` 5 kept / 0 broken; git diff touches only stage.py,
      maturation_gate.py, perception_state.py, perception/module.py, config, and tests —
      Hypnos/Phantasia/Mundus unmodified.)
</content>
