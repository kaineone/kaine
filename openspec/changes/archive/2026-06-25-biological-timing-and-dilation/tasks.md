# Tasks — biological multi-rate timing + time-dilation (Phases 1–3)

Phases 4–6 (per-fork dilation, concurrent fork runtime, remerge-with-assimilation)
are roadmap in `design.md` and are NOT in scope here — they depend on
`distributed-substrate`.

## Phase 1 — EntityClock + global time_scale (behavior-preserving)
- [x] 1.1 Add a boundary-neutral `EntityClock` (`kaine/entity_clock.py` or similar):
      `wall()`, `now()` (subjective), `scale`, `sleep(subjective_s)`, `period(hz)`;
      `scale=0` → frozen semantics; injectable real-clock + sleep for tests.
- [x] 1.2 Wire `CognitiveCycle` pacing through the EntityClock via its existing
      injectable `clock`/`_sleep` seam; generalize the deterministic logical clock
      to "subjective time at scale" (one virtual-time source for seeded + dilated).
- [x] 1.3 Add `[cycle].time_scale` (default 1.0); plumb through cycle construction.
      `0` reuses the existing freeze/suspend path; `>1` is a target (Phase 3 wires
      the throttle/report). Route ALL rate changes through one setter so the
      pacing period and logical period never diverge (fixes the existing
      `reduce_rate` vs `set_processing_rate` inconsistency).
- [x] 1.4 Tests: subjective-time math, scale=0 freeze, scale=0.5 halves pacing,
      logical-clock determinism preserved at scale 1.0, behavior-identical default.

## Phase 2 — Clock injection into cognitive modules
- [x] 2.1 Route the cognitive wall-clock reads through the injected EntityClock:
      Soma fatigue integral + interoception interval, Hypnos sleep/fatigue timing
      (RestScheduler sleep-due/deferral), Topos capture cadence, perception locus
      dwell, Thymos drift/publish/social-drive time scale, Mnemos recall throttle.
      (Eidolon's only wall reads are persisted event stamps + the save cadence —
      both infrastructural, annotated; it has no cognitive duration/cadence timer,
      its drift is per-tick via on_workspace and so already paces with the cycle.)
- [x] 2.2 Leave infrastructure timers on the real wall clock and annotate each
      (Spot watchdog, request timeouts, voice-alignment GPU window, Eidolon save
      cadence + event stamps, Topos desired-state poll, Hypnos pipeline latency).
      Added a test asserting the infra timers (Spot poll, request timeout) do NOT
      scale with time_scale and the cognitive ones (Soma fatigue, Topos cadence) DO.
- [x] 2.3 Inject the shared clock at boot (`build_registry`) so every cognitive
      module gets the same instance (also exposed on the registry so the cycle
      reuses it; Spot's rebuild path re-injects it); import boundaries stay green.

## Phase 3 — Hardware benchmark + biologically-raised sensory rates
- [x] 3.1 Build a repeatable benchmark harness: measure sustained per-tick cost
      with all modules wired (no LLM/organ calls) and per-vision-encode cost on the
      target accelerator; report achievable rates + margin. (Extends the Tier-1
      smoke; no entity boot, no cognition.) — `scripts/timing_benchmark.py`:
      deterministic ticks with lingua/vox disabled + `volition=None` (no LLM, no
      effector); times the DINOv2 encode on one seeded frame; re-runnable on any
      host (reads the same config, no hardcoded paths).
- [x] 3.2 Decouple the perception sample rate from the workspace tick; add a
      `vision_sample_hz` (subjective) and raise the default from 1 Hz toward the
      measured ~10 Hz biological band. Audio (~33 Hz) already in band. — Added
      `LiveCameraConfig.vision_sample_hz` / `interval_from_hz`; boot accepts a
      `vision_sample_hz` knob (wins over `capture_interval_s`). DEFAULT HELD at
      1 Hz (behavior-preserving) — the benchmarked raise is the operator's call.
- [x] 3.3 Wire the `>1` time_scale throttle: when the target rate overruns, reduce
      via Soma `reduce_rate` and surface achieved-rate/slip in Nexus (no silent
      overrun). — `CognitiveCycle.pacing_stats` (rolling target-vs-achieved rate +
      slip + `overrunning`), surfaced in runtime.json + a Nexus `cycle_pacing`
      health block (holding/throttling). Soma `reduce_rate` path unchanged (already
      routes through the single rate setter).
- [x] 3.4 Run the benchmark on this host; bring a recommended workspace-tick value
      (3–10 Hz band) + vision rate back to the operator BEFORE raising shipped
      defaults. Ship behavior-preserving defaults until approved. — Ran on an
      RTX 4070 SUPER: per-tick p95 ≈ 44–46 ms (max sustainable ≈ 17 Hz → recommend
      10 Hz, the band ceiling); per-encode p95 ≈ 8 ms (max sustainable ≈ 95 Hz →
      recommend 10 Hz, the biological target). Numbers brought to the operator;
      shipped defaults (3.333 Hz / 1 Hz) left UNCHANGED pending approval.

## Verify (each phase)
- [x] V.1 `openspec validate biological-timing-and-dilation --strict`. — valid.
- [x] V.2 Full suite green (`.venv/bin/pytest -q -p no:cacheprovider`),
      `lint-imports` green, no entity booted. — 2502 passed, 15 skipped;
      lint-imports 4 contracts kept; benchmark is a dry probe (organ off, no
      Volition), not an entity boot.
- [x] V.3 Each phase ships behind behavior-preserving defaults (time_scale=1.0,
      shipped rates) — confirm the default-inert scenario holds. — `time_scale=1.0`,
      `processing_rate_hz=3.333`, `capture_interval_s=1.0` all unchanged; the
      pacing report is inert (overrunning=False) at the sustainable default.
