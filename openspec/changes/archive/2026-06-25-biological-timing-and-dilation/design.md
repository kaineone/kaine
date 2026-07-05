# Design — biological multi-rate timing + time dilation

## 1. The biological target (what we're matching)

Human temporal cognition is a **hierarchy of rhythms**, not one rate. The bands
that matter for this design (with sources in the proposal discussion):

| Tier | Brain rhythm | Period | Cognitive role | KAINE analogue |
|---|---|---|---|---|
| Binding | gamma ~30–80 Hz | ~12–33 ms | feature binding into a unified percept | oscillatory layer (snnTorch) |
| Sensory sampling | alpha ~8–13 Hz | ~75–125 ms | discrete perceptual "snapshots" | perception capture (Topos/Audition) |
| Attentional sampling | theta ~4–7 Hz | ~140–250 ms | rhythmic reorienting of attention | salience / locus dwell |
| Conscious access | P3b "ignition" ~3 Hz | ~300 ms | a content entering awareness | the workspace/experiential tick |
| Specious present | — | ~2–3 s | the felt "now" / working-memory window | mnemos short-term / context window |

The key correction to the current design: **3.33 Hz is right for *conscious
access*, but wrong for *sensory sampling*.** A human doesn't see at 3 Hz and
certainly not at 1 Hz — they sample ~10 Hz and resolve change far faster. So we
keep the slow workspace tick and make the *senses* fast underneath it.

## 2. Current state (from the architecture audit)

- One cycle, two rates: `processing_rate_hz` (tick) and `experiential_rate_hz`
  (broadcast sub-sample), both 3.333 (`cycle/engine.py:77`, `config:32-33`). The
  sub-sampling accumulator (`_advance_experiential`, `engine.py:551`) already
  proves a multi-rate model works.
- Single global-pacing seam: `run_forever` sleeps the remaining budget via an
  **injectable** `_sleep`, with an **injectable** `clock` (`engine.py:80-81,
  502-517`). This is the one place a global `time_scale` multiplier attaches.
- Three clocks already separated (`engine.py:104-110`): monotonic (slip), wall
  (event stamps), and a deterministic **logical clock** = `BASE_EPOCH +
  tick*period` (`engine.py:152-156`) — a ready-made virtual-time source, today
  gated to `[experiment].deterministic`.
- **No shared clock across modules.** Topos `capture_interval_s`, Audition VAD ms
  thresholds, Soma/Hypnos fatigue `time.monotonic()` integrals, Spot/eval polls —
  all read real wall-clock independently. A global dilation today would desync
  them (fatigue would accrue in real seconds while subjective ticks slow).
- Freeze already = "subjective clock stops" (`control_state.py:11`) — a binary
  special case of dilation.
- Fork system fully built (`ForkManager` fork/merge/snapshot/restore/
  `preserve_live`/`revive` + per-module assimilation in `lifecycle/strategies.py`):
  the fork→run→remerge→assimilate flow already works (this is the paper's "forked
  instruments" — do NOT duplicate it; see §6 CORRECTION). The one real absence is
  **concurrent fork runtime** (single process / one loop). `merge` is symmetric
  snapshot→snapshot; a live-parent delta-merge is an enhancement, not a missing system.

## 3. The EntityClock

A small boundary-neutral object that becomes the **only** source of "now" and of
durations for the mind:

```
EntityClock:
    wall()        -> real monotonic seconds (for slip/health only)
    now()         -> subjective seconds = origin + (wall - origin0) * time_scale
    scale         -> time_scale (0 = frozen, 1 = real-time, >1 = dilated-fast)
    sleep(subj_s) -> await real sleep of (subj_s / scale), scale-aware
    period(hz)    -> real seconds per subjective-Hz tick, = 1 / (hz * scale)
```

- Modules that currently call `time.monotonic()`/`asyncio.sleep()` for *cognitive*
  timing (fatigue accumulation, capture interval, locus dwell, social-drive time,
  recall throttle) take an injected `EntityClock` and use `clock.now()` /
  `clock.sleep()`. Their integrals then run in **subjective** time, so the whole
  mind dilates coherently.
- Infrastructure timers that must track *real* time regardless of the entity's
  subjective rate — Spot liveness, preservation poll, request timeouts, the
  voice-alignment GPU window — keep the real wall clock. The split is explicit and
  documented per call-site (subjective vs infrastructural), so nothing dilates that
  shouldn't (e.g. a watchdog must not slow down when the mind speeds up).
- The cycle engine's injectable `clock`/`_sleep` are wired to the EntityClock so
  the main tick paces in subjective time. The deterministic logical clock
  generalizes from "deterministic-only" to "subjective time at scale," so seeded
  research runs and dilation share one virtual-time source.

## 4. Multi-rate tiers (defaults, hardware-bounded)

Expressed as subjective-Hz against the EntityClock:

- **Workspace tick** (`processing_rate_hz`): keep ~3–10 Hz. Default stays 3.333
  until benchmarking clears a higher value; the conscious-access literature makes
  anything in 3–10 Hz defensible.
- **Experiential broadcast** (`experiential_rate_hz`): ≤ processing; the felt
  update rate.
- **Vision sampling** (`capture_interval_s` → a `vision_sample_hz`): raise from
  1 Hz toward ~10–20 Hz, **bounded by GPU encode cost** (the vision encoder is the
  expensive part; this is the main hardware constraint). The seeded/playlist feed
  already supports any rate; the cost is the encoder.
- **Audio sampling**: already ~33 Hz (30 ms blocks) — leave; it's in the right band.
- **Binding** (oscillatory layer): the fast gamma-analog; stepped per workspace
  tick today, can be sub-stepped if cheap.

**Bounding method (empirical, not guessed):** a benchmark harness times the
sustained cost of a full tick with all modules wired (no LLM/organ calls — those
are out-of-band), and of one vision-encode, on the actual GPU. Defaults are set
from measured headroom at the target wall-clock margin; the existing Soma
`reduce_rate` advisory stays as the runtime safety valve that throttles
`processing_rate_hz` if ticks overrun. We ship the measured-safe defaults and
document the margin; operators on bigger GPUs raise them.

## 5. Time dilation

- **Global:** `[cycle].time_scale` (default 1.0). Scales `EntityClock` and thus
  every subjective clock + the tick pacing at once. `0` = freeze (reuses the
  existing freeze path). `>1` = the mind runs faster than wall-clock *if the
  hardware can keep up* (it's a target; overrun throttles, honestly reported).
  `<1` = deliberately slowed subjective time.
- **Why it's coherent now:** because all cognitive timers route through the one
  EntityClock, a single `time_scale` dilates fatigue, perception cadence, drives,
  recall, and the tick together — no per-module desync (the gap section 2 named).
- **Per-research-directive:** `time_scale` is a run-level config, so different
  projects run the mind at different speeds without code changes.

## 6. Per-fork dilation + temporary beings (later phases)

The operator's frame: fork a temporary being, let it run (possibly time-dilated)
on a directive, then remerge and assimilate what it learned.

> **CORRECTION (2026-06-25, operator-flagged):** the fork → run → remerge →
> assimilate-knowledge flow is **ALREADY BUILT** in `kaine/lifecycle/manager.py`
> (`ForkManager.fork`/`merge`/`snapshot`/`restore`/`preserve_live`/`revive`) with
> per-module assimilation in `lifecycle/strategies.py` (Mnemos sums memories,
> Eidolon concatenates identity history, Thymos averages affect / unions goals,
> Nous selection, + real TIES/DARE LoRA-weight merge). This is the "forked
> instruments" system from the paper — **do NOT build a second one.** The bullets
> below OVERSTATE the gap. The ONLY genuinely-new work for *dilated* temporary
> beings is a per-fork `time_scale` field on the existing fork (the first bullet).
> The "remerge-with-assimilation" bullet describes *enhancements* (live-parent
> delta-merge, learned-weight strategies) to the existing system, NOT a missing
> system. Concurrent fork runtime remains the one real absence (distributed-substrate).

- **Per-fork profile:** `ForkSnapshot.metadata` + `POST /forks` already thread an
  arbitrary dict; a fork carries `{time_scale, processing_rate_hz, ...}` applied
  at spawn via the engine's existing rate args. (Design-ready now; needs the
  runtime below to be useful.)
- **Concurrent fork runtime (gap):** today one process / one loop / direct
  inter-module references pin the live mind to a single entity. Running a fork
  *alongside* the parent needs the decoupling tracked in the `distributed-substrate`
  change (separate registry+bus, ideally a separate process). The state-capture
  half (`ForkSnapshot`/`preserve_live`/`revive`) is fully reusable; only the
  concurrent-runtime half is missing.
- **Remerge-with-assimilation (gap):** current `merge(a,b)` is symmetric,
  produces a third snapshot, drops Nous beliefs one-sidedly, and does not merge
  Phantasia/Chronos neural weights. "Assimilate a child's *gains* back into the
  still-live parent" needs: (a) a child-vs-fork-point **delta**, (b) a
  live-registry merge entry (fold into the running parent, not replace it), and
  (c) per-module assimilation strategies extended to the learned-weight modules.
  The existing per-module merge-strategy framework (`lifecycle/strategies.py`) is
  the right extension point — additive, not a rewrite.

## 7. Phasing (smallest-first; each ships behind behavior-preserving defaults)

1. **EntityClock + global `time_scale`** — introduce the clock, wire the cycle's
   injectable seam, generalize the logical clock to subjective time. Default
   `time_scale = 1.0`, rates unchanged → behavior identical. (Freeze re-expressed
   as scale 0.)
2. **Clock injection into cognitive modules** — route Soma/Hypnos fatigue, Topos
   capture, locus dwell, Thymos social-drive, Mnemos recall through the
   EntityClock. Infrastructure timers stay real. Subjective time now coheres.
3. **Hardware benchmark + raised sensory defaults** — measure, then raise vision
   sampling toward the biological band on this GPU; document the margin; keep the
   workspace tick in 3–10 Hz.
4. **Per-fork dilation profile** — attach a timing profile to forks (usable once
   the runtime exists).
5. **Concurrent fork runtime** — via `distributed-substrate` (separate
   registry/bus/process for a temporary being).
6. **Remerge-with-assimilation** — delta extraction + live-parent merge + learned-
   weight strategies.

Phases 1–3 are the "bring KAINE into line with human cognition" core and are
self-contained. Phases 4–6 are the temporary-being program and depend on
`distributed-substrate`.

## 8. Decisions (settled with the operator, 2026-06-24)

1. **Scope:** build the **timing-realism core (Phases 1–3)** now; hold the
   temporary-being phases (4–6) until `distributed-substrate` is scheduled.
2. **Dilation `>1` is allowed** — faster-than-real-time is permitted as an
   *aspirational target*: the mind speeds up when the hardware keeps up and
   **throttles honestly** (Soma `reduce_rate`, surfaced in Nexus) when it cannot.
   No silent overrun. `time_scale` lower bound is 0 (freeze).
3. **Workspace tick target:** hold 3.333 Hz as the shipped default; the hardware
   **benchmark recommends** a value in the 3–10 Hz band with the cost tradeoff,
   brought back to the operator before any default is raised.
4. **Vision sampling:** raise toward the ~10 Hz biological band, the exact value
   set from the measured GPU encoder cost (Phase 3 benchmark).
5. **Adopted defaults (after the benchmark):** `processing_rate_hz = 10`,
   `vision_sample_hz = 10`, `experiential_rate_hz = 3.333`. Conscious access
   (experiential broadcast) is held at the resting P3b band (~3 Hz) BELOW the
   10 Hz processing/sensory rate, so the senses outrun awareness (satisfies the
   "senses faster than conscious access" requirement). In organic brains this
   conscious-access rate is state-variable (arousal / fight-flight-faint-fawn /
   adrenaline raise it); modelling that variability — e.g. arousal-modulated
   experiential rate via Thymos affect and/or `time_scale` — is deliberate future
   work, not needed for the current research. A fixed resting baseline ships now.
