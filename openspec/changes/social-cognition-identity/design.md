# Design

## Context

See proposal.md for motivation and neuroscience grounding. The social cognition module currently identifies agents by operator-set labels. This design adds three perceptual identity pipelines (speaker embedding, face embedding, cross-modal binding) and extends the AgentModel to serve as a Person Identity Node.

Current state:
- **Audition** (`kaine/modules/audition/module.py`): processes audio via `process_audio()` with STT (sherpa-onnx Moonshine), emotion (emotion2vec+), acoustic perception, and prosody extraction. No speaker embedding extraction.
- **Vision** (`kaine/modules/vision/module.py`): processes frames via `process_frame()` with InternVideo-Next clip encoder, change detection, habituation, and foveation. No face detection.
- **Social cognition** (`kaine/modules/social_cognition/`): `AgentModel` stores emotion histograms, behavioral summaries, reliability, interaction counts. `_agent_for(event)` resolves by `source_label`. `AgentStore` protocol with `InMemoryAgentStore` (tests) and `QdrantAgentStore` (production).
- **sherpa-onnx**: already in the dependency tree for STT and TTS. Speaker embedding models are an additional download, not a new dependency.
- **OpenCV**: available or trivially added. YuNet and SFace are OpenCV Zoo models loaded via `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF`.

## Goals / Non-Goals

**Goals:**
- Add speaker embedding extraction to audition as a separable pathway
- Add face detection and embedding to vision as a dedicated pipeline
- Extend AgentModel with modality-specific embedding storage (separate voice and face representations)
- Implement two-phase identity learning: exemplar buffer (fast binding) → centroid consolidation (slow)
- Implement cross-modal binding via temporal co-occurrence in a convergence-zone pattern
- Integrate identity resolution into existing agent attribution (replacing label-only when available)
- Extend `familiarity()` to incorporate perceptual evidence
- All components config-gated, shipping disabled

**Non-Goals:**
- Face expression processing (pSTS analogue: changeable face features like expression and gaze)
- Lip-reading or auditory-visual speech integration
- Task-gated cross-modal binding (the brain gates binding by task demands; this implementation does not)
- Graded reliability weighting for cross-modal integration
- Norm-based encoding (global population prototype with identity as deviation)
- Direct sensory-level lateral connections between audition and vision modules
- Content workspace z_k interaction specification (deferred; speculative)
- Training or fine-tuning any models at runtime

## Decisions

### D1: Separate voice and face centroids, not a merged embedding
**Choice:** Store `voice_centroid` (192-dim) and `face_centroid` (128-dim) as independent fields on AgentModel.
**Why:** Anzellotti (2014) found face and voice identity representations do not overlap even in anterior temporal lobe. Burton & Bruce (1993) revised PINs to be identity-indexing pointers into modality-specific representations. A merged embedding would lose modality-specific information and prevent independent modality matching.
**Alternative rejected:** Single fused embedding via concatenation or learned projection. This would conflate modalities and prevent unimodal identification (voice-only or face-only scenarios).

### D2: Two-phase learning (exemplar buffer → centroid)
**Choice:** Store individual exemplar embeddings per agent per modality in a bounded buffer. Use nearest-exemplar matching initially. After accumulating sufficient diverse exemplars, consolidate to a centroid and switch to centroid-based matching.
**Why:** CLS theory (McClelland et al., 1995) argues that a single learning-rate system fails. It either catastrophically forgets or learns too slowly. The exemplar buffer is the fast episodic store (hippocampal analogue); the centroid is the consolidated prototype (neocortical analogue).
**Alternative rejected:** EMA-only from first observation. A single-sample centroid discards the specific observation; CLS theory's entire point is that you need two systems. The exemplar buffer preserves episode-level detail during early learning.

**Parameters:**
- Consolidation threshold: configurable, default 5 exemplars per modality
- Diversity floor: minimum intra-cluster variance before consolidation triggers
- Max buffer size: configurable, default 20 exemplars per modality per agent
- EMA decay rate: configurable, default 0.9 (after consolidation)

### D3: Cross-modal binder as convergence-zone correlator
**Choice:** The binder sits in the social cognition module, consuming `audition.speaker_embedding` and `vision.face_detection` events via the bus. It correlates voice and face detections within a temporal window and merges the corresponding agents.
**Why:** This is architecturally a convergence-zone pattern, analogous to the posterior STS (Campanella & Belin, 2007) which receives both auditory and visual person stimuli. It is NOT a direct sensory-level coupling (which would require lateral connections between audition and vision modules, bypassing the bus).
**Alternative rejected:** Direct audition-vision lateral connections. Architecturally complex: modules would need to hold references to each other, breaking the bus-mediated decoupling. The convergence-zone pattern is simpler and consistent with pSTS function.

**Parameters:**
- Co-occurrence window: configurable, default 3 s (engineering parameter, no direct neuroscience backing)

### D4: Speaker embedding via sherpa-onnx + WeSpeaker CAM++
**Choice:** Use the existing sherpa-onnx dependency with WeSpeaker CAM++ model.
**Why:** Already in the dependency tree. 29 MB ONNX, 192-dim embeddings, 0.73% EER on VoxCeleb1-O, Apache 2.0. Few-shot capable from ~3 s of speech. Best accuracy/size ratio available. Note: 0.73% EER is for verification (same/different), not identification; identification accuracy degrades with enrolled speaker count.
**Alternative rejected:** ECAPA-TDNN (superseded by CAM++ on all axes), any Meta-derived model (forbidden by project policy).

### D5: Face detection via YuNet + SFace (OpenCV Zoo)
**Choice:** YuNet for detection (~230 KB ONNX), SFace for recognition (~35 MB ONNX, 128-dim embeddings).
**Why:** Both are OpenCV Zoo models loadable via `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF`. Apache 2.0 licensed. Minimal footprint. OpenCV is already available.
**Upgrade path:** AuraFace-v1 (~100 MB ONNX, Apache 2.0, near-ArcFace accuracy) if SFace proves insufficient for the entity's operating environment.
**Alternative rejected:** InsightFace/ArcFace pretrained weights (non-commercial license), SCRFD pretrained weights (same restriction), YOLO face detection (AGPL-3.0).

### D6: Agent merge on cross-modal binding
**Choice:** When the binder determines that agent A (known by voice) and agent B (known by face) are the same person, it merges B into A (or vice versa, preferring the agent with more observations). The merged agent inherits both modality representations and the combined interaction history.
**Why:** The alternative (maintaining two separate agents linked by a pointer) adds complexity to every downstream consumer. A merge is cleaner: one agent, one identity, both modalities.
**Risk:** False merge from coincidental co-occurrence. Mitigated by requiring the co-occurrence to be sustained (not a single coincidence) before merging. A configurable minimum co-occurrence count before merge is triggered.

### D7: Exemplar eviction by diversity
**Choice:** When the exemplar buffer is full, evict the exemplar most similar to the current centroid or to other exemplars (least diverse).
**Why:** Andrews et al. (2015) and Jenkins et al. (2011) found that exemplar diversity matters more than count for reliable face and voice learning. Evicting the least diverse exemplar maximizes the information content of the buffer.
**Alternative rejected:** FIFO eviction (discards potentially unique early observations), random eviction (no diversity guarantee).

## Risks / Trade-offs

**[Risk] False agent minting from embedding noise** → Cosine similarity thresholds must be tuned per model and environment. Ship with conservative thresholds (prefer false negatives over false merges). Expose threshold configuration.

**[Risk] False cross-modal merge from coincidental co-occurrence** → Require configurable minimum co-occurrence count (default 3) before merge. A single coincidence does not trigger merge.

**[Risk] Speaker identification degrades with enrolled speaker count** → CAM++'s 0.73% EER is for verification, not open-set identification. With many enrolled speakers, nearest-centroid matching becomes less reliable. Mitigated by the exemplar buffer (more discriminative in early phase) and by the expected small population (home/lab, typically 1-10 people).

**[Risk] Exemplar buffer memory** → Each exemplar is ~1.5 KB (192 floats for voice, 128 floats for face, plus metadata). At 20 exemplars × 2 modalities × 10 agents = 400 exemplars ≈ 600 KB. Negligible on Orin Nano Super.

**[Risk] Face detection in low light / partial occlusion** → YuNet's accuracy (WIDER Face AP 0.834 easy, lower on hard) may produce missed detections or false positives in adverse conditions. The system degrades gracefully: missed detections mean no identity update, not a wrong one.

**[Risk] Backwards compatibility** → AgentModel gains new fields. Existing serialized agent profiles (from preservation bundles or Qdrant) must deserialize cleanly with new fields defaulting to absent. `from_dict()` handles missing keys.

**[Trade-off] Convergence zone vs. sensory-level coupling** → The binder sits in social cognition (a central hub), not at the sensory level. This is simpler but less biologically faithful. Direct sensory-level coupling would require architectural changes to module communication that are out of scope.

**[Trade-off] Single embedding level vs. two-level voice representation** → The brain has acoustic-level (TVA) and abstracted (IFC) voice identity. CAM++ produces a single embedding conflating both. Acceptable for v1; a hierarchical voice-identity system is future work.

## Open Questions

- **Exemplar buffer persistence format:** The exemplar buffer needs to serialize for preservation bundles. Should exemplars be stored inline in the AgentModel dict, or in a separate collection in Qdrant? Inline is simpler but makes the serialized model larger. Either choice does not affect the spec or the task breakdown.
- **Content workspace interaction:** If/when z_k cycle-consistency training integrates with identity, what is the API surface? Deferred per proposal; the speculative integration is not designed here.
