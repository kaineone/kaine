# Tasks — attention-driven foveation

This change is **design-first**: this pass delivers the proposal, design, and spec
deltas only. No perception or Topos code is written here. Implementation is
**phased** and gated on the lead's review of the design and on the host benchmark
confirming the two-encode budget fits the tick.

**No pretend processes.** Foveation MUST NOT ship enabled until the spatial saliency
map, the fovea selection, and the dual-view encode genuinely run and are
benchmarked. Until then the shipped perception path is the existing uniform
downsample; selecting foveation before it is real fails honestly rather than
returning a fixed/centre fovea.

## 0. Operator decisions — DECIDED (locked by operator 2026-07-08)

- [x] 0.1 **Single grab at NATIVE resolution**, kept configurable so the benchmark
      can dial it back. (design.md §Flags 1)
- [x] 0.2 **Top-down bias is in Phase 1** (workspace→Topos attention channel built
      now, not deferred). (Flag 2)
- [x] 0.3 **Single fovea.** (Flag 3)
- [x] 0.4 **Fovea size is arousal-driven** — the distinct visual coupling
      (Easterbrook narrowing default, sign tunable), NOT the Syneidesis salience
      window. (Flag 4)
- [ ] 0.5 Phase 3 native region capture: build or defer — decide after the Phase 1
      benchmark. (Flag 5)
      *Deferred: an operator decision, not code. The Phase 1 benchmark (task 1.7)
      shows the native single-grab crop fits the tick with ~61 ms headroom; whether
      the extra native region capture is worth its complexity awaits the operator's
      call. Tasks 3.1/3.2 stay gated on this.*

## 1. Phase 1 — spatial saliency + fovea (bottom-up + top-down) + dual view

- [x] 1.1 Add a coarse spatial saliency map to Topos: tile the frame; per-tile
      change and forward-model prediction error; kept in memory only.
- [x] 1.2 A workspace→Topos attention channel: an optional top-down bias region
      (from Nous / Empatheia / a goal), injected without Topos importing the
      workspace (a provider/callback seam, like the affect seam).
      (`Topos.set_top_down_bias_provider` / `set_arousal_provider`.)
- [x] 1.3 Select the single fovea target as the argmax of the precision-weighted
      combination of bottom-up saliency and the top-down bias, with dwell/hysteresis
      to damp thrashing; fovea size from the Thymos arousal value (distinct visual
      coupling; Easterbrook-narrowing default sign, tunable).
- [x] 1.4 From a single in-memory grab, derive the peripheral (downsample) and the
      foveal crop (array slice → native patch); release frames as they age out
      (zero-persistence guard stays green). *Native-resolution delivery from the
      capture layer is wired in 1.6/benchmark below.*
- [x] 1.5 Encode both views; extend `topos.report` to carry peripheral + foveal
      latents + content-free fovea location `(x, y, size)`; keep whole-frame salience
      as a diagnostic and as the fallback when foveation is off.
- [x] 1.6 Config: a foveation toggle under `[topos]` (`foveation`, off by default)
      + tile grid, dwell/hysteresis, arousal→size range, peripheral/foveal geometry;
      and a `[perception_feed.screen].native` grab (detected via xrandr on X11, with
      an honest fallback + logged note when undetectable). Arousal seam wired at the
      composition root (`_wire_topos_arousal`); the top-down seam is built and tested
      but stays unwired until a real workspace region-of-interest signal exists (no
      pretend source).
- [x] 1.7 Host-benchmark (`scripts/bench_foveation.py`) of the two-encode +
      native-grab + crop cost vs the tick. Measured on this host at native 1080p:
      per-tick foveation compute ≈ 39 ms p95 (two-encode+saliency 37 ms + grab-read
      3 ms) vs the 100 ms 10 Hz tick → FITS, ~61 ms headroom. Grab p95 (~97 ms)
      reflects the 10 fps frame-arrival cadence, not compute (reported honestly).

## 2. Phase 2 — attention schema

- [x] 2.1 Publish a *predicted next fovea* from a small forward model (the attention
      schema); expose it content-free for the self-model and diagnostics.
      (`kaine/modules/topos/foveation.py:FoveaPredictor` — a constant-velocity
      forward model of the fovea trajectory; wired in
      `kaine/modules/topos/module.py:Topos.process_frame` which publishes
      `report["predicted_fovea"]` as a content-free `{x, y, size}` alongside the
      current fovea when foveation is on. Covered by
      `tests/test_foveation.py` (5 `FoveaPredictor` cases) and
      `tests/test_topos_module.py::test_attention_schema_predicts_toward_the_fovea_trajectory`.)

## 3. Phase 3 — saccadic native fovea

- [ ] 3.1 A second native-resolution region capture pinned to the fovea, re-pinned
      only on a saccade (threshold + dwell); no per-tick reconfiguration.
      *Deferred pending operator decision 0.5 (build or defer). This is a live,
      OS-level capture (x11grab/gdigrab region reconfiguration) that cannot be
      exercised without a real display/GPU, so it is not built speculatively — the
      Phase 1 native single-grab crop is the shipped foveal source until the
      operator elects to add the second capture.*
- [ ] 3.2 Frame foveation as explicit active inference: Nous selects saccades by
      expected free energy (epistemic value of looking there).
      *Deferred: gated on 3.1 and a cross-module Nous action-selection integration
      (expected-free-energy saccade valuation). Belongs to an active-vision change,
      not this perception-path change; no pretend EFE loop is shipped.*

## 4. Phase 4 — embodiment tie-in

- [ ] 4.1 Route the fovea target (normalized 2-D + size) into the future Mundus
      "gaze direction decoupled from the body" control scalar, so screen gaze and
      camera gaze share one mechanism.
      *Deferred: the fovea is already published in the Mundus-consumable form the
      design requires — a content-free normalized 2-D target + size
      (`FoveaTarget.to_dict()`). Actually *routing* it into Mundus's gaze channel
      is a cross-module embodiment integration: Mundus's `gaze_yaw`/`gaze_pitch`
      are bidirectional rate channels driven by the learned `MotorPolicy`
      (`kaine/modules/mundus/control_surface.py`), and wiring the screen fovea into
      them competes with that learner. That coupling belongs to the embodiment
      active-vision work, not this perception change. The forward-compatible signal
      shape exists now, so the two need not diverge.*

## 5. Docs / paper

- [x] 5.1 Update `docs/modules/topos.md` with the foveation path once implemented.
      (New "Attention-driven foveation (topos-foveation)" section documenting the
      per-tick pipeline, the injected top-down/arousal seams, the attention schema,
      and the report fields; plus `[topos]` config rows, the `foveation.py` key-file
      entry, the foveated-`topos.report` payload note, and the two foveation test
      rows.)
- [ ] 5.2 Note the attention-schema realization and active-vision framing for the
      paper's future-work / §5 indicator update (paper change, not code).
      *Deferred: an explicit paper change requiring the lead's review before it
      lands (per the review-before-publishing convention), out of scope for this
      code PR.*
