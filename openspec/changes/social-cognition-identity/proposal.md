# Proposal

## Why

The social cognition module identifies agents by a single operator-set speaker label (default `"operator"`). The module docstring says: "Speaker diarization is future work (paper §10)." The entity cannot tell voices apart, cannot recognize faces, and cannot bind a heard voice to a seen face. This change adds perceptual identity (speaker embeddings, face embeddings, and cross-modal binding) so the entity learns who it is interacting with from what it hears and sees, rather than from a static label.

## Neuroscience Grounding

The design follows the brain's person-identity system as described by converging evidence from neuroimaging, single-unit recording, and neuropsychology. Each subsection states the science, then the design mapping. Findings that constrain the design are marked **[constrains]**. Findings that are compatible with the design but did not drive it are marked **[compatible]**.

### Voice identity

The human brain processes voice identity in the **temporal voice areas (TVAs)** along the superior temporal sulcus (Belin, Zatorre & Ahad, 2000, *Nature* 403:309). Voice identity follows a ventral "who" pathway separable from the speech-content pathway (Belin & Zatorre, 2003, *NeuroReport* 14:2105). The separation is an *adaptation-transfer* finding: adapting to identity does not transfer to speech content, and vice versa. Both streams originate in TVA and share early auditory processing stages before diverging. A meta-analysis localizes voice-identity processing to right mid/anterior STS and right inferior frontal cortex (Blank, Wieland & von Kriegstein, 2014, *NeuroImage*), suggesting a two-level representation: TVAs encode acoustic-level voice signatures, while right IFC encodes learned voice identity independent of low-level features.

The representational format is debated. Latinus & Belin (2011, *Cerebral Cortex* 21:2085) found adaptation aftereffects consistent with norm-based encoding (voices coded as deviations from a population average in a multidimensional voice space). However, opponent-coding and multichannel accounts remain open alternatives.

Reliable voice recognition requires substantial exposure; the familiar-voice advantage builds over days to weeks of varied exposure (Schweinberger et al., 2014, *Journal of Cognitive Neuroscience*), though above-chance recognition is possible from ~20 seconds of speech.

**Design mapping:** A dedicated speaker-identity encoder runs in the audition module alongside but separate from the speech-content (STT) and emotion pipelines. **[constrains]** The separable-streams finding requires that voice-identity processing not be conflated with speech content; a dedicated encoder satisfies this constraint. The engineering separation is stronger than the biological one: the brain shares early auditory processing across streams, while CAM++ and Moonshine have independent feature extractors. This is a pragmatic choice, not a claim of biological fidelity at the processing level. The encoder produces embeddings in a continuous space where identity is measured as cosine distance between embeddings. **[compatible]** This operates in an embedding space, which is consistent with the general idea of a multidimensional voice space, but does not implement norm-based encoding specifically (which would require a global population prototype with identities coded as deviations from it). The system stores per-person centroids, a prototype-per-person approach.

**Known gap:** The two-level representation (TVA acoustic signatures + IFC learned identity) is not reproduced. The encoder produces a single embedding that conflates acoustic and abstracted identity features.

Technology: sherpa-onnx + WeSpeaker CAM++ (29 MB ONNX, 192-dim, 0.73% EER on VoxCeleb1-O verification, Apache 2.0). Note: the 0.73% EER is for same/different verification; identification accuracy degrades with the number of enrolled speakers.

### Face identity

The brain's face system follows Haxby, Hoffman & Gobbini's (2000, *Trends in Cognitive Sciences* 4:223) distributed model: a core system (OFA for early feature detection, FFA for invariant identity features, posterior STS for changeable features like expression and gaze) and an extended system (amygdala for emotion, auditory cortex for speech from lip-reading). Viewpoint-invariant identity codes form along a posterior-to-anterior gradient in ventral temporal cortex (Freiwald & Tsao, 2010, *Science* 330:845; Anzellotti & Caramazza, 2015, *Journal of Cognitive Neuroscience*).

**Design mapping:** A face detection + recognition pipeline runs in the vision module alongside the existing clip encoder. **[constrains]** The brain has a dedicated face-identity system (FFA) distinct from general object recognition and from changeable-feature processing (pSTS); this requires a dedicated face encoder separate from the clip-level scene encoder. The face encoder was selected on engineering grounds (size, license, OpenCV integration); the neuroscience constrains the architectural decision to have a dedicated face-identity pathway, not the choice of specific model.

**Known gaps:** (1) The brain's multi-stage core system (OFA → FFA → anterior temporal) is compressed to a single feedforward encoder. (2) The pSTS role in processing changeable face features (expression, gaze, lip movement) has no analogue in this change. Expression information from faces should feed into emotion detection, not identity; this is future work, potentially in the audition-vision coordination or in a separate face-expression pipeline. (3) Haxby's extended system (amygdala for emotion, auditory cortex for lip-reading) is intentionally excluded from this change's scope.

Technology: YuNet (~230 KB, face detection) + SFace (~35 MB, face recognition), both OpenCV Zoo, Apache 2.0. Upgrade path: AuraFace-v1 (~100 MB, Apache 2.0) if SFace proves insufficient.

### Cross-modal binding through temporal co-occurrence

Von Kriegstein & Giraud (2006, *Current Biology* 16:2023) demonstrated that hearing a familiar voice activates the fusiform face area even without visual input, after only ~2 minutes of audiovisual exposure. This is a *learned structural coupling* between the TVA and FFA: repeated co-occurrence creates persistent connectivity changes so that one modality's processor activates the other's. The effect is task-dependent: FFA activation by voice occurs only during speaker identification tasks, not speech comprehension. It persists even in prosopagnosia (von Kriegstein et al., 2008, *Cerebral Cortex* 18:1), indicating sensory-to-sensory association rather than top-down semantic retrieval.

Campanella & Belin (2007, *Trends in Cognitive Sciences* 11:535) proposed that corresponding processing pathways in auditory and visual systems are linked: the ventral identity pathways cross-talk, and the posterior STS is a convergence zone for audiovisual person stimuli. Ernst (2007) argues the brain tracks statistical reliability of co-occurring cues and adjusts integration weights accordingly.

**Design mapping:** A cross-modal binder in the social cognition module uses temporal co-occurrence of voice and face detections as a Hebbian-style learning signal: voice and face events occurring within a configurable window are associated with the same agent. **[constrains]** The general principle that the brain binds co-occurring cross-modal stimuli through temporal association (Hebbian co-occurrence) justifies using co-occurrence as the binding trigger.

**What this is not:** The binder does not reproduce the FFA-TVA sensory-level coupling that von Kriegstein described. That phenomenon is a learned structural connectivity change *between sensory areas*: one modality's processor directly activating the other's. The proposed binder is architecturally a convergence-zone pattern: it sits in social cognition (a central module consuming events from both audition and vision via the bus), which is closer to the pSTS convergence zone described by Campanella & Belin than to direct sensory-to-sensory coupling. A sensory-level implementation would require direct lateral connections between the audition and vision modules, bypassing the bus. That is architecturally complex and deferred.

**Known gaps:** (1) The brain gates cross-modal binding by task demands (von Kriegstein's effect is task-dependent); this implementation does not; the binder runs whenever both modalities are active. Task-gating could be added later via attention or workspace gating. (2) The brain adjusts integration weights by statistical reliability (Ernst, 2007); this implementation uses a binary bind/don't-bind decision rather than graded reliability weighting. (3) The default co-occurrence window is an engineering parameter without direct neuroscience backing; no cited paper specifies a temporal binding window for voice-face coincidence.

### Person Identity Nodes

Bruce & Young (1986, *British Journal of Psychology* 77:305) proposed person identity nodes (PINs) as modality-independent identity indices where familiarity decisions arise. Burton & Bruce (1993) revised PINs to be identity-indexing pointers rather than information stores, with familiarity computed at the PIN level. The neural correlate is debated: ATL, pSTS, and hippocampus all have supporting evidence. Quiroga et al. (2005, *Nature* 435:1102) found hippocampal concept cells that fire to a specific person across photos, drawings, and names. Tyree, Metke & Miller (2023, *Science*) found cross-modal identity neurons in marmoset hippocampus. Whether concept cells form from few exposures (as Quiroga, 2019 suggests) remains debated.

**Design mapping:** The existing AgentModel is the PIN: a per-person index node that accumulates identity evidence from either modality. **[constrains]** Following Burton & Bruce (1993), the PIN stores pointers to modality-specific representations (separate voice_centroid and face_centroid) rather than a single merged embedding. This is further constrained by Anzellotti's (2014) finding that face and voice identity representations do not overlap even in ATL, so modality-specific codes persist alongside any cross-modal representation. The `familiarity()` method should be extended to incorporate embedding-based evidence (number of exemplars, centroid stability, binding confidence), making the PIN the locus of familiarity decisions as Burton & Bruce intended.

**[compatible]** Concept cells (Quiroga et al., 2005) and cross-modal identity neurons (Tyree et al., 2023) support the general idea of a per-person identity representation activated by any modality. The AgentModel serves this role but does not directly model concept-cell behavior (sparse, selective neural activation). These findings are cited as supporting evidence for the PIN concept, not as directly modeled mechanisms.

### Fast binding, slow consolidation

The hippocampus mediates rapid cross-modal identity binding (Paller et al., 2003, *Learning & Memory* 10:253). Complementary learning systems (CLS) theory (McClelland, McNaughton & O'Reilly, 1995, *Psychological Review*) posits two architecturally distinct memory systems: a fast-learning hippocampal system that binds specific episodes and a slow-learning neocortical system that gradually extracts statistical regularities. The entire point of CLS theory is that a single learning-rate system cannot serve both roles. It either catastrophically forgets old associations when learning new ones (too fast) or cannot form new associations quickly (too slow).

Initial person binding forms in minutes of co-occurrence; consolidation to reliable, viewpoint-invariant identity requires varied exemplars over days to weeks (Andrews, Jenkins, Sherrill & Burton, 2015, *Cognition*; Jenkins et al., 2011, *Cognition*; Schweinberger et al., 2014). Exemplar diversity matters more than count.

**Design mapping:** **[constrains]** Following CLS theory, the identity system implements two phases:

1. **Fast binding (hippocampal analogue):** On first encounter, new agents are minted immediately. Individual exemplar embeddings (each voice observation, each face observation) are stored in a per-agent exemplar buffer with timestamps and context. During the fast-binding phase, identity matching uses nearest-exemplar comparison against the buffer, preserving the specific observations rather than averaging them away.
2. **Slow consolidation (neocortical analogue):** As the exemplar buffer accumulates varied observations, the system periodically consolidates exemplars into centroid representations (running averages). Once the centroid stabilizes (sufficient exemplar diversity, measured by intra-cluster variance), matching transitions from exemplar-based to centroid-based. The exemplar buffer is pruned to retain only diverse exemplars, keeping memory bounded.

This two-phase approach follows CLS theory: the exemplar buffer is the fast episodic store, and the centroid is the consolidated prototype. The transition from exemplar-based to centroid-based matching is the consolidation process.

**Content workspace (speculative):** When the content workspace (option F) is enabled, speaker and face embeddings register as processors for z_k cycle-consistency training. This *could* serve as an additional slow-consolidation mechanism, with z_k learning cross-modal mappings over time. However, the mechanism by which z_k would interact with the identity system is not specified in this proposal. This is flagged as a speculative future integration, not a designed feature.

## What Changes

- **Speaker embedding extraction in audition.** The audition module gains a speaker embedding extractor that runs alongside the existing emotion/STT pipeline, implementing a dedicated voice-identity pathway (constrained by the separable-streams finding; Belin & Zatorre, 2003). Each processed audio window publishes an `audition.speaker_embedding` event carrying the embedding vector, source label, and confidence. Gated by a config flag; ships disabled.
- **Face detection and embedding in vision.** The vision module gains a face detection + embedding pipeline that runs per-frame alongside the existing clip encoder, implementing a dedicated face-identity pathway (constrained by the FFA's distinct role in Haxby et al.'s core system). Each frame with detected faces publishes a `vision.face_detection` event carrying per-face embeddings, bounding boxes, and confidence. Gated by a config flag; ships disabled.
- **AgentModel as Person Identity Node.** The AgentModel dataclass gains `voice_centroid` (192-dim), `face_centroid` (128-dim), per-modality exemplar buffers, sample counts, modality binding state, and binding confidence. Following Burton & Bruce (1993), the PIN stores separate modality-specific representations rather than a merged embedding. The `familiarity()` method is extended to incorporate embedding-based evidence. Serialization and fork/merge cover the new fields.
- **Two-phase identity learning.** New agents use exemplar-based matching (fast binding); after sufficient diverse observations, the system consolidates to centroid-based matching (slow consolidation), following CLS theory.
- **Identity consumers in social cognition.** The social cognition module gains three new event consumers: a speaker identification consumer (matches `audition.speaker_embedding` against known voice exemplars/centroids), a face identification consumer (matches `vision.face_detection` against known face exemplars/centroids), and a cross-modal binder. The binder uses temporal co-occurrence as a Hebbian-style learning signal, operating as a convergence zone (architecturally analogous to pSTS) that associates voice and face events within a configurable window.
- **New bus events.** `audition.speaker_embedding` (embedding, source_label, confidence), `vision.face_detection` (per-face embeddings, bounding boxes, confidence, face_count), and `social_cognition.identity_update` (agent_id, modality, confidence, is_new).
- **Content workspace processor registration (speculative).** When the content workspace (option F) is enabled, speaker embeddings (192-dim) and face embeddings (128-dim) register as processors for z_k. The interaction between z_k's cycle-consistency training and the identity system is unspecified in this proposal and is deferred to design.
- **Privacy note.** Face and voice embeddings are biometric identifiers. They are stored on-device only, never transmitted (existing no-outbound policy), and travel with the entity through preservation bundles. The operator is responsible for consent in multi-person settings. This is flagged for a future privacy review but does not block the design.

## Capabilities

### New Capabilities
- `social-cognition/identity-binding`: Cross-modal identity binding. Matches speaker embeddings and face embeddings to known agents via exemplar buffers (fast binding) and consolidated centroids (slow consolidation), binding voice and face to the same agent through temporal co-occurrence in a convergence-zone binder, and publishing identity updates when agents are recognized or newly encountered.

### Modified Capabilities
- `social-cognition`: AgentModel gains embedding centroid fields, exemplar buffers, and sample counts, serving as a Person Identity Node (pointer/index into modality-specific representations, not a merged embedding); `familiarity()` extended with embedding evidence; the module gains speaker-embedding and face-detection event consumers that identify agents by perceptual similarity rather than operator-set labels; fork/merge reconciles the new fields.
- `audition`: New `audition.speaker_embedding` event type published by a config-gated speaker embedding extractor alongside the existing pipeline, implementing a separable voice-identity pathway.
- `vision`: New `vision.face_detection` event type published by a config-gated face detection and embedding pipeline alongside the existing clip encoder, implementing dedicated face-identity processing.
- `deployment-tiers`: The capability matrix gains a row for perceptual identity (speaker + face recognition), present at Tier 2 through the full pipeline, absent at Tier 0 and Tier 1 (models not provisioned).

## Known Gaps and Future Work

- **pSTS analogue for changeable face features** (expression, gaze, lip movement → emotion/attention, not identity). Not in scope; may be addressed by a future face-expression pipeline.
- **Task-gated cross-modal binding.** The brain gates cross-modal coupling by task demands (von Kriegstein & Giraud, 2006). The current binder runs whenever both modalities are active. Task-gating via workspace attention is future work.
- **Graded reliability weighting.** The brain adjusts cross-modal integration weights by statistical reliability (Ernst, 2007). The current binder uses binary bind decisions. Graded weighting is future work.
- **Two-level voice representation.** TVAs encode acoustic voice signatures; right IFC encodes abstracted identity. The current design has a single embedding level.
- **Haxby extended system.** Amygdala (emotion from faces) and auditory cortex (lip-reading) pathways are out of scope.
- **Content workspace interaction.** How z_k's cross-modal training integrates with the identity system is unspecified; deferred to design.

## Impact

- Code: `kaine/modules/social_cognition/agent.py` (new fields + exemplar buffer), `kaine/modules/social_cognition/store.py` (embedding storage/search), `kaine/modules/social_cognition/module.py` (new consumers + binder), `kaine/modules/audition/module.py` (speaker embedding extraction), `kaine/modules/vision/module.py` (face detection + embedding), `kaine/workspace/content.py` (new processors, speculative), `kaine/lifecycle/strategies.py` (merge of new fields), `kaine/boot/factories/` (wiring).
- Dependencies: sherpa-onnx (already present for STT/TTS; speaker embedding models are an additional download), OpenCV (already present or trivially added; YuNet and SFace are OpenCV Zoo models loaded via `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF`).
- Models: WeSpeaker CAM++ (~29 MB ONNX), YuNet (~230 KB ONNX), SFace (~35 MB ONNX). All consent-gated downloads via the existing provision system. Total ~65 MB additional.
- Memory: ~65 MB model weights on Orin Nano Super (all CPU inference), plus exemplar buffer memory (~1.5 KB per exemplar, bounded per agent). Well within the ~2.3 GB headroom after the existing cognitive stack.
- Config: New `[social_cognition]` keys for speaker/face identification thresholds, model selection, cross-modal binding window, exemplar buffer limits, and consolidation thresholds. All ship disabled.
