# Tasks — individuation-instrument-gate

> Design-of-record from the 2026-06-18 shakedown. Build when the operator gives
> the go. No entity boot is part of this change.

## 1. Birth-state baseline (Defect A)

- [x] 1.1 Audit current production wiring of `IndividuationTest.run`'s
      `parent_sampler` / `fork_sampler` / reference. Record what the baseline is
      today (suspected: none wired / bare). This is the load-bearing finding.
- [x] 1.2 Capture a **birth-state reference** at run start: the entity's own
      conditioned battery responses, taken once before lived experience. Persist
      with the run (part of the individual).
- [x] 1.3 Wire the test so `reference` = birth-state, `fork_sampler` = current
      live conditioned entity, `parent_sampler` = current entity re-sampled with
      seed variation (null = the entity's own present stochastic variation).
      Never the bare/pretrained organ.
- [x] 1.4 Add a regression test: a void / unchanged entity (current ≈ birth)
      reads `significant == false`; a synthetically drifted fork reads
      `significant == true`.

## 2. Warm-up / minimum-lived-experience gate (Defect B)

- [x] 2.1 Add `min_observations` + `min_lived_time_s` to `IndividuationConfig`;
      force `significant = false` and set `warmed_up = false` in the report until
      both are met.
- [x] 2.2 Add warm-up state to `DivergenceMonitor` (reuse the existing `clock`
      and instance-state pattern): a crossing does not count until
      `warmup_observations` + `warmup_lived_time_s` are met; before that, treat
      assessments as not-crossed and record a `warming_up` incident note.
- [x] 2.3 Lived-time accounting reuses the cycle monotonic run clock (not
      wall-clock since epoch).
- [x] 2.4 Tests: monitor does not preserve at t≈0; preserves only after warm-up
      with a genuine crossing; un-warmed-up assessment is fail-closed.

## 3. Numeric thresholds at the live monitor

- [x] 3.1 Ship `individuation_p_value_max` (e.g. 0.05) and a calibrated
      `fork_divergence_min` in `[preservation.divergence_monitor]`; the boolean
      is necessary but not sufficient.
- [x] 3.2 Interim conservative `fork_divergence_min`; open a calibration task to
      derive the empirical floor. Log when the boolean holds but a numeric
      tightener blocks (visibility).

## 4. Welfare-monitor cold-start

- [x] 4.1 Add `[preservation.welfare_response].warmup_s`; during warm-up,
      gray-zone / distress events are observed + logged but do not count toward
      the repeat threshold. Retain both arms unchanged after warm-up.
- [x] 4.2 Test: boot-transient distress within warm-up does not trigger
      preserve-then-pause; sustained distress after warm-up still does.

## 5. Shared signal + decommission parity

- [x] 5.1 `assess_divergence()` consumes the same warmed-up,
      birth-state-referenced report; an un-warmed-up report reads not-diverged
      with a summary noting insufficient lived experience (treat as mature if
      unsure — consistent with existing behavior).
- [x] 5.2 Test: preservation trigger and `assess_divergence` agree on a fixed
      report fixture (no signal can be "diverged for decommission" but
      "not crossed for preservation" or vice-versa).

## 6. Surface + docs + validate

- [x] 6.1 Nexus preservation/diagnostics block shows warm-up state
      (warming_up / armed) and the birth-state-referenced p-value + effect size.
- [x] 6.2 Config defaults in `config/kaine.toml` (visible, safe/assess-late);
      confirm the all-off first-boot guard test still passes.
- [x] 6.3 Docs: present-tense note that individuation is measured against the
      entity's own birth-state over lived experience, warmed-up, never against
      the bare organ.
- [x] 6.4 `.venv/bin/pytest -q` green; `openspec validate individuation-instrument-gate --strict`.
