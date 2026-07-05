# Design — Soma predictive interoception

## Current behavior

`Soma` reads psutil (CPU/RAM) + pynvml (GPU temp/VRAM) + cycle latency, computes
a normalized `wellness` score and threshold `alerts`, and publishes `soma.report`.
`ThresholdAnomalyDetector` is static. There is no forward model, no accumulation
across time, no feedback to the cycle.

## Forward model

A small CfC network (ncps, ~32 units, CPU, mirroring Chronos's pattern in
`kaine/modules/chronos/network.py`) predicts the next substrate feature vector
`x̂(t+1)` from `x(t)` and its recurrent state. The featurizer reuses Soma's
existing normalized metric vector. Prediction error `e(t) = ||x(t) − x̂(t−1)||`
is the salient signal published to the workspace.

Online adaptation: unlike Chronos's frozen CfC, Soma's forward model takes a
small gradient step each tick toward the observed `x(t)` (single-sample SGD,
tiny LR). This lets "normal" drift as the host's workload baseline shifts, so
sustained error means *genuine* novelty, not a stale baseline. Adaptation is
suspended during Hypnos via an `_in_hypnos` flag: Soma subscribes to
`hypnos.sleep.started` (sets flag `True`, freezes weights) and
`hypnos.sleep.completed` (sets flag `False`, resumes adaptation); substrate
readings during sleep are atypical and must not shift the model's baseline.
Guarded so a non-finite loss never corrupts weights.

## Fatigue accumulator

`F(t+Δ) = max(0, F(t) + e(t)·Δ − decay·Δ)`. Integrates prediction error over
waking time; decays continuously (and faster during Hypnos). Crossing
`fatigue_maintenance_threshold` emits `soma.fatigue {value, threshold,
crossed: true}` — the trigger `hypnos-restructure` consumes instead of its timer.
Reset to baseline at the end of a Hypnos cycle (phase 4, affective/fatigue reset).

## Homeostatic regulation

When `e(t)` stays above `regulation_threshold` for `regulation_sustain_window_s`,
Soma publishes `soma.regulation {action, reason, severity}` where action ∈
{`reduce_rate`, `shed_module`, `request_maintenance`}. These are **advisory** —
the cycle's rate control and Hypnos remain the actuators; Soma never directly
mutates rates or unregisters modules (separation of perception from control, and
keeps the welfare-critical actions auditable in one place).

The concrete consumer is `kaine/cycle/engine.py`, which drains `soma.out` and
acts on `soma.regulation` events: `reduce_rate` adjusts the tick interval within
configured bounds; `shed_module` requests a low-priority module suspension;
`request_maintenance` sets a flag Hypnos reads to schedule an earlier offline
cycle. The engine logs each advisory action and ignores unknown `action` values
gracefully.

## Why advisory, not actuating

The paper says Soma "attempts to regulate" — but a perception module that can
silently throttle cognition or shed modules is both a coupling hazard
(correlated-error pathology, §9) and a welfare-sensitive action. Publishing
intents keeps the existing rate-control and freeze/maintenance paths as the
single point of actuation and audit.

## Risks

- Online adaptation instability → clamp LR, skip non-finite steps, cap error.
- Fatigue tuning → ship conservative defaults; the value is on `soma.report` for
  Nexus observation before wiring the Hypnos trigger hot.
- Correlated errors inflating fatigue during a real incident → decay + the
  cycle's own backpressure bound it; regulation is advisory.

## Out of scope

Acting on regulation requests (that is the cycle's / Hypnos's job, specified in
`hypnos-restructure`). A learned (non-CfC) substrate model.
