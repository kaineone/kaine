## ADDED Requirements

### Requirement: Topos publishes topos.report for each processed frame
Topos SHALL publish a `topos.report` event to its `topos.out` stream
every time `process_frame(image)` is called. The event SHALL carry
`latent` (list of floats — the encoder output), `change_score` (float
`>= 0`), `habituation_score` (float in `[0.0, 1.0]`), and
`encoder_model_id` (string). Salience SHALL be elevated when
`change_score` exceeds the configured alert threshold.

#### Scenario: One frame in produces one report out
- **WHEN** `topos.process_frame(image)` is awaited once
- **THEN** exactly one `topos.report` event appears on the `topos.out`
  stream and the returned value is its entry id

#### Scenario: Large change elevates salience
- **WHEN** two frames that produce orthogonal embeddings are processed
  in sequence and the alert threshold is 0.5
- **THEN** the second event's salience equals the configured alert
  salience and its `change_score >= 1.0`

### Requirement: Encoder is replaceable via the Encoder protocol
Topos SHALL accept an `Encoder` collaborator implementing
`async encode(image) -> list[float]`. The default encoder SHALL be
`DINOv2Encoder` loading `facebook/dinov2-small` (configurable). The
returned vector SHALL be deterministic for the same image bytes.

#### Scenario: Custom encoder substitutes cleanly
- **WHEN** Topos is constructed with a custom `Encoder` returning a
  constant vector
- **THEN** every published `topos.report` carries that vector as
  `latent`

#### Scenario: Default encoder identity reported in event
- **WHEN** the default `DINOv2Encoder` is used
- **THEN** published reports have `encoder_model_id` equal to
  `"facebook/dinov2-small"`

### Requirement: Cosine-similarity change detection
The default `CosineChangeDetector` SHALL compute
`change_score = 1 - cosine_similarity(previous, current)`. The first
frame after initialization SHALL produce `change_score = 0` (no
previous frame to compare against). Identical consecutive frames
SHALL produce `change_score = 0`. Orthogonal frames SHALL produce
`change_score = 1`. Anti-correlated frames SHALL produce
`change_score = 2`.

#### Scenario: First frame yields zero change
- **WHEN** Topos processes one frame after initialization
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

### Requirement: Frozen encoder, no training in Topos
The default `DINOv2Encoder` SHALL load its underlying torch model in
`eval()` mode with `requires_grad_(False)` on every parameter. Topos
SHALL never call `.train()` or any optimizer on the encoder.

#### Scenario: Encoder parameters require no gradient
- **WHEN** the default `DINOv2Encoder` is initialized
- **THEN** every parameter of the underlying torch model returns
  `requires_grad == False`

### Requirement: Device selection through dynamic-hardware
The default `DINOv2Encoder` SHALL resolve its device through
`kaine.hardware.select_device(preferred)`, where `preferred` comes
from `[topos].device` in `config/kaine.toml` (`auto`, `cpu`, `cuda`,
`mps`). `KAINE_FORCE_DEVICE` env-var override SHALL be honored.

#### Scenario: Preferred device honored when available
- **WHEN** `[topos].device = "cpu"` is configured
- **THEN** the encoder's tensors live on `cpu` even on a CUDA host

### Requirement: Default Topos config and disabled-by-default
The repository SHALL ship a `[topos]` section in `config/kaine.toml`
with default values for `encoder_model_id`, `device`,
`change_alert_threshold`, `habituation_window`, `baseline_salience`,
`alert_salience`. The `[modules].topos = false` flag SHALL keep first
boot from auto-registering Topos.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[topos]` section with `encoder_model_id`,
  `device`, `change_alert_threshold`, `habituation_window`,
  `baseline_salience`, `alert_salience`, and `[modules].topos == false`
