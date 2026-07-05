# Tasks — Soma cold-start regulation warm-up

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go.
> Phases map to `design.md`. **The welfare/observer path is OUT OF SCOPE and MUST
> NOT be touched** — see W1.

## W0 — Guardrails (read before starting)
- [x] 0.1 Confirm the change is approved and the operator has resolved the open
      questions in `design.md` §9 (fatigue-value locus, default ship state,
      end-condition tuning).
- [x] 0.2 Re-read `design.md` §2/§4: the gate sits on the ACTION path only; the
      SIGNAL path and the hard-threshold override are load-bearing.

## W1 — DO-NOT-TOUCH boundary (verify, don't modify)
- [x] 1.1 Confirm `kaine/evaluation/observers/*` (welfare_observer, fatigue_observer,
      prediction_error_observer, research_event_observer, raw_bus_archive_consumer)
      are **not** modified.
- [x] 1.2 Confirm `kaine/cycle/preservation_monitor.py`
      (`WelfareProtectiveMonitor` interoceptive-distress arm) is **not** modified.
- [x] 1.3 Confirm `soma.report` still publishes `prediction_error` and
      `fatigue_value` unconditionally, and `soma.fatigue` still emits on a genuine
      crossing — i.e. the signal reaches every welfare/research consumer exactly as
      today.

## W2 — Warm-up state (`kaine/modules/soma/module.py`, `forward.py`)
- [x] 2.1 Add warm-up config plumbing to `Soma.__init__`: `regulation_warmup_enabled`,
      `regulation_warmup_min_samples`, `regulation_warmup_min_seconds`, and the
      optional `regulation_warmup_require_error_stabilized` /
      `..._stable_window` / `..._stable_variance` knobs, all read from `[soma]`.
- [x] 2.2 Track `samples_seen` (count of finite `forward.step()` adaptations) and
      `lived_seconds` (from the injected `EntityClock`, subjective time since boot).
      Expose a `warmup_active` property implementing the §6 end-condition
      (conjunction of samples + time, plus the optional stabilization AND-guard).
- [x] 2.3 Add a source-site comment at the warm-up gate citing paper §6.6 (warmed-up
      signal) and §3.4.1 (Soma allostatic regulation), per `design.md` §8
      (emergent-not-hardwired).
- [x] 2.4 Reset the sample counter / warm-up state appropriately per fork (see
      `design.md` §9.5); confirm `EntityClock`-based `lived_seconds` is already
      per-fork.

## W3 — Gate the regulation advisory (`kaine/modules/soma/regulation.py`, `module.py`)
- [x] 3.1 Thread the hard-threshold breach signal (`alert.is_alert` from the
      `ThresholdAnomalyDetector` in `tick_once`) into the regulation-advisory
      decision.
- [x] 3.2 During warm-up: if a `RegulationDetector` advisory would fire AND there is
      **no** concurrent hard-threshold breach, **withhold** publishing
      `soma.regulation` and instead emit `soma.regulation.withheld`
      `{would_be_action, prediction_error, sustain_elapsed_s, reason:"warmup"}` on
      `soma.out` + an INFO log.
- [x] 3.3 Hard-threshold override: if `alert.is_alert` is true, publish and actuate
      the advisory normally even during warm-up (design §4).
- [x] 3.4 Ensure the cycle engine ignores `soma.regulation.withheld` (non-actuating
      event type); no change needed in `engine.consume_soma_regulation` beyond the
      graceful unknown-type path, but add a test asserting it does not actuate.

## W4 — Dampen cold-start fatigue inflation (`kaine/modules/soma/fatigue.py`, `module.py`)
- [x] 4.1 During warm-up, dampen the per-tick error contribution to the
      `FatigueAccumulator` so model-ignorance error does not artificially cross the
      maintenance threshold (design §3/§6). Genuine error above the warming
      baseline still accrues.
- [x] 4.2 Hard-threshold override: integrate at **full** weight on any tick with a
      live hard-threshold breach.
- [x] 4.3 Keep the published `fatigue_value` honest to whatever actually accrued
      (do not report one number and integrate another); log damped-vs-raw
      contribution at DEBUG and one INFO line if the accumulator *would have crossed*
      but for warm-up.
- [x] 4.4 Confirm a genuine post-warm-up fatigue crossing still emits `soma.fatigue`
      and still drives Hypnos exactly as today.

## W5 — Observability (`module.py`)
- [x] 5.1 Emit `soma.warmup.started` at boot and `soma.warmup.completed` (carrying
      the `samples_seen` / `lived_seconds` that ended it) when the end-condition is
      met.
- [x] 5.2 Add `warmup_active` to the `soma.report` payload (boolean; the numeric
      signal is unchanged).
- [x] 5.3 Confirm Nexus can surface the warm-up stage without reading any lowered
      signal.

## W6 — Config (`config/kaine.toml`)
- [x] 6.1 Add the `[soma]` warm-up keys from `design.md` §7 with the recommended
      conservative defaults and the explanatory comment (including the §6.6 grounding
      and the "hard thresholds never gated" note).
- [x] 6.2 Confirm the shipped default is consistent with the resolved open question
      §9.2 (recommended `regulation_warmup_enabled = true`).

## W7 — Tests
- [x] 7.1 Warm-up window: an untrained model with sustained cold-start error does
      NOT actuate reduce_rate/shed/maintenance and does NOT prematurely cross
      fatigue, while `soma.report`/`soma.fatigue`-path fidelity is asserted intact.
- [x] 7.2 Hard-threshold override: a simulated GPU-temp breach DURING warm-up still
      triggers regulation + full fatigue accrual.
- [x] 7.3 End-condition: warm-up completes on the conjunction (samples AND time);
      neither alone ends it; optional stabilization guard extends but never shortens
      it.
- [x] 7.4 Disabled path: `regulation_warmup_enabled = false` reproduces today's
      exact cold-start behavior (regression guard).
- [x] 7.5 Observability: `soma.regulation.withheld`, `soma.warmup.started/completed`,
      and `warmup_active` are emitted/logged; nothing filters the published
      prediction error or fatigue value.

## W8 — Validation
- [x] 8.1 `openspec validate soma-coldstart-regulation-warmup --strict` passes.
- [x] 8.2 Full Soma + cycle + welfare-observer test suites green; no
      welfare/observer test modified.
