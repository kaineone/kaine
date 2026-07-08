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

## 1. Phase 1 — spatial saliency + fovea (bottom-up + top-down) + dual view

- [ ] 1.1 Add a coarse spatial saliency map to Topos: tile the frame; per-tile
      change and forward-model prediction error; kept in memory only.
- [ ] 1.2 A workspace→Topos attention channel: an optional top-down bias region
      (from Nous / Empatheia / a goal), injected without Topos importing the
      workspace (a provider/callback seam, like the affect seam).
- [ ] 1.3 Select the single fovea target as the argmax of the precision-weighted
      combination of bottom-up saliency and the top-down bias, with dwell/hysteresis
      to damp thrashing; fovea size from the Thymos arousal value (distinct visual
      coupling; Easterbrook-narrowing default sign, tunable).
- [ ] 1.4 From a single NATIVE-resolution in-memory grab, derive the peripheral
      (downsample) and the foveal crop (array slice → native patch); release frames
      as they age out (zero-persistence guard stays green).
- [ ] 1.5 Encode both views; extend `topos.report` to carry peripheral + foveal
      latents + content-free fovea location `(x, y, size)`; keep whole-frame salience
      as a diagnostic and as the fallback when foveation is off.
- [ ] 1.6 Config: a foveation toggle under `[topos]`/`[perception_feed]`, off by
      default; grab resolution (native default), tile grid, dwell/hysteresis, the
      arousal→size mapping.
- [ ] 1.7 Host-benchmark the two-encode + native-grab + crop cost against the tick
      budget; gate enabling on it. Report a NULL/regression result honestly, and
      dial grab resolution back if native strains the budget.

## 2. Phase 2 — attention schema

- [ ] 2.1 Publish a *predicted next fovea* from a small forward model (the attention
      schema); expose it content-free for the self-model and diagnostics.

## 3. Phase 3 — saccadic native fovea

- [ ] 3.1 A second native-resolution region capture pinned to the fovea, re-pinned
      only on a saccade (threshold + dwell); no per-tick reconfiguration.
- [ ] 3.2 Frame foveation as explicit active inference: Nous selects saccades by
      expected free energy (epistemic value of looking there).

## 4. Phase 4 — embodiment tie-in

- [ ] 4.1 Route the fovea target (normalized 2-D + size) into the future Mundus
      "gaze direction decoupled from the body" control scalar, so screen gaze and
      camera gaze share one mechanism.

## 5. Docs / paper

- [ ] 5.1 Update `docs/modules/topos.md` with the foveation path once implemented.
- [ ] 5.2 Note the attention-schema realization and active-vision framing for the
      paper's future-work / §5 indicator update (paper change, not code).
