# Spec Delta

## ADDED Requirements

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
