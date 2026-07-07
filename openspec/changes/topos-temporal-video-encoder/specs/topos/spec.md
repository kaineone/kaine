## MODIFIED Requirements

### Requirement: Encoder is replaceable via the Encoder protocol
Topos SHALL accept an `Encoder` collaborator that exposes `clip_len` (the number
of frames it consumes) and `async encode_clip(frames) -> list[float]` (encode a
clip of exactly `clip_len` frames to one pooled vector). The default encoder SHALL
be a **temporally-native video encoder** (InternVideo-Next base, `clip_len = 16`)
that returns a **768-dim** pooled clip embedding. The default encoder id and
backend SHALL be configurable. The returned vector SHALL be deterministic for the
same clip of frames. A per-frame encoder MAY implement the protocol with
`clip_len = 1`.

#### Scenario: Custom clip encoder substitutes cleanly
- **WHEN** Topos is constructed with a custom `Encoder` whose `encode_clip`
  returns a constant vector
- **THEN** every published `topos.report` carries that vector as `latent`

#### Scenario: Default encoder is temporally-native and 768-dim
- **WHEN** the default encoder is used
- **THEN** its `clip_len == 16` and each published report's `latent` has length
  `768`
- **AND** the report's `encoder_model_id` is the configured InternVideo-Next id,
  not a `facebook/`-namespaced id

### Requirement: Topos publishes topos.report for each processed frame
Topos SHALL maintain a bounded, RAM-only ring buffer of the most recent frames of
size `clip_len`. Topos SHALL publish a `topos.report` event to its `topos.out`
stream when the ring buffer is full AND a clip latent is produced on the clip
cadence (see the strided-clip requirement) — NOT once per incoming frame. Before
the ring buffer first fills, Topos SHALL publish no `topos.report`. Each published
event SHALL carry `latent` (list of floats — the pooled clip embedding),
`change_score` (float `>= 0`), `habituation_score` (float in `[0.0, 1.0]`),
`encoder_model_id` (string), and `prediction_error` (float). Salience SHALL be
elevated when `change_score` exceeds the configured alert threshold (or, when the
forward model is enabled, when the normalized prediction error is surprising).

#### Scenario: No report until the buffer fills
- **WHEN** fewer than `clip_len` frames have been processed after initialization
- **THEN** no `topos.report` event has been published

#### Scenario: A produced clip latent yields one report
- **WHEN** the ring buffer is full and a clip latent is produced on the cadence
- **THEN** exactly one `topos.report` event appears on `topos.out` carrying the
  768-dim `latent`, `change_score`, `habituation_score`, `encoder_model_id`, and
  `prediction_error`

#### Scenario: Large change elevates salience
- **WHEN** two produced clip latents are orthogonal and the change exceeds the
  configured alert threshold
- **THEN** the second event's salience equals the configured alert salience

### Requirement: Frozen encoder, no training in Topos
The default encoder SHALL load its underlying torch model in `eval()` mode with
`requires_grad_(False)` on every parameter, and Topos SHALL never call `.train()`
or any optimizer on the encoder. The encoder SHALL load ONLY from vendored,
revision-pinned modeling code and locally cached weights: it SHALL NOT pass
`trust_remote_code=True` and SHALL NOT fetch code or weights from a remote host at
runtime.

#### Scenario: Encoder parameters require no gradient
- **WHEN** the default encoder is initialized
- **THEN** every parameter of the underlying torch model returns
  `requires_grad == False`

#### Scenario: No remote code execution at load
- **WHEN** the default encoder loads
- **THEN** it does so from a local directory with `trust_remote_code=False` and
  performs no network access

### Requirement: Default Topos config and disabled-by-default
The repository SHALL ship a `[topos]` section in `config/kaine.toml` with default
values for the encoder backend/id, the pinned encoder revision, the local weights
directory, `clip_len`, `clip_stride`, clip resolution, pooling, device,
`change_alert_threshold`, `baseline_salience`, and `alert_salience`. The shipped
default `encoder_model_id` SHALL be the InternVideo-Next id and SHALL NOT be
`facebook/dinov2-small` (no Meta-owned model in the default configuration). The
`[modules].topos = false` flag SHALL keep first boot from auto-registering Topos.

#### Scenario: kaine.toml carries the temporal-encoder defaults and no Meta model
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** the `[topos]` section names the InternVideo-Next encoder with a pinned
  revision, `clip_len`, `clip_stride`, and pooling, contains no
  `facebook/`-namespaced model id, and `[modules].topos == false`

## ADDED Requirements

### Requirement: Clip latent produced on a strided sliding window
Topos SHALL produce a clip latent by encoding the most recent `clip_len` frames
every `clip_stride` frame-ticks (a strided sliding window). The default
`clip_stride` SHALL align the clip-latent cadence with the experiential /
conscious-access rate (~3.33 Hz at the shipped 10 Hz vision sampling), and SHALL
be operator-configurable. The stride SHALL be counted in frame-ticks so the clip
cadence dilates with the EntityClock `time_scale` without additional clock wiring.

#### Scenario: One clip latent per stride, not per frame
- **WHEN** `clip_stride` frames arrive after the buffer is full
- **THEN** exactly one clip latent is produced and one `topos.report` is published

#### Scenario: Cadence dilates with the entity clock
- **WHEN** the EntityClock `time_scale` changes
- **THEN** the real-time interval between clip latents scales with it, because the
  stride is counted in (already-dilated) frame-ticks

### Requirement: The frame ring buffer is RAM-only and never persisted
The `clip_len`-frame ring buffer SHALL exist only in process memory. It SHALL
never be written to disk, and it SHALL NOT appear in `Topos.serialize()` output.
Each frame SHALL be released when it ages out of the bounded buffer, preserving
the zero-raw-sense-data persistence invariant.

#### Scenario: Buffer absent from serialized state
- **WHEN** `Topos.serialize()` is called with a partially or fully filled ring
  buffer
- **THEN** the returned state contains no raw frames and no raw clip-buffer data

### Requirement: The temporally-native encoder loads only vendored, pinned code
The InternVideo-Next modeling code SHALL be vendored into the repository under
`external/internvideo_next/` with an `UPSTREAM` provenance record (upstream repo,
pinned commit SHA, MIT license text, vendoring-path decision), following the
`external/dreamerv3` convention. The runtime SHALL load the encoder from that
vendored code and from locally cached weights fetched at the pinned revision; the
vendored-code revision and the weights revision SHALL match, and a mismatch SHALL
be a load-time error.

#### Scenario: Provenance record present and pinned
- **WHEN** the vendored encoder is inspected
- **THEN** `external/internvideo_next/UPSTREAM` records the upstream repo, a pinned
  commit SHA, the MIT license, and the vendoring decision

#### Scenario: Revision mismatch fails closed
- **WHEN** the locally cached weights revision does not match the vendored-code
  pinned revision
- **THEN** encoder load raises a clear error rather than loading mismatched code
  and weights
