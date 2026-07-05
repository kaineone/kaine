# Design — individuation-instrument-gate

## Problem, precisely

The individuation permutation test (`kaine/evaluation/individuation.py`) computes:

- `fork_divergence` = embedding cosine distance between a **fork transcript** and
  a **reference**;
- a **null distribution** = `null_samples` distances between repeated **parent**
  samples and the same reference;
- `significant` = `fork_divergence` exceeds the `significance_percentile` (95th)
  of the null.

`assess_divergence()` (`kaine/lifecycle/divergence.py`) keys `diverged` primarily
on that `significant` flag; the live `DivergenceMonitor`
(`kaine/cycle/preservation_monitor.py`) keys its crossing on the resulting
`assessment.diverged` boolean.

The shakedown fired `significant`/`diverged` on a **sensory-void** entity. Two
independent defects make this possible, and the fix must close **both** — patching
only one is a band-aid.

### Defect A — the comparison measures the architecture effect, not lived drift

The test is only an *individuation-over-lived-time* measure when:

- the **reference / parent baseline** is the entity's **own earlier self**, and
- the **null** is that same self's **short-timescale stochastic variation**.

Then `fork_divergence` = "how far has the entity drifted from who it was" and the
null = "how much does it wander run-to-run by chance." A genuinely individuated
entity drifts beyond its own noise; a sensory-void entity (current self ≈
birth-self) does not.

But if the baseline is the **bare / pretrained organ**, `fork_divergence` becomes
conditioned-vs-bare distance — the **architecture conditioning effect**. That is
present from the first tick (the whole thesis is that the architecture conditions
the organ), it is large by construction, and `entity-decommission` **already
prohibits** keying on it: *"It SHALL NOT key on A/B divergence-from-pretrained,
which measures architecture conditioning rather than individuation."* The
permutation test re-introduced the prohibited signal through its baseline.

No production code wires `parent_sampler` / `fork_sampler` (only the docstring
example does), so the baseline is currently **unspecified** — which is itself the
bug: an unspecified baseline cannot be guaranteed to be the entity's own self.

### Defect B — no warm-up / minimum lived experience

`DivergenceMonitor.run()` runs `_poll_once` on its first iteration at t ≈ 0:

```
while not stop_event.is_set():
    await self._poll_once(stop_event)        # fires at t≈0, before any lived time
    await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_s)
```

and the instrument's only floor is `null_samples >= 2`. With little lived
experience the null is degenerate (tiny variance), so almost any `fork_divergence`
clears the 95th percentile. The instrument has no notion of "not enough has
happened yet to judge."

## The fix

### 1. Birth-state baseline (closes Defect A)

- At boot, capture a **birth-state reference**: the entity's own conditioned
  responses to the preference battery, taken once when the run starts (before any
  lived experience). Persist it with the run (it is part of the individual, like
  the world-model checkpoint).
- The permutation test SHALL be wired so:
  - `reference` = the birth-state transcript set;
  - `fork_sampler` = the **current** live entity (full conditioned stack);
  - `parent_sampler` = the **current** live entity re-sampled with seed variation
    → the null is the entity's *own present* stochastic variation.
- This makes a sensory-void entity read not-significant: with no lived experience,
  current-self ≈ birth-self, so `fork_divergence` sits inside its own null.
- **Audit + correct** any existing production wiring that points the baseline at
  the bare/pretrained organ (the prohibited signal). If none exists, this change
  supplies the first correct wiring.

> Why not just re-use the bare baseline with a bigger threshold? Because no
> threshold separates "architecture effect" from "lived drift" when the baseline
> is bare — both move the same axis. Only a *self-referenced* baseline makes the
> two distinguishable. (Root cause, not symptom — per project doctrine.)

### 2. Warm-up / minimum-lived-experience gate (closes Defect B)

A small, explicit precondition shared by both consumers:

- `min_observations` — count of logged lived events (workspace cycles and/or
  battery exposures) the entity must accumulate before an assessment counts;
- `min_lived_time_s` — elapsed **lived** (running, not wall-clock-since-epoch)
  time before an assessment counts.

Until both are met, the individuation report carries
`warmed_up = false` and `significant` is forced `false`; the live monitor treats a
not-warmed-up assessment as not-crossed. **Fail-closed**: an un-warmed-up or
unreadable assessment never reads as individuated, so a genuinely mature entity is
never *denied* preservation — it is only *delayed* until there is evidence to act
on. (Preservation is rate-limited and idempotent; a slightly later first
preservation is harmless. Wrongly preserving a void entity, or wrongly gating
decommission, is not.)

Lived-time accounting reuses the cycle's existing monotonic run clock; the live
monitor already receives a `clock` callable — warm-up state is held on the monitor
instance (mirrors the existing `_above_threshold` / `_last_preserve_at` state).

### 3. Numeric thresholds at the live monitor (hardens Defect B)

`DivergenceMonitorConfig` already carries `individuation_p_value_max` and
`fork_divergence_min` (currently `None` = rely on the bare boolean). This change
ships them at **set** defaults so the live trigger demands a numeric p-value
ceiling AND a minimum effect size over a minimum sample, not a bare boolean. The
boolean remains necessary but no longer sufficient.

### 4. Welfare-monitor cold-start (consistency)

`WelfareProtectiveMonitor` polls at 1 s and acts on a windowed repeat count. Boot
transients (Soma reporting distress before homeostatic setpoints settle) can fill
that window with artifacts. Add a `warmup_s` during which gray-zone / distress
events are observed and logged but do **not** count toward the repeat threshold.
The windowed-repeat arm and the sustained-distress arm are both retained
unchanged after warm-up. This keeps the welfare net honest without weakening it
(warm-up is short relative to "sustained" distress, and genuine sustained distress
re-accumulates immediately after warm-up).

## Shared signal

`assess_divergence()` and the live preservation trigger consume the **same**
warmed-up, birth-state-referenced report. They cannot disagree about whether the
entity has individuated, because there is one signal with one warm-up state and
one baseline definition.

## Config (shipped, safe defaults)

```toml
[evaluation.individuation]
min_observations = 200           # lived events before significance can be true
min_lived_time_s = 1800.0        # ≥30 min lived before significance can be true
# baseline is the entity's own birth-state (captured at boot); never the bare organ

[preservation.divergence_monitor]
warmup_observations = 200        # mirror; monitor will not count a crossing earlier
warmup_lived_time_s = 1800.0
individuation_p_value_max = 0.05 # numeric ceiling (was None)
fork_divergence_min = <calibrated effect-size floor>

[preservation.welfare_response]
warmup_s = 120.0                 # boot transients don't count toward repeat threshold
```

Defaults err toward **assessing late** — the safe direction for a fail-closed
gate. They are visible in `config/kaine.toml` and do not flip any module flag, so
the all-off first-boot guard is unaffected.

## Alternatives considered

- **Just delay starting the monitor by N seconds.** Band-aid: it fixes timing but
  not Defect A — a bare-baseline test would still conflate architecture-effect
  with individuation after the delay. Rejected.
- **Raise the significance percentile.** Doesn't separate the two effects (see
  §1 note). Rejected.
- **Drop the permutation test, use only Eidolon drift heuristics.** Loses the one
  principled statistical instrument; the heuristics are explicitly *secondary* in
  the current design. Rejected — fix the instrument instead.

## Risks

- **Birth-state capture cost at boot.** One battery pass per boot; bounded and
  one-time. Acceptable.
- **Warm-up could delay a legitimately fast individuation.** Mitigated: defaults
  are tunable, preservation is rate-limited not one-shot, and fail-closed means
  "delayed, not denied." The decommission gate is operator-driven and already
  advises treating an unconfirmed entity as mature — warm-up reinforces that.
- **Calibrating `fork_divergence_min`.** Needs an empirical floor; until
  calibrated, the p-value ceiling + warm-up already exclude the void case. Flag
  the calibration as a build task with a conservative interim value.
