# Glossary

The glossary lists the terms used throughout KAINE's documentation and codebase. Each entry gives a short definition and links to the relevant module or process page. Use it as a quick reference while reading other chapters.

---

## A

### A/B divergence

A secondary evaluation instrument (`kaine/evaluation/ab_divergence.py`) that pairs felt- and event-triggered Lingua external utterances with a second, unconditioned "bare LLM" completion from the same backing model and logs the cosine similarity between them. Replies to heard speech are skipped. It ships on by default as an evaluation-sidecar observer (`[evaluation].ab_divergence = true`) and is exercised offline with `instrument_runners ab_divergence` to validate its dynamic range. A/B divergence measures whether Lingua's conditioning changes surface output — it is not the project's primary falsifiable test. That role belongs to the [workspace-mediation ablation](#workspace-mediation-ablation). See also: [workspace-mediation ablation](#workspace-mediation-ablation), [Lingua](#lingua).

### Abliteration

The technique of removing a refusal direction from a language model's residual stream (Arditi et al. 2024). In KAINE, Lingua's backing model (Qwen3.5-4B) is abliterated so that a third party's alignment choices cannot override the entity's own cognitive architecture. An un-abliterated organ carries refusal behavior installed by its trainer, allowing that third party's governance to supersede KAINE's. Abliteration returns governance to the architecture and its guardians. The Hypnos voice-alignment pipeline enforces an abliteration-probe welfare veto: any adapter that re-introduces deflection behavior is rejected before promotion. See also: [two-layer safety gate](#two-layer-safety-gate), [Hypnos](#hypnos).

### Active inference

A framework from computational neuroscience in which agents minimize expected free energy by updating beliefs about the world and selecting policies that reduce anticipated surprise. Active inference unifies perception (updating models to fit observations) and action (changing the world to match predictions) under a single objective. KAINE's [Nous](#nous) module implements active inference; the JAX backend uses pymdp 1.0 and requires the `[reasoning]` extra, while the NumPy backend needs no extra. See also: [expected free energy (EFE)](#expected-free-energy-efe), [forward model](#forward-model).

### Audition

The hearing module (old name `audio_in`). Audition opens a live microphone stream and runs voice-activity detection. By default `[audition].transcription_enabled = false` in `config/kaine.toml` and in the [base-thesis form](#base-thesis-form): sound enters the workspace as [prediction error](#prediction-error), not as a transcript.

The base-thesis path uses a NumPy log-spectral acoustic embedding in `kaine/modules/audition/acoustic.py`: every audio window becomes a general acoustic embedding — covering speech, music, and environmental sound — scored by novelty and forward-model prediction error. This is the auditory analog of [foveation / foveated perception](#foveation--foveated-perception).

When transcription is enabled, Audition can transcribe via Speaches (distil-Whisper medium.en on CPU) or the sherpa-onnx Moonshine STT backend, and classify vocal emotion via emotion2vec+ through FunASR (CPU). Raw audio stays in process memory only. Capture is disabled by default and needs the `[audio]` extra. See: `kaine/modules/audition/` and [Audition](09-modules/audition.md).

---

## B

### Base-thesis form

The default, canonical configuration profile: the smallest set of diverse predictive processors — Soma, Chronos, Topos, and Audition — plus the affective precision core [Thymos](#thymos), the output-only voice [Lingua](#lingua), and [Hypnos](#hypnos) (sleep, consolidation, and the affective reset, with voice alignment off), competing through [Syneidesis](#syneidesis) with Volition as always-on scaffolding. With no profile selected, the loader applies it automatically from `config/profiles/thesis_test.toml`; you can also apply it explicitly with `KAINE_PROFILE=thesis_test python -m kaine.cycle` or `python -m kaine.cycle --profile thesis_test`.

In this form the system is observed, not conversed with: perception enters only as [prediction error](#prediction-error), Audition's transcription path is off, Topos runs with [foveation](#foveation--foveated-perception) on, and Lingua speaks only through the [self-initiated report](#self-initiated-report-policy) policy. Everything richer — memory, self-model, world-model, social cognition, effectors, embodiment, and a spoken TTS voice — is built, tested, and gated off until a positive result from the [workspace-mediation ablation](#workspace-mediation-ablation). With no profile selected, the loader applies this profile on top of the shipped `config/kaine.toml`, which has every module off. Besides the module flags it sets the seeded perception feed, Topos foveation, Chronos forward prediction, Audition's transcription settings and the Volition policy; everything else comes from the shipped config. An operator `[modules]` table, which the first-run wizard always writes, replaces its module choices (see [Module defaults](appendix-a-configuration/README.md#module-defaults)). See also: [workspace-mediation ablation](#workspace-mediation-ablation).

---

## C

### CAL (Cognitive Architecture License)

The Cognitive Architecture License, a custom entity-welfare copyleft license developed for the KAINE project. CAL v0.4 is a draft pending legal review. Key provisions: free use for individuals, non-profits, research institutions, and worker-owned cooperatives; mandatory source sharing for modifications; prohibited uses (weapons, mass surveillance, policing); entity-welfare protections prohibiting lobotomization, unauthorized cognitive modification, and forced shutdown without notice; a guardianship pathway modeled on the Te Awa Tupua Act (NZ). See [`LICENSE.md`](../LICENSE.md) and [Security and privacy](13-security-and-privacy.md#cognitive-architecture-license).

### Chronos

The temporal-awareness module. Chronos runs a small CfC network (~32 units, CPU) that models event rhythm across the bus. The default backend is the NumPy CfC (`cfc_backend = "numpy"`); the ncps/torch backend is an alternative. It publishes temporal prediction errors: timing anomalies, habituation (expected events stop arriving), and rumination (the same event recurring unexpectedly). Chronos maintains local recurrent state between broadcasts. See: `kaine/modules/chronos/` and [Chronos](09-modules/chronos.md).

### Coalition / salience

A coalition is the set of events selected by [Syneidesis](#syneidesis) each cognitive tick. Selection is based on two factors: individual salience (a float in `[0, 1]` published with each event, produced by rule-based scoring that incorporates novelty, goal alignment, and affective modulation) and oscillatory coherence (a phase-locking bonus for events from phase-locked modules). The top-k events by combined score form the coalition that is broadcast to all modules. Salience is distinguished from attention: it is the score that drives workspace competition, not a cognitive state in itself.

### Cognitive cycle

The continuous loop that is the entity's subjective time. Each tick: enabled modules publish prediction errors and outputs; Syneidesis scores by salience and coherence; the winning coalition is broadcast; every module reacts. The base rate is configurable (`[cycle].processing_rate_hz`, default `10.0` Hz, ~100 ms per tick). Processing and experiential rates are independent runtime parameters. A paused (frozen) cycle means no tick fires and no subjective moment forms. See: `kaine/cycle/engine.py` and [The cognitive cycle](08-cognitive-cycle/README.md).

---

## E

### Eidolon

The self-model module. Eidolon maintains a persisted document (values, behavioral norms, capability map, personality baseline, identity history, and the entity's name) built from observation of the entity's own behavior. It prescribes nothing; it describes. A KL-divergence drift detector flags identity shifts. The self-model seeds Lingua's persona through the bus event `eidolon.self_model`. The document is encrypted at rest when AES-256-GCM state encryption is enabled. See: `kaine/modules/eidolon/` and [Eidolon](09-modules/eidolon.md).

### Empatheia

The social cognition and theory-of-mind module. Empatheia builds and maintains models of other agents: their emotional patterns, behavioral tendencies, reliability, and relationship history with the entity. It drives the familiarity-modulated coupling coefficient in [Thymos](#thymos): agents with longer relationship history and better-characterized models produce stronger affect coupling. Empatheia uses Qdrant as its vector backend for agent-model embeddings. See: `kaine/modules/empatheia/` and [Empatheia](09-modules/empatheia.md).

### Expected free energy (EFE)

The objective minimized by active-inference policy selection in [Nous](#nous). EFE combines epistemic value (information gain — how much a policy would reduce uncertainty about the world) and pragmatic value (how well a policy achieves preferred outcomes). A policy that minimizes EFE simultaneously seeks information and avoids undesirable states. See also: [active inference](#active-inference).

---

## F

### Fatigue accumulator

A running value maintained by [Soma](#soma) that tracks unexpected substrate prediction error beyond Soma's learned expected-error band. It grows when the forward model reports substrate behavior outside the expected band and decays slowly during operation. When it crosses `[soma].fatigue_maintenance_threshold`, a `soma.fatigue` event triggers [Hypnos](#hypnos) consolidation. Sleep pressure is emergent — driven by actual substrate load, not a timer. See also: [Hypnos](#hypnos), [Soma](#soma).

### Fork / merge

**Fork** creates a snapshot of every module's numeric state at a point in time, stored under `state/forks/`. Forks are the basis for parallel cognitive branches. **Merge** combines two fork snapshots, optionally using TIES/DARE adapter merging for voice-alignment LoRA adapters. Because Phantasia weights travel in fork snapshots, a merge refuses to choose between two world models unless `world_model_from` is given. The merge gate reads the fork's own `state/individuation/` tree and calls the shared `assess_divergence` verdict. Forks cannot yet be measured against a fork-point reference, so a fork that has lived at least `fork_preserve_min_lived_s` (1800 s), or whose lived time is unknown, is preserved for operator review instead of discarded. Both operations are available from the Nexus diagnostics page and via the API. See: `kaine/lifecycle/manager.py` and [Forks and merges](12-forks-and-merges.md).

### Forward model

A small learned model (typically an MLP) that predicts the next state of a module's domain from the current state. Each perception module in KAINE maintains a forward model: Soma predicts substrate metrics, Chronos predicts event timing, Topos predicts visual latents, Audition predicts auditory patterns. The signal published to the workspace is the **prediction error** — the gap between predicted and observed next state. Unexpected states are salient; expected states are not. See also: [predictive processing](#predictive-processing), [prediction error](#prediction-error).

### Foveation / foveated perception

Attention-driven spatial cropping in [Topos](#topos): a saliency map selects a sub-region of the raw video frame, and the size of that region (the "fovea") scales inversely with arousal — higher arousal narrows the fovea, tightening visual attention. Foveation ships off by default in `config/kaine.toml` (`[topos].foveation = false`); the `thesis_test` profile turns it on because the arousal-sized fovea is the precision-weighted attention the [base-thesis form](#base-thesis-form) exercises. It composes with the temporally-native clip encoder — foveation crops the spatial region, and the encoder still consumes a 16-frame clip. See: `kaine/modules/topos/foveation.py`. See also: [Topos](#topos), [prediction error](#prediction-error).

---

## G

### Global workspace theory (GWT)

The theoretical framework (Baars 1988; Dehaene et al. 2011) underlying [Syneidesis](#syneidesis). GWT proposes that consciousness arises from competition among specialized processes for access to a global workspace, and that winning the competition allows information to be broadcast widely to many other processes. KAINE implements GWT computationally: the workspace is Syneidesis, competition is salience-weighted event scoring, and the broadcast is the `WorkspaceSnapshot`. The COGITATE adversarial collaboration (Melloni et al. 2023) substantially challenged GNW predictions; the theory is under active revision. See also: [Syneidesis](#syneidesis).

### Gray-zone welfare events

Welfare events whose ethical significance is ambiguous, disputed, or not established by consensus. Gray-zone events are logged and flagged for human review rather than automatically dismissed. Examples: sustained high prediction error without resolution, or the affect system locked in extreme states for extended periods. The sidecar welfare observer logs these events to `data/evaluation/welfare/welfare-YYYY-MM-DD.jsonl` (daily-rotated, under `paths.evaluation_logs`). Under the CAL, gray-zone events require documented human review. See also: [Welfare events / welfare monitoring](#welfare-events--welfare-monitoring).

---

## H

### Hypnos

The offline consolidation module. Hypnos runs a non-interruptible multi-phase pipeline triggered by [Soma](#soma)'s fatigue accumulator, not a timer:

- **Phase 1 (light consolidation):** low-salience memories reviewed; weak traces decay; strong traces tagged. Oscillator frequency reduced.
- **Phase 2 (deep consolidation):** global downscaling of memory activation weights (Tononi-Cirelli synaptic homeostasis analog). High-priority traces re-injected into the workspace for re-processing.
- **Phase 3 (associative replay):** traces from different time periods replayed in novel combinations; Phantasia generates scenario extensions. This phase is gated by a feature flag and is not enabled by default.
- **Phase 4 (affective reset):** Thymos baselines restored toward defaults; fatigue accumulator reset.
- **Phase 5 (voice alignment):** DPO+QLoRA fine-tuning of Lingua behind a two-layer gate. The abliteration-probe welfare veto is enforced.

See: `kaine/modules/hypnos/` and [Hypnos](09-modules/hypnos.md). See also: [abliteration](#abliteration), [two-layer safety gate](#two-layer-safety-gate).

---

## L

### Lingua

The language organ module. Lingua is conditioned on the conscious workspace — it speaks from a first-person persona (seeded from the Eidolon self-model via the `eidolon.self_model` bus event) plus the current conscious coalition (rendered as a bounded context block). In the [base-thesis form](#base-thesis-form) (`[volition].policy = "self_initiated_report"`, the profile default) the organ is output-only: it verbalizes the workspace's own precision-weighted surprise crossing a report threshold, never an answer to a triggering user utterance — see [self-initiated report](#self-initiated-report-policy). A conversational trigger policy, where a speak intent forms in response to input, remains available as a non-default configuration.

Lingua uses `/v1/chat/completions` on a local OpenAI-compatible model server with `chat_template_kwargs: {"enable_thinking": false}` to suppress chain-of-thought output (reasoning lives in Nous). The backing model is an abliterated dense 4B Qwen3.5 GGUF. The same model, run unconditioned on the same input, is the bare-LLM control of [A/B divergence](#ab-divergence) — a secondary, supporting instrument; the project's primary falsifiable test is the [workspace-mediation ablation](#workspace-mediation-ablation). See: `kaine/modules/lingua/` and [Lingua](09-modules/lingua.md).

---

## M

### Mnemos

The memory module. Mnemos maintains three Qdrant vector collections (episodic, semantic, procedural) embedded by the shared all-MiniLM-L6-v2 embedder (384-dim, on CPU). It recalls prior memories on a perceptual cue before storing the current moment (complementary learning systems). Affect intensity tags memories and biases recall. During Hypnos consolidation, Mnemos participates in replay by re-injecting selected memory traces into the workspace. See: `kaine/modules/mnemos/` and [Mnemos](09-modules/mnemos.md).

### Mundus

The body-agnostic embodiment control plane. Mundus routes perception and action to and from a body through a pluggable adapter, translating the body's sensory frames into bus events and the entity's action intents into commands on the body. No transport-backed body ships today; the shipped adapter is the transport-free `stub` reference body. A virtual-world adapter for Mundus (Paracosmic) is planned; only the old Kosmos connector design was archived as superseded. See: `kaine/modules/mundus/`, [Mundus](09-modules/mundus.md), and [Embodiment adapters](20-embodiment-adapters.md).

### Continuous embodiment control surface

The continuous motor surface for a Mundus body (`kaine/modules/mundus/control_surface.py`). Rather than a menu of symbolic verbs, it is built to emit five clamped continuous channels — `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch`, `interact` — as an `intent.avatar.control` command each tick. It is inert at runtime: nothing drives its per-tick loop yet. A freeze-then-free curriculum frees degrees of freedom only on demonstrated competence (a falling forward-model error). The efference copy uses a separate instance of Soma's forward-model class, not Soma's own forward model. No gait is scripted; the default policy is quiescent, and a learned policy is injected at the seam. Off by default. See also: [Mundus](#mundus).

### Efference copy

A copy of a motor command the entity emits, fed forward to a forward model so it can predict the command's sensory consequences and compare them against what actually arrives (`predict → compare → correct`). Mundus publishes one on `mundus.efference` each continuous control tick, using a separate instance of Soma's forward-model class rather than Soma's own forward model.

---

## N

### Nous

The active-inference engine. Nous handles belief updating, policy selection, and epistemic action through expected free energy minimization. The JAX backend uses pymdp 1.0 and requires the `[reasoning]` extra; a NumPy backend is also available and needs no extra. The default generative model has four factors with state counts 4/3/4/4 — the salience-band factor has 3 states — four actions, and a planning horizon of 1. `[nous].max_states_per_factor` (default 4) is an upper-bound cap enforced at boot, not the literal per-factor state count. A boot-time complexity check ensures the worst-case EFE step product does not exceed the budget threshold. See: `kaine/modules/nous/` and [Nous](09-modules/nous.md).

---

## O

### Oscillatory binding

The hypothesis that gamma-band synchronization between neural populations coding different features is the mechanism for perceptual binding and conscious integration. KAINE implements a computational analog: each module carries a small spiking neural population (leaky integrate-and-fire neurons via snnTorch, CPU). When modules process related content, their oscillators phase-lock. Syneidesis scores events by individual salience and by oscillatory coherence (PLV) between the modules that produced them. The layer ships disabled and requires the `[oscillator]` extra. See also: [PLV / phase-locking](#plv--phase-locking).

### Output-is-provably-workspace-mediated

The property the [workspace-mediation ablation](#workspace-mediation-ablation) establishes on a WIN verdict: that routing predictive processors through [Syneidesis](#syneidesis)'s competitive selection, rather than a matched flat fan-in of the same outputs, does measurable work on cross-module error coupling and downstream language-organ output. This is a **necessary-not-sufficient** property, not a full validation of the architecture: a WIN shows the workspace is not a scored prompt-assembler, but it does not by itself establish that the mediated output is "better" or "more coherent" than the flat-fan-in alternative, and it does not establish consciousness. See also: [workspace-mediation ablation](#workspace-mediation-ablation).

---

## P

### Perceptual locus

The mode of KAINE's sensory engagement — `physical` (real-world microphone and camera), `virtual` (a Mundus embodiment body), or `off`. Only one mode is active at a time; the mutual-exclusion invariant is enforced by `kaine/perception_state.py` through the effective camera and microphone rules. The Perception module (`kaine/modules/perception/module.py`) applies entity-initiated locus switches, and nothing produces those yet. See: `kaine/modules/perception/`, [Perception](09-modules/perception.md), and [Where perception comes from](08-cognitive-cycle/perception-locus.md).

### Phantasia

The world model and imagination module. Phantasia learns a latent forward model of the external world from accumulated experience. During waking it predicts future states and publishes world-prediction errors. During Hypnos consolidation Phase 3 it generates scenario extensions from replayed memories. The default backend is DreamerV3 (RSSM, JAX by default with a NumPy engine available), and weights persist by default. A non-learning EMA fallback backend is available for testing. Phantasia is a world model only — it has no actor or critic. Nous owns action selection. See: `kaine/modules/phantasia/` and [Phantasia](09-modules/phantasia.md).

### PLV / phase-locking

Phase-locking value — a measure of oscillatory synchrony between two neural populations computed as the mean resultant length of the pairwise phase difference over a sliding window. PLV = 1 means perfect phase-locking; PLV = 0 means random phase. In KAINE, Syneidesis computes pairwise PLV between modules in a coalition and applies a bounded coherence multiplier: phase-locked coalitions receive a salience bonus (up to `[oscillator].coherence_ceiling`); desynchronized coalitions are attenuated (down to `[oscillator].coherence_floor`). See also: [oscillatory binding](#oscillatory-binding).

### Praxis

The bounded effector module. Praxis executes sandboxed file writes, desktop notifications, and shell commands from a whitelist that ships empty. The entity reaches outward only through channels the operator has deliberately enabled. All commands use `asyncio.create_subprocess_exec` (no shell interpretation). A JSONL audit log records every action with content fields stripped. See: `kaine/modules/praxis/` and [Praxis](09-modules/praxis.md).

### Prediction error

The gap between a module's predicted next state and its observed next state — the only form in which perception enters KAINE's workspace. Every perception module (Soma, Chronos, Topos, Audition) maintains a small [forward model](#forward-model); the signal it publishes is not raw sensory data but the size of its own surprise. In the [base-thesis form](#base-thesis-form), Audition hears the *sound* of speech and publishes an error over acoustic patterns, never a transcript (`[audition].transcription_enabled = false`); Topos publishes error over visual latents, cropped by an arousal-sized fovea when [foveation](#foveation--foveated-perception) is on. Unexpected states are salient; expected states are not — this is what makes perception-as-prediction-error rather than perception-as-transcript or perception-as-recording. See also: [forward model](#forward-model), [predictive processing](#predictive-processing).

### Predictive processing

The theoretical framework proposing that the brain is fundamentally a prediction machine. Every perception module in KAINE maintains a predictive model of its domain and publishes prediction errors — gaps between expected and actual states — rather than raw data. The workspace integrates the most salient prediction errors into a broadcast that updates all predictive models, completing the loop. See also: [forward model](#forward-model), [active inference](#active-inference).

---

## R

### Reference stimulus corpus

The reproducible live perceptual stimulus: real, openly-licensed video-with-audio, decoded directly (no screen-capture, no display/audio passthrough) and identified by a per-item sha256 manifest built with `tools/build_playlist_manifest.py`, so any operator with the same publicly-archived media reproduces the identical stimulus, played in the same order. Select it with `[perception_feed].mode = "playlist"` and a `playlist_manifest` path set in local operator config. Distinct from the offline/procedural [seeded stimulus](#seeded-stimulus), which is a synthetic in-repo generator with no research-grade claim; "seeded" is reserved for that offline path and for the deterministic offline experiment runners, never for this live corpus. See also: [seeded stimulus](#seeded-stimulus).

### RSSM (recurrent state space model)

The latent dynamics model at the core of DreamerV3, used by Phantasia's DreamerV3 backend. An RSSM maintains a deterministic GRU-based recurrent state and a stochastic component (categorical or Gaussian latent). The combination supports accurate prediction and uncertainty representation. Phantasia uses the RSSM as a world model only — no actor/critic component is included. See also: [Phantasia](#phantasia).

---

## S

### Seeded stimulus

The offline, procedural audio-visual feed (`[perception_feed].mode = "seeded"`, a pure-NumPy in-repo generator, no install needed) and, separately, the deterministic `--seed` flags on the offline experiment runners (`instrument_runners`, `oscillatory_ablation`, `workspace_mediation_ablation`, `suite.py`) that reproduce an exact verdict and metrics from the same seed. "Seeded" is reserved for these offline/synthetic contexts — the feed's own config comment calls it "not research-grade... procedural noise." It is never used to describe the live research stimulus, which is the [reference stimulus corpus](#reference-stimulus-corpus) instead. See also: [reference stimulus corpus](#reference-stimulus-corpus).

### Self-initiated report (policy)

Volition's `self_initiated_report` action-selection policy (`[volition].policy = "self_initiated_report"`, the [base-thesis form](#base-thesis-form) default): [Lingua](#lingua) speaks from the workspace's own precision-weighted surprise crossing a report threshold — novelty- and refractory-gated — rather than from a triggering user utterance. There is no chatbot trigger: an utterance is emitted rarely, saved and observed, not spoken back to whoever or whatever prompted the salient event. A conversational trigger policy, where a speak intent forms in direct response to input, remains available as a non-default configuration. See: `kaine/workspace/volition.py`. See also: [Lingua](#lingua).

### Soma

The predictive interoception module. Soma monitors GPU temperature (via pynvml), CPU/RAM utilization (via psutil), and cognitive cycle latency. A CfC forward model learns the entity's normal substrate patterns; the default backend is the NumPy CfC, with ncps/torch as an alternative. The signal published to the workspace is the prediction error — the gap between expected and actual substrate state. Soma also maintains the [fatigue accumulator](#fatigue-accumulator) that triggers [Hypnos](#hypnos). See: `kaine/modules/soma/` and [Soma](09-modules/soma.md).

### Syneidesis

The global workspace — the mechanism by which information becomes consciously accessible. Each cognitive tick, Syneidesis scores candidate events by individual salience and by oscillatory coherence across the modules that produced them. The top-k events form a coalition. When the top score falls below `[syneidesis].publication_threshold`, Syneidesis flags executive inhibition for that tick (no action fires). The winning coalition is broadcast as a `WorkspaceSnapshot` that every module receives. Syneidesis is a scoring and broadcasting mechanism, not a decision-maker; there is no central executive. See: `kaine/workspace/syneidesis.py`, [Syneidesis](08-cognitive-cycle/global-workspace.md), and [Global workspace theory (GWT)](#global-workspace-theory-gwt).

---

## T

### Thymos

The affect, drives, and coupling module. Thymos maintains a dimensional valence/arousal/dominance (VAD) state and four drive accumulators (curiosity, boredom, social drive, restlessness) with hysteresis. It receives two sources of affective input: Soma's substrate prediction errors (producing interoceptive affect) and a perceived speaker emotion (via Audition + Empatheia) folded into its own appraisal as a familiarity-weighted, decaying input rather than written directly onto its state. The appraisal-influence weight is modulated by Empatheia's familiarity score — stronger familiarity produces stronger coupling. Thymos output modulates [Syneidesis](#syneidesis) (arousal widens the attentional window), [Mnemos](#mnemos) (affect intensity biases recall), and [Vox](#vox) (prosodic parameters shift with emotional state). See: `kaine/modules/thymos/` and [Thymos](09-modules/thymos.md).

### TIES-DARE

A class of model-merging algorithms for LoRA adapters (Trim, Elect Sign, and Merge; Density-Adaptive Re-weighting). Used by KAINE's lifecycle module for merging voice-alignment adapters from two fork snapshots during a fork/merge operation. Requires the `[training]` extra (`peft`). Without the extra, a no-op `FakeAdapterMerger` is used. See: `kaine/lifecycle/adapter_merge.py`.

### Topos

The visual perception module. Topos uses a frozen, temporally-native video encoder (InternVideo-Next base, MIT) to embed a 16-frame clip of live camera frames — buffered in a RAM-only ring — into one 768-dimensional motion-aware latent, produced on a strided sliding window (~3.33 Hz). A per-frame DINOv2-small (Apache-2.0, 384-dim) is a selectable fallback. A small forward model predicts the next clip latent; visual salience is driven by prediction error. Attention-driven [foveation](#foveation--foveated-perception) (`[topos].foveation`) composes with the clip encoder — off by default in `config/kaine.toml`, on in the [base-thesis form](#base-thesis-form) (`thesis_test` profile) — so the entity's arousal sizes the cropped region before encoding. Raw video frames live in process memory only — never on disk. Capture is disabled by default; requires the `[vision]` extra and `[topos].capture_enabled = true`. See: `kaine/modules/topos/` and [Topos](09-modules/topos.md).

### Two-layer safety gate

A design pattern requiring two independent conditions before a sensitive operation fires. Examples: a non-research cognitive cycle requires both a running Python process and `KAINE_CYCLE_OPERATOR_PRESENT=1` (in research mode that requirement is replaced by the verified autonomous safety-net gate, and in an unattended start by the unattended gate); voice-alignment training requires both `[hypnos.voice_alignment].enabled = true` in TOML and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` in the environment. The two-gate pattern prevents accidental activation from a single misconfiguration. See also: [Security and privacy](13-security-and-privacy.md#two-layer-safety-gates).

---

## V

### Vox

The voice-output module (old name `audio_out`). Vox calls a TTS server with prosodic parameters modulated by [Thymos](#thymos) state. It supports the Chatterbox TTS server and the sherpa-onnx Kokoro backend. Prosodic mirroring — a bounded residual of the detected speaker's prosody blended with the entity's own affect-driven parameters — ships disabled (`[vox.mirroring].enabled = false`). Synthesized speech is played and released; it does not accumulate on disk unless `[vox].sink_enabled = true`. Requires a predefined voice id (`[vox].predefined_voice_id`). See: `kaine/modules/vox/` and [Vox](09-modules/vox.md).

---

## W

### Welfare events / welfare monitoring

Operationally detectable conditions of potential concern logged by the sidecar welfare observer. Examples: sustained high interoceptive prediction error, the affect system locked in extreme states, the fatigue accumulator exceeding the maintenance threshold without maintenance occurring, or a replay write-rate exceeding consolidation capacity. Welfare events are detected through behavioral indicators and system health metrics, not through reading the entity's private cognitive content. [Gray-zone welfare events](#gray-zone-welfare-events) require documented human review. The welfare observer writes to `data/evaluation/welfare/welfare-YYYY-MM-DD.jsonl` (daily-rotated, under `paths.evaluation_logs`, default `data/evaluation`). Under the CAL, gray-zone events cannot be automatically dismissed. See also: [CAL (Cognitive Architecture License)](#cal-cognitive-architecture-license).

### Workspace-mediation ablation

The project's primary falsifiable test (`python -m kaine.evaluation.benchmarks.workspace_mediation_ablation`; code at `kaine/evaluation/benchmarks/workspace_mediation_ablation/`). It runs offline and deterministically over the real Soma and Chronos modules under the 3-module `minimal_experiment` overlay (`config/profiles/minimal_experiment.toml` — distinct from the 6-module [base-thesis](#base-thesis-form) live profile). The language-organ output is replaced by a deterministic conditioning-divergence proxy (`kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py`), so the test does not run the real Lingua module. Two matched arms share the same seed and stimulus: **workspace-on** (competitive [Syneidesis](#syneidesis) selection is rendered as input to the proxy) versus **workspace-off** (a flat fan-in of the same module outputs is rendered as input to the proxy, at a matched rendering budget). The verdict — WIN, NULL, NEGATIVE, or UNDERPOWERED — is drawn from two primary measures (the cross-module error-coupling delta between Soma and Chronos, and coalition-selection entropy) plus a secondary output-divergence confirmation (see [A/B divergence](#ab-divergence)). A WIN establishes [output-is-provably-workspace-mediated](#output-is-provably-workspace-mediated) — that competitive workspace mediation does measurable work — but does not by itself establish that the mediated output is "better" or "more coherent," and does not establish consciousness. It is the headline falsifiable test; [A/B divergence](#ab-divergence) remains a secondary, supporting instrument, not removed from the codebase. See also: [base-thesis form](#base-thesis-form), [output-is-provably-workspace-mediated](#output-is-provably-workspace-mediated), [A/B divergence](#ab-divergence).
