# InternVideo-Next GPU shakedown

Validated record of the first real-weights forward pass of the Topos
InternVideo-Next clip encoder, and the salience calibration derived from it. This
closes the deferred tasks §5.1 / §5.2 / §7.2 of the `topos-temporal-video-encoder`
change, which shipped with the real forward pass un-exercised and
`change_alert_threshold` carried over from DINOv2 as a flagged placeholder.

- Date: 2026-07-10
- Hardware: NVIDIA RTX 4070 SUPER (pinned via `CUDA_VISIBLE_DEVICES=0`)
- torch 2.11.0+cu128, CUDA 12.8, transformers 4.x; `[internvideo]` deps
  `einops`, `timm`, `easydict` installed (plus a matching `torchvision`
  `0.26.0+cu128` that `timm` pulls in — the PyPI default wheel mismatches this
  torch's ABI and must come from the cu128 index).
- Model: `revliter/internvideo_next_base_p14_res224_f16`, MIT, vendored +
  revision-pinned (`ff2659b9…`); ~182 MB fp16 weights fetched once via
  `python -m kaine.setup.internvideo_next --yes` into
  `state/models/internvideo_next_base_p14_res224_f16/` (git-ignored).

## How it ran without flash_attn

No prebuilt `flash-attn` wheel exists for torch 2.11 / cu128; the source build
needs a long nvcc compile, so it was **not** installed. The vendored modeling code
(kept byte-identical to upstream by policy) hard-imports `flash_attn` at module top
level and defaults the backbone to `use_flash_attn=True`, but it also carries a
complete **eager** path (`Attention._naive_attn`, plain `Mlp`, local `RMSNorm`)
selected by `use_flash_attn=False`. The eager and fused configs share identical
parameter names (`qkv`/`proj`, `fc1`/`fc2`, `RMSNorm.weight`), so the real fp16
checkpoint loads into the eager model with **zero** missing / unexpected /
mismatched keys (91.0M params), and `_naive_attn` computes standard
scaled-dot-product attention over the real trained weights.

The run used a **local, uncommitted** shim (a `sitecustomize.py` on `PYTHONPATH`,
never added to the tree) that (1) registers a stub `flash_attn` package so the
vendored module imports — the stubbed names are only referenced, never called, on
the eager path — and (2) wraps the offline loader's `_import_vendored_classes` to
force `use_flash_attn = use_fused_rmsnorm = use_fused_mlp = False`. The vendored
files and the committed loader were **not** edited to achieve this. A production
run on a host with a real `flash_attn` build needs neither the stub nor the force.

## Real-path fix found

The shipped loader read the model **config** from the weights dir, but the setup
step fetches only `model.safetensors` there — `config.json` is **vendored**
in-tree (`external/internvideo_next/config.json`) and is never downloaded. The real
load therefore failed (`'InternVideoNextConfig' object has no attribute
'model_config'`). Fixed in `kaine/modules/topos/internvideo_next_loader.py`: the
config now loads from `vendored_code_dir()` (reviewed, pinned, in-tree — exactly as
the VideoMAE processor already does), and only the weights load from the fetch dir
with that config passed in explicitly. This was masked before because every test
injects fakes; it is the kind of gap the shakedown exists to catch.

## Measured forward pass (attention pooling, the shipped default)

- Output: **768-dim** pooled clip vector from a 16-frame 224×224 clip; all-finite,
  not L2-normalized (habituation / forward-model signals use its magnitude).
- Encode latency (GPU 0, fp16, eager, batch 1): **median ~78 ms/clip** (p90 ~86 ms).
  End-to-end over the seeded feed including frame synthesis + CPU forward-model:
  ~105 ms/clip.
- Peak VRAM: **~1.06 GB allocated / ~1.10 GB reserved** (weights + activations).
- Model load: ~1.8 s on GPU 0.

## Salience calibration (seeded feed, deterministic)

Driven end-to-end through the real `Topos.process_frame` (real encoder,
`forward_prediction=True`, `clip_stride=3`) over the in-repo deterministic
`SeededProceduralSource` (seed = 0, 640×480, `surprise_interval=150`,
`surprise_strength=1.0`), 900 frames → 295 clip reports. Reproducible provenance:
seed 0, 900 frames, surprises at frames 150/300/450/600/750.

**Finding — the cosine `change_score` is heavily compressed on attention-pooled
InternVideo-Next embeddings:**

| stimulus | cosine change (`1 − cos`) |
|---|---|
| routine overlapping clips (13/16 shared, stride 3) | ~0.00001 |
| same smooth world, far apart | ~0.0003 |
| clip containing a surprise blob | ~0.0004 |
| black ↔ white hard flash | ~0.008 |
| red ↔ green colour cut | ~0.015 |
| natural feed ↔ solid colour (total content change) | ~0.041–0.043 |

Full-feed `change_score`: p90 = 0.0000, p99 = 0.0003, **max 0.0004**. The global
attention-pooled vector is highly **direction-stable**; the encoder's entire cosine
"scene-change" dynamic range tops out near ~0.04 for completely different content.
The DINOv2-era **0.5 was unreachable** (never fired — ~12× above even a total
content change). Mean pooling is ~3–4× less compressed (content change ~0.14) but
the shipped default is attention pooling and was not changed here.

The informative salience signal on this feed is the **forward-model prediction
error** (L2 over the un-normalized 768-d embedding): mean ~28.6, range 27.5–31.6;
normalized to the rolling-window mean it reached exactly the 2.0× alert factor once
(the sole alert, 0.3% of reports), consistent with the design leaving that factor
at 2.0. Habituation stayed in a healthy 0.66–1.0 band.

**Calibrated value:** `change_alert_threshold = 0.005` (was 0.5). It sits in the
empirical gap — >10× above the seeded feed's routine floor (≤0.0004, so routine
motion stays baseline) yet below the weakest genuine cut (~0.008), so real scene
changes alert. On the smooth seeded feed the change path stays quiet by design (it
has no scene cuts); surprises there are carried by the prediction-error path.
`baseline_salience = 0.2` / `alert_salience = 0.7` were re-verified and left
unchanged. Because the seeded feed is a continuous world with no genuine cuts, a
naive "90th-percentile of observed change" (≈0) is not usable; the threshold is
instead anchored between the measured routine floor and the encoder's measured
scene-cut scale. This value is calibrated on the smooth synthetic feed — real
camera footage is noisier, so it is a defensible starting point to revisit against
live video, not a final constant.
