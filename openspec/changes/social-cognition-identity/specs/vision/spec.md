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
The face detection pipeline SHALL NOT persist any raw frame data, face crops, or intermediate images to disk. Face embeddings are derived representations, not raw sense data, and SHALL follow the same on-device-only storage policy as clip embeddings.

#### Scenario: No face images written to disk
- **WHEN** the face detection pipeline processes a frame
- **THEN** no raw pixel data, face crop, or intermediate image SHALL be written to disk or included in preservation bundles
