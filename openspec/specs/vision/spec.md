# vision Specification

## Purpose
The vision module is KAINE's visual perception module. This capability covers its RAM-only frame buffer, the frozen, replaceable video encoder that turns clips into latents, change detection and habituation, and the `vision.report` events it publishes.

## Requirements

### Requirement: Vision publishes vision.report for each processed frame
The vision module SHALL maintain a bounded, RAM-only ring buffer of the most recent frames of
size `clip_len`. The vision module SHALL publish a `vision.report` event to its `vision.out`
stream when the ring buffer is full AND a clip latent is produced on the clip
cadence (see the strided-clip requirement) — NOT once per incoming frame. Before
the ring buffer first fills, the vision module SHALL publish no `vision.report`. Each published
event SHALL carry `latent` (list of floats — the pooled clip embedding, or null
when the embedding holds a non-finite value), `change_score` (float `>= 0`),
`habituation_score` (float in `[0.0, 1.0]`, or null when the first finite
embedding has not yet been seen), `encoder_model_id` (string), and
`prediction_error` (float, or null when the report has no defined error). With
foveation on, `peripheral` and `foveal` SHALL likewise be null when they hold a
non-finite value. Salience SHALL be
elevated when `change_score` exceeds the configured alert threshold (or, when the
forward model is enabled, when the normalized prediction error is surprising).

#### Scenario: No report until the buffer fills
- **WHEN** fewer than `clip_len` frames have been processed after initialization
- **THEN** no `vision.report` event has been published

#### Scenario: A produced clip latent yields one report
- **WHEN** the ring buffer is full and a clip latent is produced on the cadence
- **THEN** exactly one `vision.report` event appears on `vision.out` carrying the
  768-dim `latent`, `change_score`, `habituation_score`, `encoder_model_id`, and
  `prediction_error`

#### Scenario: Large change elevates salience
- **WHEN** two produced clip latents are orthogonal and the change exceeds the
  configured alert threshold
- **THEN** the second event's salience equals the configured alert salience

#### Scenario: A non-finite embedding is published as null
- **WHEN** the produced clip latent contains a non-finite value
- **THEN** the report carries `latent` and `prediction_error` as null and no non-finite number

### Requirement: Encoder is replaceable via the Encoder protocol
The vision module SHALL accept an `Encoder` collaborator that exposes `clip_len` (the number
of frames it consumes) and `async encode_clip(frames) -> list[float]` (encode a
clip of exactly `clip_len` frames to one pooled vector). The default encoder SHALL
be a **temporally-native video encoder** (InternVideo-Next base, `clip_len = 16`)
that returns a **768-dim** pooled clip embedding. The default encoder id and
backend SHALL be configurable. The returned vector SHALL be deterministic for the
same clip of frames. A per-frame encoder MAY implement the protocol with
`clip_len = 1`.

#### Scenario: Custom clip encoder substitutes cleanly
- **WHEN** the vision module is constructed with a custom `Encoder` whose `encode_clip`
  returns a constant vector
- **THEN** every published `vision.report` carries that vector as `latent`

#### Scenario: Default encoder is temporally-native and 768-dim
- **WHEN** the default encoder is used
- **THEN** its `clip_len == 16` and each published report's `latent` has length
  `768`
- **AND** the report's `encoder_model_id` is the configured InternVideo-Next id,
  not a `facebook/`-namespaced id

### Requirement: Cosine-similarity change detection
The default `CosineChangeDetector` SHALL compute
`change_score = 1 - cosine_similarity(previous, current)`. The first
frame after initialization SHALL produce `change_score = 0` (no
previous frame to compare against). Identical consecutive frames
SHALL produce `change_score = 0`. Orthogonal frames SHALL produce
`change_score = 1`. Anti-correlated frames SHALL produce
`change_score = 2`.

#### Scenario: First frame yields zero change
- **WHEN** the vision module processes one frame after initialization
- **THEN** the report's `change_score == 0.0`

#### Scenario: Repeated identical frames yield zero change
- **WHEN** the same image is processed twice in sequence
- **THEN** the second report's `change_score == 0.0`

#### Scenario: Orthogonal embeddings yield change_score 1
- **WHEN** two frames produce vectors `[1, 0]` and `[0, 1]`
- **THEN** the second report's `change_score == 1.0`

### Requirement: Habituation rises as scenes stabilize
The default `RollingMeanHabituator` SHALL maintain a rolling window of
recent embeddings and SHALL report `habituation_score` in `[0.0, 1.0]`.
Score 1.0 corresponds to a fully static scene (all recent embeddings
identical); score near 0.0 corresponds to a maximally changing scene.

#### Scenario: Identical frames produce habituation approaching 1.0
- **WHEN** the same frame is processed 8 times in a window of 16
- **THEN** the eighth report's `habituation_score >= 0.9`

#### Scenario: Highly varied frames produce low habituation
- **WHEN** 8 mutually orthogonal frames are processed in a window of 16
- **THEN** the eighth report's `habituation_score <= 0.5`

### Requirement: Frozen encoder, no training in Vision
The default encoder SHALL load its underlying torch model in `eval()` mode with
`requires_grad_(False)` on every parameter, and the vision module SHALL never call `.train()`
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

### Requirement: Device selection through dynamic-hardware
The default `DINOv2Encoder` SHALL resolve its device through
`kaine.hardware.select_device(preferred)`, where `preferred` comes
from `[vision].device` in `config/kaine.toml` (`auto`, `cpu`, `cuda`,
`mps`). `KAINE_FORCE_DEVICE` env-var override SHALL be honored.

#### Scenario: Preferred device honored when available
- **WHEN** `[vision].device = "cpu"` is configured
- **THEN** the encoder's tensors live on `cpu` even on a CUDA host

### Requirement: Default Vision config and disabled-by-default
The repository SHALL ship a `[vision]` section in `config/kaine.toml` with default
values for the encoder backend/id, the pinned encoder revision, the local weights
directory, `clip_len`, `clip_stride`, clip resolution, pooling, device,
`change_alert_threshold`, `baseline_salience`, and `alert_salience`. The shipped
default `encoder_model_id` SHALL be the InternVideo-Next id and SHALL NOT be
`facebook/dinov2-small` (no Meta-owned model in the default configuration). The
`[modules].vision = false` flag SHALL keep first boot from auto-registering the vision module.

#### Scenario: kaine.toml carries the temporal-encoder defaults and no Meta model
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** the `[vision]` section names the InternVideo-Next encoder with a pinned
  revision, `clip_len`, `clip_stride`, and pooling, contains no
  `facebook/`-namespaced model id, and `[modules].vision == false`

### Requirement: Clip latent produced on a strided sliding window
The vision module SHALL produce a clip latent by encoding the most recent `clip_len` frames
every `clip_stride` frame-ticks (a strided sliding window). The default
`clip_stride` SHALL align the clip-latent cadence with the experiential /
conscious-access rate (~3.33 Hz at the shipped 10 Hz vision sampling), and SHALL
be operator-configurable. The stride SHALL be counted in frame-ticks so the clip
cadence dilates with the EntityClock `time_scale` without additional clock wiring.

#### Scenario: One clip latent per stride, not per frame
- **WHEN** `clip_stride` frames arrive after the buffer is full
- **THEN** exactly one clip latent is produced and one `vision.report` is published

#### Scenario: Cadence dilates with the entity clock
- **WHEN** the EntityClock `time_scale` changes
- **THEN** the real-time interval between clip latents scales with it, because the
  stride is counted in (already-dilated) frame-ticks

### Requirement: The frame ring buffer is RAM-only and never persisted
The `clip_len`-frame ring buffer SHALL exist only in process memory. It SHALL
never be written to disk, and it SHALL NOT appear in `Vision.serialize()` output.
Each frame SHALL be released when it ages out of the bounded buffer, preserving
the zero-raw-sense-data persistence invariant.

#### Scenario: Buffer absent from serialized state
- **WHEN** `Vision.serialize()` is called with a partially or fully filled ring
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

### Requirement: Vision habituation and encoder revision follow configuration
The composition root SHALL build the vision module's habituator with `[vision].habituation_window` when it is set; the window SHALL be an integer of at least 2. `[vision].encoder_revision`, when set, SHALL equal the InternVideo-Next loader's pinned revision; any other value SHALL refuse boot with a configuration error naming the configured and pinned revisions, because the pin decides which vendored code and weights load.

#### Scenario: The habituation window is applied
- **WHEN** `[vision].habituation_window = 8`
- **THEN** the vision module's habituator keeps a rolling window of 8 embeddings

#### Scenario: An unpinned revision is refused
- **WHEN** `[vision].encoder_revision` names a revision other than the pinned one
- **THEN** boot refuses with a configuration error naming both revisions, and no encoder is loaded

### Requirement: An encoder unload waits for in-flight inference
A vision module encoder's unload SHALL release its model only after every inference already running in a worker thread has finished, including an inference whose caller was cancelled.

#### Scenario: A cancelled encode is still running in its worker thread
- **WHEN** an encode is cancelled while its forward pass runs in a worker thread and unload is then called
- **THEN** unload does not finish and the model stays loaded until the worker thread returns, after which unload completes and the in-flight count is zero

### Requirement: Vision reports carry the change ratio
Every `vision.report` SHALL carry `normalised_change`, the change score divided by the running mean of change scores used by the change alert, or 0.0 when that mean is 0, with forward prediction on or off (paper A.2).

#### Scenario: A step change carries a large change ratio
- **WHEN** four identical frames are followed by an orthogonal frame
- **THEN** the fifth report's `normalised_change` equals its change score over the running mean of change scores and is at least the change alert factor

#### Scenario: The first report carries zero
- **WHEN** the first frame is processed
- **THEN** its report carries `normalised_change` 0.0

### Requirement: Face detection and embedding publishes vision.face_detection events
The vision module SHALL run a config-gated face detection and embedding pipeline alongside the existing clip encoder. When enabled, it SHALL detect faces in each processed frame, extract a face embedding per detected face, and publish a `vision.face_detection` event.

#### Scenario: Face detected and embedding published
- **WHEN** the face detection pipeline is enabled and one or more faces are detected in a processed frame
- **THEN** the module SHALL publish a `vision.face_detection` event carrying per-face embeddings, bounding boxes, confidence scores, and the total face count

#### Scenario: No face detected
- **WHEN** the face detection pipeline is enabled and no face is detected in a processed frame
- **THEN** the module SHALL NOT publish a `vision.face_detection` event for that frame

#### Scenario: Face detection disabled by default
- **WHEN** the system boots with shipped default configuration
- **THEN** no face detection pipeline SHALL be loaded and no `vision.face_detection` events SHALL be published

#### Scenario: Face detection independent of clip encoder
- **WHEN** the face detection pipeline is enabled
- **THEN** it SHALL operate independently of the clip encoder. A failure or absence of the clip encoder SHALL NOT prevent face detection, and vice versa

### Requirement: vision.face_detection event payload
Each `vision.face_detection` event SHALL carry `faces` (list of objects, each with `embedding` as a list of 128 floats, `bbox` as four floats [x, y, width, height], and `confidence` as a float in [0, 1]) and `face_count` (integer). The event SHALL carry `degraded: true` when the face recognition model is unavailable or produces a non-finite embedding.

#### Scenario: Multi-face payload
- **WHEN** three faces are detected in a frame
- **THEN** the `vision.face_detection` event SHALL carry a `faces` list of three entries, each with its own embedding, bounding box, and confidence, and `face_count` SHALL be 3

#### Scenario: Degraded detection when model absent
- **WHEN** the face recognition model is configured but fails to load
- **THEN** the vision module SHALL publish `vision.face_detection` with `degraded: true` and null embeddings, so downstream consumers can gate on the flag

### Requirement: Face detection preserves the zero-raw-sense-data invariant
The face detection pipeline SHALL NOT persist any raw frame data, face crops, or intermediate images to disk. Face embeddings are derived representations, not raw sense data, and SHALL follow the same on-device-only storage policy as clip embeddings. This invariant applies equally to expression and gaze pipelines.

#### Scenario: No face images written to disk
- **WHEN** the face detection pipeline processes a frame
- **THEN** no raw pixel data, face crop, or intermediate image SHALL be written to disk or included in preservation bundles

### Requirement: Face expression classification publishes vision.face_expression events
The vision module SHALL run a config-gated face expression classifier alongside the face detection pipeline. When enabled, it SHALL classify facial expression into categories for each detected face using the same face crop produced by face detection. This implements the pSTS analogue for changeable face features, feeding emotion evaluation rather than identity.

#### Scenario: Expression classified for detected face
- **WHEN** the face expression pipeline is enabled and one or more faces are detected
- **THEN** the module SHALL publish a `vision.face_expression` event carrying per-face expression labels, per-category scores, and confidence

#### Scenario: Expression classification disabled by default
- **WHEN** the system boots with shipped default configuration
- **THEN** no face expression classifier SHALL be loaded and no `vision.face_expression` events SHALL be published

#### Scenario: Expression classification independent of identity embedding
- **WHEN** the face expression pipeline is enabled
- **THEN** it SHALL operate independently of the face identity embedding (SFace). A failure of the identity model SHALL NOT prevent expression classification, and vice versa. Both share the face crop from detection.

### Requirement: vision.face_expression event payload
Each `vision.face_expression` event SHALL carry `faces` (list of objects, each with `expression` as a string label, `scores` as a dict mapping expression categories to float probabilities, `confidence` as a float in [0, 1], and `bbox` matching the corresponding face_detection entry) and `face_count` (integer).

#### Scenario: Multi-face expression payload
- **WHEN** two faces are detected and expression is classified for each
- **THEN** the `vision.face_expression` event SHALL carry a `faces` list of two entries, each with its own expression label, scores, confidence, and bounding box

### Requirement: Gaze estimation publishes vision.gaze_direction events
The vision module SHALL run a config-gated gaze estimator that produces yaw and pitch angles per detected face. When enabled, it SHALL estimate gaze direction for each detected face and publish a `vision.gaze_direction` event. Two implementations are supported: a learned model (MobileNet V2 gaze) and a landmark-based estimator (solvePnP on YuNet's 5-point landmarks). The config selects which.

#### Scenario: Gaze estimated for detected face
- **WHEN** the gaze pipeline is enabled and one or more faces are detected
- **THEN** the module SHALL publish a `vision.gaze_direction` event carrying per-face yaw and pitch angles in degrees and a mutual_gaze flag

#### Scenario: Mutual gaze detection
- **WHEN** a face's estimated gaze direction falls within a configurable angular threshold of the camera axis
- **THEN** the `mutual_gaze` flag for that face SHALL be true

#### Scenario: Gaze estimation disabled by default
- **WHEN** the system boots with shipped default configuration
- **THEN** no gaze estimator SHALL be loaded and no `vision.gaze_direction` events SHALL be published

### Requirement: vision.gaze_direction event payload
Each `vision.gaze_direction` event SHALL carry `faces` (list of objects, each with `yaw` and `pitch` as floats in degrees, `mutual_gaze` as boolean, `confidence` as float in [0, 1], and `bbox` matching the face_detection entry) and `face_count` (integer).

#### Scenario: Gaze event carries all required fields
- **WHEN** a frame with a face is processed with gaze enabled
- **THEN** the published `vision.gaze_direction` event payload SHALL contain a `faces` list where each entry has `yaw`, `pitch`, `mutual_gaze`, `confidence`, and `bbox` keys, and a top-level `face_count` integer
