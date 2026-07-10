# Design — Soma cold-start regulation warm-up

> **Design-of-record only.** No behavior code ships with this change. Code
> references and snippets are illustrative of the intended future implementation.

## 1. Problem, in the architecture's own terms

Soma's `SubstrateForwardModel` (`kaine/modules/soma/forward.py`) is a frozen CfC
reservoir plus an **online-learned** linear readout. The readout starts at random
init and adapts one SGD step per tick toward the observed substrate feature vector.
On a fresh boot it has never seen this host, so for the first minutes its
predictions are wrong and the L2 prediction error is large. Two Soma-owned
mechanisms then convert that error into punitive action:

1. **`RegulationDetector`** (`regulation.py`) — when error stays above
   `regulation_threshold` (0.5) for `regulation_sustain_window_s` (30 s), it emits
   a `soma.regulation` advisory that escalates `reduce_rate` → `shed_module` →
   `request_maintenance`. The cycle engine actuates these
   (`engine.consume_soma_regulation`): rate throttle, low-priority module
   suspension, and — via Hypnos observing the event — an early maintenance cycle.
2. **`FatigueAccumulator`** (`fatigue.py`) — integrates prediction error over
   waking time: `F += (error - decay) * dt`. A sustained cold-start error inflates
   `F` quickly past `fatigue_maintenance_threshold`, publishing `soma.fatigue`,
   which Hypnos treats as sleep pressure → premature maintenance.

Both are **correct** mechanisms responding to a **wrong** input. The fix is a
developmental grace that gates the *response* during a bounded warm-up window while
the readout learns the baseline — without touching the *signal*.

## 2. The signal path vs. the action path (the load-bearing split)

The single most important design decision is **where the gate sits**. Soma has two
distinct downstreams for the prediction error:

```
                         forward.step() → prediction_error
                                   │
        ┌──────────────────────────┼─────────────────────────────┐
        │  SIGNAL / OBSERVE PATH    │   ACTION / ACTUATE PATH       │
        │  (NEVER gated)            │   (gated during warm-up)      │
        ▼                           ▼                               ▼
  soma.report{prediction_error,  RegulationDetector →        FatigueAccumulator →
    fatigue_value} on soma.out     soma.regulation advisory     soma.fatigue → Hypnos
        │                           │  (reduce_rate/shed/          (premature maintenance)
        ▼                           │   request_maintenance)
  welfare_observer,                 ▼
  fatigue_observer,           engine.consume_soma_regulation:
  prediction_error_observer,   rate throttle / module shed /
  research_event_observer,     maintenance latch
  raw_bus_archive_consumer,
  preservation_monitor
  (WelfareProtectiveMonitor)
```

The warm-up gate is placed **only on the ACTION path, inside Soma**. The SIGNAL
path — `soma.report` publishing and everything that reads it — is byte-for-byte
unchanged. This is what guarantees the "cry" is fully recorded: the welfare
observer, the fatigue observer, the research event log, the raw archive, and the
`WelfareProtectiveMonitor`'s interoceptive-distress arm all read `soma.report`'s
`prediction_error` (and `soma.fatigue`) directly and continue to do so at full
fidelity. **We do not touch `kaine/evaluation/observers/*` or
`kaine/cycle/preservation_monitor.py` at all.**

## 3. What is gated vs. what stays live

### Gated during warm-up (the punitive allostatic actions)

| Action | Source | Warm-up behavior |
| --- | --- | --- |
| `reduce_rate` processing throttle | `RegulationDetector` advisory | **Withheld** — advisory not published (unless hard-threshold override, §4) |
| `shed_module` low-priority suspension | `RegulationDetector` advisory | **Withheld** — advisory not published (unless override) |
| `request_maintenance` (RegulationDetector tier 3 → Hypnos) | `RegulationDetector` advisory | **Withheld** — advisory not published (unless override) |
| Premature Hypnos via fatigue | `FatigueAccumulator` crossing | **Cold-start error's contribution to `F` is dampened** so the untrained model does not artificially cross the maintenance threshold |

### Stays fully live at all times (never gated)

- **All hard substrate-safety thresholds** in `[soma.thresholds]` via the
  `ThresholdAnomalyDetector` (`detector.py`): these are absolute limits, **not**
  learned predictions. The `alert` evaluation, the `alerts` list on `soma.report`,
  and alert-driven salience are untouched.
- **`soma.report` and `soma.fatigue` publishing** (the signal path, §2).
- **Genuine fatigue** on real lived time: fatigue still accrues from any error
  *above the warming model's own baseline*, and always accrues at full weight once
  a hard threshold is breached — so real sleep pressure from real load still
  builds. Warm-up dampens only the artificial cold-start inflation, not fatigue as
  such.
- **Forward-model online adaptation** — the readout keeps learning every tick; in
  fact warm-up *ends because* it has learned. (Adaptation is already suspended
  during Hypnos sleep; that is unchanged.)

## 4. The hard-threshold override (does warm-up ever mask a real problem?)

This is the key safety question: if we withhold the learned-regulation advisory
during warm-up, and a **real** GPU overheat happens in that window, is protection
lost?

Two answers, layered:

1. **The threshold path is independent and never gated.** A real breach of an
   absolute limit is detected by `ThresholdAnomalyDetector`, not by the CfC. That
   detection (`alert.is_alert`, the `alerts` list, alert salience) fires regardless
   of warm-up. Perception of the danger is never suppressed.
2. **A concurrent hard-threshold breach OVERRIDES the warm-up gate for actuation.**
   The gate withholds an advisory only when its **sole** cause is learned
   prediction error with **no** concurrent hard-threshold breach. If
   `alert.is_alert` is true on the tick (a real limit is breached), the advisory is
   published and actuated normally — reduce_rate / shed / maintenance — even during
   warm-up. Likewise the fatigue accumulator integrates at **full** weight on any
   tick with a live hard-threshold breach. So a genuinely overheating GPU during
   warm-up still triggers the full protective response; only *model-ignorance*
   error is graced.

This carve-out is the crisp boundary: **warm-up gates learned-prediction-only
regulation; any concurrent absolute-threshold breach bypasses the gate.**

## 5. Observability (never a silent no-op)

Warm-up must be auditable. The design adds:

- A **`soma.warmup.started`** event (or a `warmup: true` field on the first
  `soma.report`) at boot, and a **`soma.warmup.completed`** event when the
  end-condition (§6) is met, carrying the samples-seen and lived-seconds that ended
  it.
- A **`soma.regulation.withheld`** observability event each time an advisory is
  suppressed by warm-up, carrying `{would_be_action, prediction_error,
  sustain_elapsed_s, reason: "warmup"}`. This is emitted on `soma.out` (a new,
  non-actuating event type the cycle engine ignores) **and** logged at INFO. The
  fatigue-dampening similarly logs each tick's damped-vs-raw contribution at DEBUG,
  and a single INFO line when the accumulator *would have crossed* but for warm-up.
- `soma.report` gains a `warmup_active` boolean so the Nexus dashboard and the
  research log can show the developmental stage without changing the numeric
  signal.

Nothing here filters or lowers the published `prediction_error` / `fatigue_value`.

## 6. Warm-up end condition (options + recommendation)

Mirroring the §6.6 precedent — *"a minimum of logged lived events **and** a minimum
of lived running time"* — the recommended end condition is a **conjunction** of two
readily-available Soma-local signals:

- **`samples_seen`** — the number of forward-model online-adaptation steps taken
  (i.e. `forward.step()` calls with a finite feature vector). This is the direct
  analogue of "logged lived events": it counts how much the model has actually
  learned from.
- **`lived_seconds`** — accumulated **subjective** time since boot (from the
  injected `EntityClock`, so it dilates coherently with the rest of the mind). The
  analogue of "lived running time".

**Recommended default:** warm-up ends when **both** `samples_seen ≥
regulation_warmup_min_samples` **and** `lived_seconds ≥
regulation_warmup_min_seconds`. Conjunction (not disjunction) is the conservative
choice: a paused or sensory-starved entity that logged few samples cannot age out
of warm-up on the clock alone, and a fast-sampling entity cannot age out before
enough wall/subjective time has passed. This is exactly the §6.6 shape.

### Alternatives considered

- **Error-stabilization gate** (rolling variance of the prediction-error window
  drops below a bound, or error stays below `regulation_threshold` for a sustained
  window). *Pro:* directly measures "the model has learned." *Con:* somewhat
  circular and gameable — a transient dip could end warm-up early, and the signal
  we are protecting against is the very thing we would gate on. **Recommendation:**
  offer it as an **optional additional guard** (an extra AND-term), default
  **off**, so operators who want empirical confirmation can require it without it
  being able to *shorten* the developmental window.
- **Samples-only or time-only.** Rejected as the default: each alone is trivially
  defeated (a paused entity, or a stalled sampler). Kept implicitly — setting the
  other knob to zero degrades to a single-signal gate for experimentation.

### Default values (conservative; final tuning is an open question)

The shakedown showed error above threshold for ~20 min, decaying to 0.14 by then.
Conservative defaults that comfortably cover that window (at the default
`read_interval_s = 1.0`, ~1 sample/s):

- `regulation_warmup_min_seconds = 1200.0` (20 min of lived subjective time)
- `regulation_warmup_min_samples = 1000` (≈17 min of samples at 1 Hz; the time gate
  is the binding one on a normally-paced boot)

These are illustrative; §9 lists the tuning question.

## 7. Config knobs (`[soma]`)

All new, additive; defaults chosen so the grace is on and conservative.

```toml
[soma]
# ... existing keys ...
# Developmental warm-up: while the interoceptive forward model is still
# learning this host's substrate baseline, withhold the PUNITIVE allostatic
# actions its (untrained) prediction error would trigger — the reduce_rate
# throttle, low-priority module shedding, and the fatigue inflation that forces
# premature maintenance. The prediction-error signal itself is still published
# and logged at full fidelity, and the absolute [soma.thresholds] limits are
# NEVER gated (a real substrate breach overrides warm-up). Grounded in the
# paper's warmed-up-signal logic (§6.6), applied to interoceptive regulation.
regulation_warmup_enabled = true
regulation_warmup_min_samples = 1000
regulation_warmup_min_seconds = 1200.0
# Optional additional AND-guard: require the prediction error to have stabilized
# before warm-up can end. Off by default (see design §6).
regulation_warmup_require_error_stabilized = false
regulation_warmup_stable_window = 32
regulation_warmup_stable_variance = 0.02
```

**Ship state.** `regulation_warmup_enabled` defaults to **`true`**. Rationale:
Soma's regulation itself ships *enabled* — it is active whenever the Soma module is
turned on (`[modules] soma`), with no separate gate flag — so the grace that tempers
regulation ships the same way. It is welfare-protective and consistent with the
"safety over UX / pick the safest design" rule, and it has **no substrate-safety
downside** because the hard thresholds still fire (§4). Setting it `false` restores
today's exact cold-start behavior. (The alternative — shipping it gated/`false` to
match the conservative posture of a brand-new predictive feature like
`chronos.forward_prediction = false` — is noted as an open question in §9.)

## 8. Where the emergent-not-hardwired citation goes

The grace is a **developmental stage**, not an innate hardcoded behavior, and must
be justified at the code site the way the individuation warm-up is. The future
implementer SHALL add a comment at the warm-up gate (in `regulation.py` /
`module.py`) citing paper §6.6 (the warmed-up-signal precedent) and §3.4.1 (Soma
allostatic regulation), stating that the developmental window is grounded in the
architecture's existing warmed-up-signal logic rather than an arbitrary constant —
mirroring the existing §-citations already present in `forward.py`.

## 9. Open questions / tradeoffs (for the operator)

1. **Fatigue-value fidelity vs. dampened accrual — DECIDED (Option A).** The gate
   dampens the *input* to the fatigue accumulator during warm-up, so the published
   `fatigue_value` honestly reflects reduced accrual (we change what fatigue *is*,
   not what we *report*). The raw `prediction_error` — the actual "cry" — is
   untouched and fully published/logged. This keeps the change Soma-contained (no
   Hypnos reach), and avoids a false cold-start crossing emitting a `soma.fatigue`
   welfare event. Rejected alternative (B): integrate the full error and gate only
   the *consequence* at the Hypnos trigger — more literally "full-fidelity
   fatigue_value," but touches Hypnos and lets false crossings fire. Operator
   decision, 2026-07-01: **Option A.**
2. **Default ship state:** `true` (recommended, matches Soma regulation's always-on
   posture and welfare-first) vs. `false` (matches the conservative "new predictive
   feature ships gated" posture, e.g. `chronos.forward_prediction`). 
3. **End-condition tuning:** are `min_seconds = 1200` / `min_samples = 1000` right,
   and should the error-stabilization guard be on by default? The shakedown is a
   single data point on one host; different substrates may warm up faster/slower.
4. **Does gating ever mask a real early substrate problem?** Addressed by §4 (the
   independent threshold path + the hard-threshold override). Operator should
   confirm the override is acceptable and that no protective response *other* than
   the gated advisories exists that would be lost during warm-up.
5. **Per-boot vs. per-fork warm-up.** A forked/time-dilated being also boots an
   untrained (or restored) readout. Should each fork run its own warm-up window on
   its own subjective clock? (The `EntityClock` injection already makes
   `lived_seconds` per-fork; confirm the sample counter resets per fork.)

## 10. Validation

`openspec validate soma-coldstart-regulation-warmup --strict` must pass. The spec
delta modifies the two affected `soma-predictive` requirements (advisory regulation,
fatigue accumulator) and adds the warm-up gate + observability requirements, each
with scenarios.
