# Tasks

## 1. Speaker Embedding Extraction in Audition

- [x] 1.1 Add sherpa-onnx speaker embedding model provisioning to `kaine/boot/provision.py`: WeSpeaker CAM++ (~29 MB ONNX) as a consent-gated download via the existing provision system. Verify: provisioning downloads the model to the configured model directory.
- [x] 1.2 Implement `SpeakerEmbedder` class in `kaine/modules/audition/speaker_embedder.py`: wraps sherpa-onnx speaker embedding API, accepts audio samples, returns 192-dim embedding vector and confidence. Gated by config flag `[audition].speaker_embedding_enabled`. Verify: unit test that loads the model and extracts an embedding from a test audio sample; test that absent model returns degraded result.
- [x] 1.3 Integrate `SpeakerEmbedder` into `Audition.process_audio()`: run alongside existing STT/emotion pipelines, publish `audition.speaker_embedding` event on the bus. Independent of STT: failure of one does not block the other. Verify: integration test that processes audio and observes `audition.speaker_embedding` on the bus; test that disabling the config flag produces no events.
- [x] 1.4 Add `[audition].speaker_embedding_enabled` config key (default false) to `config/kaine.toml` and wire it through composition root in `kaine/boot/factories/`. Verify: boot with default config does not load speaker embedder; boot with flag enabled does.

## 2. Face Detection and Embedding in Vision

- [x] 2.1 Implement `FaceDetector` class in `kaine/modules/vision/face_detector.py`: wraps `cv2.FaceDetectorYN` (YuNet) for detection and `cv2.FaceRecognizerSF` (SFace) for 128-dim face embedding extraction. Accepts a frame, returns list of (embedding, bbox, confidence) per detected face. Gated by config flag. Verify: unit test that detects a face in a test image and returns an embedding of correct dimensionality.
- [x] 2.2 Add YuNet and SFace model provisioning: consent-gated downloads via the existing provision system (~230 KB + ~35 MB ONNX). Verify: provisioning downloads both models.
- [x] 2.3 Integrate `FaceDetector` into `Vision.process_frame()`: run alongside existing clip encoder, publish `vision.face_detection` event on the bus. No raw frame data persisted (zero-raw-sense-data invariant). Verify: integration test that processes a frame with a face and observes `vision.face_detection` on the bus; test with no face produces no event; test that disabling config produces no events.
- [x] 2.4 Add `[vision].face_detection_enabled` config key (default false) to `config/kaine.toml` and wire through composition root. Verify: boot with default config does not load face detector.

## 3. AgentModel Extension (Person Identity Node)

- [x] 3.1 Extend `AgentModel` in `kaine/modules/social_cognition/agent.py`: add `voice_centroid` (192-dim, nullable), `face_centroid` (128-dim, nullable), `voice_exemplars` (list of exemplar dicts with embedding + timestamp), `face_exemplars` (list), `voice_sample_count` (int), `face_sample_count` (int), `binding_state` (enum: unbound/voice_only/face_only/bound), `binding_confidence` (float, Bayesian posterior accumulator, nullable), `voice_reliability` (float, inverse intra-cluster variance, nullable), `face_reliability` (float, nullable), `voice_acoustic_embedding` (nullable, forward-compatible with deferred two-level voice). Exemplar buffers serialized inline in `to_dict()`. Verify: unit test for construction, serialization (`to_dict`/`from_dict`), and backwards-compatible deserialization of profiles lacking the new fields (defaults to absent).
- [x] 3.2 Extend `familiarity()` to incorporate embedding evidence: factor in exemplar count, centroid stability, and binding confidence alongside existing interaction count and emotion coverage. When no embeddings exist, fall back to existing computation. Verify: unit test showing familiarity is higher with stable centroids and high sample counts than without, given equal interaction counts.
- [x] 3.3 Extend `SocialCognitionMergeStrategy` in `kaine/lifecycle/strategies.py`: merge voice/face centroids by sample-count-weighted average, union exemplar buffers with similarity-based deduplication, binding state takes higher-confidence side, binding confidence takes maximum. Verify: unit test for merge with diverged centroids, merge with one side lacking embeddings, merge of exemplar buffers.

## 4. Two-Phase Identity Learning

- [x] 4.1 Implement `ExemplarBuffer` in `kaine/modules/social_cognition/exemplar_buffer.py`: bounded per-modality exemplar storage with configurable max size, diversity-based eviction (evict exemplar most similar to centroid or peers), consolidation check (exemplar count >= threshold AND intra-cluster variance >= diversity floor). Verify: unit test for add, evict, consolidation trigger, buffer bounds.
- [x] 4.2 Implement consolidation logic: compute centroid from exemplar buffer, transition to centroid-based matching, EMA update after consolidation. Verify: unit test showing transition from exemplar matching to centroid matching after consolidation threshold is met.
- [x] 4.3 Add configuration keys for exemplar buffer limits, consolidation threshold, diversity floor, and EMA decay rate under `[social_cognition]`. Verify: config keys parsed and applied.

## 5. Identity Consumers and Cross-Modal Binder

- [x] 5.1 Implement speaker identification consumer in `kaine/modules/social_cognition/module.py`: subscribes to `audition.speaker_embedding`, matches against known agents (exemplar-based or centroid-based depending on phase), resolves to best match or mints new agent, publishes `social_cognition.identity_update`. Verify: integration test with known speaker resolved, unknown speaker minted.
- [x] 5.2 Implement face identification consumer: subscribes to `vision.face_detection`, matches each face against known agents, resolves per face, publishes `social_cognition.identity_update` per face. Verify: integration test with known face, unknown face, multiple faces.
- [x] 5.3 Implement reliability-weighted cross-modal binder in `kaine/modules/social_cognition/binder.py`: tracks recent voice and face identifications in a sliding window, computes Bayesian posterior for common-cause (Ernst & Banks 2002 MLE), weights by per-modality reliability (inverse exemplar variance), accumulates binding_confidence via EMA, merges agents when binding_confidence exceeds configurable threshold. Verify: integration test showing agent merge on sustained high-confidence co-occurrence, no merge on low-confidence or single coincidence, no merge when only one modality active, low-reliability modality contributes less to binding.
- [x] 5.4 Wire identity resolution into existing agent attribution: when identity binding is enabled and a speaker has been identified, `_agent_for(event)` uses the identity-resolved agent instead of the operator label. Fallback to label when identity unavailable. Verify: integration test showing identity-based attribution replacing label-based.
- [x] 5.5 Add `FaithfulRenderer` template for `social_cognition.identity_update` events. Verify: template renders in human-readable form.

## 6. Store and Persistence

- [x] 6.1 Extend `AgentStore` protocol and both implementations (`InMemoryAgentStore`, `QdrantAgentStore`) to store and search by voice and face embeddings. Verify: unit test for storing agent with embeddings, searching by voice embedding, searching by face embedding.
- [x] 6.2 Extend preservation: `social_cognition` capture and restore includes exemplar buffers and centroids. Verify: test that preserved agent profiles with embeddings restore correctly.

## 7. Configuration and Deployment Tiers

- [x] 7.1 Add `[social_cognition]` config keys: speaker/face identification thresholds, co-occurrence window, binding merge threshold, p_common prior, reliability floor, exemplar buffer limits, consolidation parameters, expression/gaze pipeline toggles. All ship disabled/conservative. Verify: config keys parsed, defaults correct.
- [x] 7.2 Update deployment-tier capability matrix: perceptual identity row (speaker + face identity + expression + gaze): present Tier 2+, absent Tier 0/1. Tier 0/1 tier files force identity and face-perception config flags to disabled. Verify: Tier 1 config overlay disables all; Tier 2 allows them.

## 8. Face Expression Classification (pSTS Analogue)

- [x] 8.1 Add OpenCV Zoo FER model provisioning: consent-gated download via the existing provision system (~8 MB ONNX). Verify: provisioning downloads the model.
- [x] 8.2 Implement `FaceExpressionClassifier` class in `kaine/modules/vision/face_expression.py`: wraps the OpenCV Zoo FER model, accepts a face crop (from YuNet detection), returns expression label, per-category scores, and confidence. Gated by config flag. Verify: unit test that classifies a test face crop and returns 7-category scores.
- [x] 8.3 Integrate `FaceExpressionClassifier` into `Vision.process_frame()`: run on each detected face alongside the identity pipeline, sharing the same face crop. Publish `vision.face_expression` event on the bus. Independent of identity embedding (SFace failure does not block expression). Verify: integration test that processes a frame with a face and observes `vision.face_expression` on the bus.
- [x] 8.4 Add `[vision].face_expression_enabled` config key (default false) to `config/kaine.toml`. Verify: boot with default config does not load expression classifier.

## 9. Gaze Estimation

- [x] 9.1 Implement gaze estimation in `kaine/modules/vision/gaze_estimator.py`: two backends, config-selectable. (1) Landmark-based: solvePnP on YuNet's 5-point landmarks, producing yaw/pitch (zero model cost). (2) Learned: MobileNet V2 gaze (~10 MB ONNX, MIT, consent-gated download). Both produce per-face yaw, pitch, and mutual_gaze flag. Verify: unit test for both backends.
- [x] 9.2 Integrate gaze estimator into `Vision.process_frame()`: run on each detected face, publish `vision.gaze_direction` event. Verify: integration test with face observes gaze event; mutual gaze flag set when face points at camera.
- [x] 9.3 Add `[vision].gaze_enabled` and `[vision].gaze_backend` (landmark|learned) config keys (default false/landmark). Add MobileNet V2 gaze model provisioning if learned backend enabled. Verify: config keys parsed, landmark backend works without model download.

## 10. Multimodal Emotion Fusion

- [x] 10.1 Implement face expression consumer in `kaine/modules/social_cognition/module.py`: subscribes to `vision.face_expression`, looks up the agent for the detected face via the identity system, updates the agent's emotion histogram with visual evidence weighted by expression confidence. Verify: integration test showing agent emotion histogram updated from face expression.
- [x] 10.2 Implement emotion fusion logic: when both voice emotion (from `audition.emotion`) and face emotion (from `vision.face_expression`) are available for the same agent in the same processing window, fuse by confidence-weighted combination. Verify: unit test showing fused emotion differs from either single-modality source.
- [x] 10.3 Add `FaithfulRenderer` template for `vision.face_expression` and `vision.gaze_direction` events. Verify: templates render in human-readable form.

## 11. Per-Modality Reliability

- [x] 11.1 Implement reliability computation in `ExemplarBuffer`: method `reliability()` returns inverse of intra-cluster variance (mean squared cosine distance from centroid), normalized to [0, 1]. Returns configurable floor when fewer than 2 exemplars. Verify: unit test with known exemplar distributions.
- [x] 11.2 Wire reliability into AgentModel: `voice_reliability` and `face_reliability` fields, updated when exemplar buffer changes. Verify: reliability increases as exemplars cluster tighter.
- [x] 11.3 Wire reliability into familiarity(): weight perceptual evidence contribution by reliability. High-reliability centroids contribute more to familiarity than low-reliability ones. Verify: unit test showing familiarity difference.

## 12. Integration Verification

- [x] 12.1 End-to-end integration test: enable all pipelines (speaker identity, face identity, expression, gaze), process audio and video with a consistent identity. Verify: agent minted by voice, recognized by face, expression and gaze events attributed to agent, cross-modal merge on sustained co-occurrence with reliability weighting, familiarity increases, all events published correctly.
- [x] 12.2 Backwards compatibility test: deserialize agent profiles from before this change (no embedding/reliability fields), verify they load with absent defaults and continue to function.
- [x] 12.3 Single-modality test: enable only speaker embedding (face disabled). Verify: voice-only identification works, no face events, no binding, no expression/gaze events. Repeat with only face enabled.
