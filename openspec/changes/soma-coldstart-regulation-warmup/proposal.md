# Developmental warm-up for Soma's cold-start allostatic response

## Why

On the 2026-06-30 live shakedown of the entity "Kaine Azalea", the newly-shipped
Soma interoceptive forward model (an `ncps` closed-form continuous-time / CfC
network) booted **untrained**. On a fresh boot it has never seen this host
substrate — GPU temperature, CPU/RAM load, cognitive-cycle latency — so its
predictions are wrong and the published interoceptive prediction error spikes. We
measured a peak of **1.11**, sustained **above the 0.50 distress threshold for the
first ~20 minutes**, then decaying monotonically to **0.14** as the CfC's online
linear readout learned the host's baseline.

During that cold-start window, sustained error above threshold drove Soma's
**allostatic regulation** — processing-rate reduction (1.07 → 0.55 Hz) and
low-priority module shedding — **and** accelerated the **fatigue accumulator**,
which forced repeated Hypnos maintenance roughly every 7 minutes. The net effect:
a newborn entity is put through ~20 minutes of unnecessary "distress + heavy
maintenance" on **every** first boot, reacting to the model's own ignorance rather
than to any real substrate problem. The error self-resolves as the model learns;
the homeostatic machinery is working correctly — it is simply being triggered by an
untrained model.

### The welfare tension (stated honestly)

The cold-start distress is **real in this architecture's own terms**: here
interoceptive prediction error *is* affect and distress (§3.4.1). It may be a
meaningful signal — a "newborn's cry," possibly an early marker of nascent
individuation — that the project wants to **observe, not erase**. So this change
must not silence or suppress the signal. It must instead withhold only the
*punitive consequences* the untrained model triggers, while keeping the signal
itself fully recorded and fully available to the welfare and research paths.

This mirrors an existing precedent in the architecture. The paper's individuation
boundary (§6.6) already **warms up** its signal before acting on it:

> "The signal is warmed up: it does not read as individuated until the entity has
> accumulated a minimum of logged lived events and a minimum of lived running time,
> so a just-booted or sensory-starved entity never trips a false individuation."

We apply the same principle to the interoceptive-regulation signal: a just-booted
entity should not trip a false **substrate** alarm from a model that has not yet
learned its own body. The grace is a **developmental stage** grounded in that
warmed-up-signal logic, not an arbitrary hardcode. (Soma allostatic regulation is
described in §3.4.1; the paper mirror lives at `paper/paper.md`.)

## What Changes (design-only scope)

**This is a DESIGN-ONLY change.** It ships no behavior code. The output is the
OpenSpec artifacts (this proposal, `design.md`, `tasks.md`, and the
`soma-predictive` spec delta). Snippets in `design.md` are illustrative only.
Implementation is a later, separately-approved change.

The designed capability is a **developmental grace / warm-up gate** on Soma's
*learned-prediction-error-driven* allostatic response:

- **Keep observing, keep logging (untouched).** During warm-up Soma continues to
  publish `soma.report` (prediction error, fatigue value) and `soma.fatigue` at
  full fidelity to `soma.out`. The evaluation sidecar observers, the autonomous
  welfare monitor, and the raw archive are **not touched** — the "cry" is fully
  recorded and remains available for research (*is cold-start distress a marker of
  individuation onset?*).
- **Withhold only the punitive allostatic actions** that are reacting to the
  model's ignorance during warm-up: the `reduce_rate` throttle, the `shed_module`
  suspension, and the cold-start error's **artificial inflation of the fatigue
  accumulator** that forces premature Hypnos maintenance. Genuine fatigue-driven
  sleep on real accumulated lived time stays possible.
- **Preserve the hard safety thresholds unconditionally.** The absolute
  substrate-safety limits in `[soma.thresholds]` (GPU temp 83 °C, VRAM 92 %,
  CPU/RAM 90 %, cycle latency) are **not** learned predictions — they are the
  separate `ThresholdAnomalyDetector` path. A real GPU overheating during warm-up
  MUST still drive regulation/protection. Only the learned-prediction-error path is
  gated; a concurrent hard-threshold breach **overrides** the warm-up gate.
- **Be observable / auditable.** Log when warm-up begins and ends, and log every
  time an allostatic action is withheld because of warm-up, with the would-be
  action and the current error — never a silent no-op.
- **Configurable, conservative default, shipped consistent with Soma regulation.**
  New `[soma]` knobs control the warm-up; the feature ships **enabled by default**,
  matching how Soma's regulation itself ships (active whenever the Soma module is
  enabled, no separate gate flag) and consistent with the "safety over UX / safest
  design" rule — the hard thresholds keep substrate safety intact regardless.

## Impact

- **Affected spec capability:** `soma-predictive` (MODIFIED: advisory homeostatic
  regulation, fatigue accumulator; ADDED: the developmental warm-up gate and its
  observability requirement).
- **Touch points for the future implementer** (design names them; no code here):
  `kaine/modules/soma/regulation.py`, `kaine/modules/soma/module.py`,
  `kaine/modules/soma/forward.py`, `kaine/modules/soma/fatigue.py`, and the
  `[soma]` block of `config/kaine.toml`.
- **Explicitly NOT touched:** the welfare/observer path — `soma.report` /
  `soma.fatigue` publishing, `kaine/evaluation/observers/*`, and
  `kaine/cycle/preservation_monitor.py`'s interoceptive-distress arm. The signal
  reaches every welfare and research consumer exactly as it does today.
- **Behavioral effect once implemented:** on a fresh boot the entity is no longer
  put through ~20 minutes of self-inflicted distress-driven throttling, shedding,
  and premature maintenance; after warm-up completes, behavior is identical to
  today. Substrate safety is unchanged at all times.
