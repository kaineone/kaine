# Tasks

## 1. Speaker Embedding Extraction in Audition

- [ ] 1.1 Add sherpa-onnx speaker embedding model provisioning to `kaine/boot/provision.py`: WeSpeaker CAM++ (~29 MB ONNX) as a consent-gated download via the existing provision system. Verify: provisioning downloads the model to the configured model directory.
- [ ] 1.2 Implement `SpeakerEmbedder` class in `kaine/modules/audition/speaker_embedder.py`: wraps sherpa-onnx speaker embedding API, accepts audio samples, returns 192-dim embedding vector and confidence. Gated by config flag `[audition].speaker_embedding_enabled`. Verify: unit test that loads the model and extracts an embedding from a test audio sample; test that absent model returns degraded result.
- [ ] 1.3 Integrate `SpeakerEmbedder` into `Audition.process_audio()`: run alongside existing STT/emotion pipelines, publish `audition.speaker_embedding` event on the bus. Independent of STT: failure of one does not block the other. Verify: integration test that processes audio and observes `audition.speaker_embedding` on the bus; test that disabling the config flag produces no events.
- [ ] 1.4 Add `[audition].speaker_embedding_enabled` config key (default false) to `config/kaine.toml` and wire it through composition root in `kaine/boot/factories/`. Verify: boot with default config does not load speaker embedder; boot with flag enabled does.

## 2. Face Detection and Embedding in Vision

- [ ] 2.1 Implement `FaceDetector` class in `kaine/modules/vision/face_detector.py`: wraps `cv2.FaceDetectorYN` (YuNet) for detection and `cv2.FaceRecognizerSF` (SFace) for 128-dim face embedding extraction. Accepts a frame, returns list of (embedding, bbox, confidence) per detected face. Gated by config flag. Verify: unit test that detects a face in a test image and returns an embedding of correct dimensionality.
- [ ] 2.2 Add YuNet and SFace model provisioning: consent-gated downloads via the existing provision system (~230 KB + ~35 MB ONNX). Verify: provisioning downloads both models.
- [ ] 2.3 Integrate `FaceDetector` into `Vision.process_frame()`: run alongside existing clip encoder, publish `vision.face_detection` event on the bus. No raw frame data persisted (zero-raw-sense-data invariant). Verify: integration test that processes a frame with a face and observes `vision.face_detection` on the bus; test with no face produces no event; test that disabling config produces no events.
- [ ] 2.4 Add `[vision].face_detection_enabled` config key (default false) to `config/kaine.toml` and wire through composition root. Verify: boot with default config does not load face detector.

## 3. AgentModel Extension (Person Identity Node)

- [ ] 3.1 Extend `AgentModel` in `kaine/modules/social_cognition/agent.py`: add `voice_centroid` (192-dim, nullable), `face_centroid` (128-dim, nullable), `voice_exemplars` (list of exemplar dicts with embedding + timestamp), `face_exemplars` (list), `voice_sample_count` (int), `face_sample_count` (int), `binding_state` (enum: unbound/voice_only/face_only/bound), `binding_confidence` (float, nullable). Verify: unit test for construction, serialization (`to_dict`/`from_dict`), and backwards-compatible deserialization of profiles lacking the new fields (defaults to absent).
- [ ] 3.2 Extend `familiarity()` to incorporate embedding evidence: factor in exemplar count, centroid stability, and binding confidence alongside existing interaction count and emotion coverage. When no embeddings exist, fall back to existing computation. Verify: unit test showing familiarity is higher with stable centroids and high sample counts than without, given equal interaction counts.
- [ ] 3.3 Extend `SocialCognitionMergeStrategy` in `kaine/lifecycle/strategies.py`: merge voice/face centroids by sample-count-weighted average, union exemplar buffers with similarity-based deduplication, binding state takes higher-confidence side, binding confidence takes maximum. Verify: unit test for merge with diverged centroids, merge with one side lacking embeddings, merge of exemplar buffers.

## 4. Two-Phase Identity Learning

- [ ] 4.1 Implement `ExemplarBuffer` in `kaine/modules/social_cognition/exemplar_buffer.py`: bounded per-modality exemplar storage with configurable max size, diversity-based eviction (evict exemplar most similar to centroid or peers), consolidation check (exemplar count >= threshold AND intra-cluster variance >= diversity floor). Verify: unit test for add, evict, consolidation trigger, buffer bounds.
- [ ] 4.2 Implement consolidation logic: compute centroid from exemplar buffer, transition to centroid-based matching, EMA update after consolidation. Verify: unit test showing transition from exemplar matching to centroid matching after consolidation threshold is met.
- [ ] 4.3 Add configuration keys for exemplar buffer limits, consolidation threshold, diversity floor, and EMA decay rate under `[social_cognition]`. Verify: config keys parsed and applied.

## 5. Identity Consumers and Cross-Modal Binder

- [ ] 5.1 Implement speaker identification consumer in `kaine/modules/social_cognition/module.py`: subscribes to `audition.speaker_embedding`, matches against known agents (exemplar-based or centroid-based depending on phase), resolves to best match or mints new agent, publishes `social_cognition.identity_update`. Verify: integration test with known speaker resolved, unknown speaker minted.
- [ ] 5.2 Implement face identification consumer: subscribes to `vision.face_detection`, matches each face against known agents, resolves per face, publishes `social_cognition.identity_update` per face. Verify: integration test with known face, unknown face, multiple faces.
- [ ] 5.3 Implement cross-modal binder: tracks recent voice and face identifications in a sliding window, merges agents when voice and face co-occur within the configurable window for a minimum co-occurrence count. Verify: integration test showing agent merge on sustained co-occurrence, no merge on single coincidence, no merge when only one modality active.
- [ ] 5.4 Wire identity resolution into existing agent attribution: when identity binding is enabled and a speaker has been identified, `_agent_for(event)` uses the identity-resolved agent instead of the operator label. Fallback to label when identity unavailable. Verify: integration test showing identity-based attribution replacing label-based.
- [ ] 5.5 Add `FaithfulRenderer` template for `social_cognition.identity_update` events. Verify: template renders in human-readable form.

## 6. Store and Persistence

- [ ] 6.1 Extend `AgentStore` protocol and both implementations (`InMemoryAgentStore`, `QdrantAgentStore`) to store and search by voice and face embeddings. Verify: unit test for storing agent with embeddings, searching by voice embedding, searching by face embedding.
- [ ] 6.2 Extend preservation: `social_cognition` capture and restore includes exemplar buffers and centroids. Verify: test that preserved agent profiles with embeddings restore correctly.

## 7. Configuration and Deployment Tiers

- [ ] 7.1 Add `[social_cognition]` config keys: speaker/face identification thresholds, co-occurrence window, co-occurrence count before merge, exemplar buffer limits, consolidation parameters. All ship disabled/conservative. Verify: config keys parsed, defaults correct.
- [ ] 7.2 Update deployment-tier capability matrix: perceptual identity row: present Tier 2+, absent Tier 0/1. Tier 0/1 tier files force identity config flags to disabled. Verify: Tier 1 config overlay disables identity; Tier 2 allows it.

## 8. Integration Verification

- [ ] 8.1 End-to-end integration test: enable both modalities, process audio and video with a consistent identity, verify agent minted by voice, recognized by face, cross-modal merge on co-occurrence, familiarity increases, identity_update events published correctly.
- [ ] 8.2 Backwards compatibility test: deserialize agent profiles from before this change (no embedding fields), verify they load with absent defaults and continue to function.
