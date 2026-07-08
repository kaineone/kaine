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

## 0. Operator decisions — PENDING (see design.md §Flags)

- [ ] 0.1 Capture-resolution ceiling for the single grab (suggest 1080p).
- [ ] 0.2 Phase 3 native region capture: build, or defer if single-grab-crop is
      sharp enough in practice.
- [ ] 0.3 Phase 1 scope: bottom-up only, or include top-down from day one.
- [ ] 0.4 Single fovea vs top-k.
- [ ] 0.5 Fovea size: arousal-driven (reuses Thymos) vs fixed configured size.

## 1. Phase 1 — spatial saliency + bottom-up fovea + dual view

- [ ] 1.1 Add a coarse spatial saliency map to Topos: tile the frame; per-tile
      change and forward-model prediction error; kept in memory only.
- [ ] 1.2 Select the bottom-up fovea target as the saliency argmax (tile centre),
      with dwell/hysteresis to damp thrashing.
- [ ] 1.3 From a single moderate-resolution in-memory grab, derive the peripheral
      (downsample) and the foveal crop (array slice → native patch); release frames
      as they age out (zero-persistence guard stays green).
- [ ] 1.4 Encode both views; extend `topos.report` to carry peripheral + foveal
      latents + content-free fovea location `(x, y, size)`; keep whole-frame salience
      as a diagnostic and as the fallback when foveation is off.
- [ ] 1.5 Config: a foveation toggle under `[topos]`/`[perception_feed]`, off by
      default; grab resolution, tile grid, dwell/hysteresis.
- [ ] 1.6 Host-benchmark the two-encode + crop cost against the tick budget; gate
      enabling on it. Report a NULL/regression result honestly.

## 2. Phase 2 — top-down bias + attention schema

- [ ] 2.1 A workspace→Topos attention channel: an optional top-down region (from
      Nous / Empatheia / a goal) as a bias map.
- [ ] 2.2 Combine bottom-up saliency and top-down bias under precision weighting;
      map Thymos arousal onto fovea size.
- [ ] 2.3 Publish a *predicted next fovea* from a small forward model (the attention
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
