# Design — attention-driven foveation

## The fovea target signal

Topos today emits whole-frame salience (change, habituation, forward-model
prediction error). Foveation needs a *spatial* target. Compute a coarse saliency
map by tiling the frame (e.g. an N×M grid, N,M ≈ 8–16) and scoring each tile by the
same quantities used per-frame:

- **change** — cosine distance of the tile's features to the previous frame's;
- **prediction error** — the tile's contribution to the Topos forward model's
  predicted-minus-actual latent (spatially localized, not just the frame scalar).

The **bottom-up** target is the argmax tile (its centre). A **top-down** bias is an
optional region supplied by the workspace / Nous / Empatheia (e.g. "attend to the
region where the speaking agent's face was"). The two combine by **precision
weighting** — the fovea target is the argmax of `w_bu · saliency + w_td · bias`,
where the weights are precisions, consistent with the precision-as-attentional-gain
the architecture already uses (Feldman and Friston 2010; Bastos et al. 2012). With
no top-down source the target is purely bottom-up (Phase 1).

**Fovea size from arousal — a distinct visual coupling.** Do not conflate this with
the existing Thymos→Syneidesis mechanism. That mechanism ("arousal widens the
attentional window," §3.4.3) is a *cognitive salience-selection* window inside the
workspace/Thymos graph — it scales salience scores and how hard the confidence
threshold is to clear, i.e. *which candidates* reach the workspace. It says nothing
about a spatial region of the visual field. Fovea size is a **new** coupling: the
Thymos arousal *value* is taken as an input and mapped onto the spatial extent of
the high-acuity crop. The grounding is the psychophysics of arousal and visual
attention — the Easterbrook (1959) cue-utilization effect, in which higher arousal
*narrows* the effective visual field (tunnel vision). The default mapping should
therefore make higher arousal a **tighter, higher-magnification** fovea, but the
exact function and its sign are a **tuning parameter**, not an asserted result, and
the coupling ships behind the same benchmark gate as the rest.

## Producing the two views

The tension: a high-res fovea needs a high-res source, which is the bandwidth we
are trying to avoid. Two construction options, staged:

1. **Single in-memory grab + crop (Phases 1–2).** Grab the whole screen once per
   tick at a *moderate* resolution (e.g. 1080p — one ffmpeg, bounded bandwidth).
   In-process (numpy/cv2), derive the peripheral (downsample to e.g. 320×180) and
   the foveal crop (an array slice around the target, scaled to the encoder's native
   patch). This alone gives the fovea ~1080p detail in the attended region versus a
   uniform 640×480 — a large acuity win at bounded, fixed cost, with no dynamic
   capture reconfiguration.
2. **Native region capture on saccade (Phase 3).** For true-native fovea detail, add
   a second capture pinned to the fovea region at native resolution
   (x11grab/gdigrab capture only that region's pixels, so it is cheap). Re-pin it
   **only on a saccade** — when the fovea target moves beyond a hysteresis threshold
   *and* a minimum dwell has elapsed — so any capture reconfiguration is amortized
   over a fixation, matching how the eye jumps and dwells rather than roaming. Any
   reconfiguration cost is thus paid a few times per second at most, not every tick.

Both keep the **zero-raw-sense-data invariant**: every grabbed frame, the
peripheral, and the crop live only in process memory and are released as they age
out; nothing touches disk. The existing static-grep guard
(`tests/test_zero_persistence_invariant.py`) must continue to pass — no new
`cv2.imwrite` / `VideoWriter` / raw-frame file path is introduced.

## Encoding and the report

Topos encodes both views: the peripheral → a gist/context latent, the foveal patch
→ a detail latent at the encoder's native size (efficient). The `topos.report`
carries both latents, each tagged `peripheral` / `foveal`, plus the **content-free
fovea location** (normalized `(x, y)` and size in `[0, 1]`) — never pixels. When
foveation is disabled the report is exactly today's single whole-frame latent.

Publishing the fovea, and having the forward model predict the *next* fovea, is the
concrete attention-schema step: the entity carries a model of where its own visual
attention is and will be.

## Cost

To be **benchmarked, not asserted**, on the host startup benchmark before the mode
may be enabled:

| | Uniform (today) | Foveated |
|---|---|---|
| Capture | full screen → 640×480 | 1080p grab (+ optional native fovea region on saccade) |
| Encoder | 1 × large uniform encode | 1 small peripheral + 1 native-size foveal encode |
| Acuity | low, everywhere | coarse periphery + near-native at the point of interest |

The claim to verify: two small encodes + an in-process crop fit the tick budget,
and the attended-region acuity beats the uniform downsample at equal-or-lower total
cost.

## Active-vision framing (why this is not a bolt-on)

The loop: bottom-up saliency proposes → precision-weighted selection with top-down →
the fovea moves (a covert eye movement = **epistemic action**, valued by Nous via
expected free energy) → the high-res fovea lowers prediction error where attended →
forward models update → next tick's saliency shifts. This is active inference over
where to look (Friston et al. 2012), realized with machinery the architecture
already builds. It strengthens the agency / embodiment indicators and the
attention-schema indicator, not just throughput.

## Embodiment tie-in

The paper's §3.4.6 Mundus continuous-control plan already names "gaze direction
decoupled from the body" as a clamped per-tick control scalar. The fovea-target
signal defined here is that gaze signal for the screen: in an embodied setting the
same target aims a real or virtual camera. This change should therefore publish the
fovea target in a form the future Mundus gaze scalar can consume directly (a
normalized 2-D target + size), so the two never diverge.

## Risks / open questions

- **Fovea thrashing.** The target could oscillate (kin to the loop-stability
  concern in §9). Damp with dwell/hysteresis, momentum (Topos already carries local
  recurrent state), and arousal-set size.
- **Spatial saliency touches the perception hot path.** Modest work, but benchmark
  it — the tiling and per-tile scoring run every emitted tick.
- **Multiple salient regions.** Start with a single fovea; top-k foveae is a later
  option (flagged).
- **Latency budget.** Two encodes + crop must fit ~100 ms; the cycle already
  benchmarks the host at startup, so this is measurable before enabling.

## Flags — operator decisions

Locked by the operator 2026-07-08:

1. **Capture resolution of the single grab: NATIVE** (up to 4K), kept configurable
   so the host benchmark can dial it back if it strains the tick.
2. **Phase 1 scope: INCLUDE top-down** — the workspace→Topos attention channel is
   built in Phase 1, not deferred.
3. **Fovea count: SINGLE.**
4. **Fovea size: AROUSAL-DRIVEN** (the distinct visual coupling above), sign per the
   Easterbrook narrowing default, mapping tunable.

Still open (Phase 3):

5. **Native region capture: build or defer** — the native single-grab crop of Phase
   1 may already be sharp enough; the second capture adds real complexity. Decide
   after the Phase 1 benchmark.

## Grounding

Foveal acuity fall-off and saccadic sampling (Yarbus 1967); active vision as a
task-driven sensing loop (Bajcsy 1988; Findlay and Gilchrist 2003); saccades as
epistemic action under active inference (Friston et al. 2012); precision as
attentional gain (Feldman and Friston 2010; Bastos et al. 2012 — already cited by
the paper); attention schema (Graziano and Webb 2015). The active-inference and
precision sources extend the paper's existing base; attention-schema is the route
to the indicator the paper currently marks unimplemented.
