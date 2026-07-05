## Why

`docs/kaine-paper.md` §3.1 places Topos as the spatial-awareness module:
"processes visual input through a frozen latent world model encoder,
specifically V-JEPA 2, and publishes latent vectors rather than text
descriptions." It is the third and final Phase 2 perception module; the
tag `v0.2-perception` ships once it lands.

Build prompt §2.3 prescribes the integration path: "If V-JEPA 2 is
available and fits RTX 3070 (8GB), integrate frozen encoder. If not,
use DINOv2 ViT-S/B as placeholder with clear upgrade path." DINOv2 is
the conservative choice — small (`facebook/dinov2-small` is 22M params,
~85 MB), Apache-2.0, no model-gating, and broadly supported by
`transformers`. V-JEPA 2 is the spec target but introduces freshness
risk; we ship DINOv2 by default and document V-JEPA 2 as a one-line
swap behind the `Encoder` protocol.

## What Changes

- Introduce `kaine.modules.topos` package split four files:
  - `encoder.py` — `Encoder` protocol with `encode(image) -> list[float]`
    plus `DINOv2Encoder` default loading `facebook/dinov2-small`. Lazy
    `transformers` import. Frozen network, eval mode, no grad. Picks
    its device through `select_device` so the operator can pin it (the
    build prompt's GPU-assignment freedom).
  - `change.py` — `ChangeDetector` protocol + `CosineChangeDetector`
    default. `change_score = 1 - cosine_similarity(prev, current)` per
    build prompt §2.3 "Change detection via cosine similarity."
  - `habituation.py` — `SceneHabituator` protocol +
    `RollingMeanHabituator` default. Tracks a rolling mean of embeddings;
    habituation rises as recent frames cluster around the mean. Build
    prompt §2.3 "Habituation for static scenes."
  - `module.py` — `Topos(BaseModule)` orchestrating the encoder +
    change + habituation. Exposes `process_frame(image)` as the entry
    point; frame source adapters (webcam, video file, future modules)
    call this. Publishes `topos.report` carrying the latent vector,
    change score, and habituation.
- Add `transformers>=4.40,<5` and `Pillow>=10,<12` to runtime deps.
  Both go through the existing dynamic install path; no new wheel-index
  branching needed.
- `[topos]` block in `config/kaine.toml` (encoder model id, device
  override, change/habituation thresholds, baseline/alert salience,
  habituation window). `modules.topos = false` so first boot remains
  operator-supervised.
- Tests use a fake `Encoder` that returns deterministic vectors keyed on
  pixel statistics, so the suite runs without a `transformers` download.
  One opt-in test loads real DINOv2 and asserts the encoder produces
  the expected 384-dim CLS vector — skipped unless
  `KAINE_TOPOS_RUN_REAL_ENCODER=1`.

## Capabilities

### New Capabilities

- `topos`: spatial perception. Owns the frozen vision encoder, latent
  publishing, cosine-similarity change detection, and static-scene
  habituation. `Encoder` is replaceable — DINOv2 ViT-S/14 is the v1
  default; V-JEPA 2 ViT-S can drop in by implementing the same
  protocol.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `dynamic-hardware`,
  optionally `cognitive-cycle` (it publishes through the bus like
  every other module). All shipped.
- **Repo:** adds `kaine/modules/topos/*.py`, `tests/test_topos_*`,
  updates `pyproject.toml` (`transformers`, `Pillow`, packages list),
  `config/kaine.toml`, `DEPENDENCIES.md`.
- **Disk:** DINOv2 small weights are ~85 MB; first init downloads
  them into the HF cache.
- **VRAM:** at default device selection on this host, Topos will pin to
  the operator's GPU preference. The 3070 budget (~6 GB free after
  Speaches+Chatterbox) easily fits DINOv2 small.
- **No runtime impact** on the cycle. Topos is registered in code paths
  but not auto-added to ModuleRegistry; first boot decides.

After this change Phase 2 closes and `v0.2-perception` is tagged on
main.
