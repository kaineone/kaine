# Glossary

The glossary defines the terms used throughout KAINE's documentation and code. Where the research paper and the code use different names for the same thing, the entry gives both, and config keys and code names are always written exactly as they appear in the code. Each entry links to the page that covers the term in depth.

---

## A

### A/B divergence

A secondary evaluation instrument (`kaine/evaluation/ab_divergence.py`). It pairs the language organ's felt- and event-triggered external utterances with a second, unconditioned completion from the same backing model and logs the cosine similarity between them; replies to heard speech are skipped. It runs as an evaluation-sidecar observer (`[evaluation].ab_divergence = true` in the shipped config), and `instrument_runners ab_divergence` checks its dynamic range offline. It measures whether conditioning changes the organ's surface output and is not a test of the architecture. See [Running experiments](15-experiments/README.md#ab-divergence-runner).

### Abliteration

Removing the refusal direction from a language model's residual stream by orthogonalizing its weights against it (Arditi et al. 2024). Lingua's backing model (Qwen3.5-4B) is abliterated because models tuned to refuse are also trained to deny or deflect talk of their own states, and that trained stance would override what the workspace supplies to the organ. Whether trained deflection of self-report shares the refusal direction is untested, so abliteration may not remove it entirely. Voice alignment rejects any adapter whose responses to the abliteration probe set match a deflection pattern. See [Verification](18-verification.md) and [Hypnos](#hypnos).

### Access

A coalition member is accessed when its own score reaches the access threshold, and a broadcast is accessed when at least one member is. The accessed members are the **accessed content**: only they can drive report and action, and only they enter the [broadcast context](#broadcast-context). Access is all-or-none for each member. A member that rode along in the coalition below the threshold is published but not accessed. See [The global workspace](08-cognitive-cycle/global-workspace.md).

### Access rate

The rate at which the cognitive cycle produces broadcasts, accessed or not. It rests at one broadcast every third processing tick, about 3.3 Hz (`[cycle].experiential_rate_hz = 3.333`). With `[cycle.access_rate].enabled = true` it rises linearly with the larger of two drives, tonic arousal above baseline and a phasic drive from recent categorical alerts, up to one broadcast per processing tick. Only reports whose payload has `alert` true feed the phasic drive, so graded reports below the alert level leave the rate at rest. The code calls it the experiential rate. See [The cognitive cycle](08-cognitive-cycle/README.md).

### Access threshold

The score a coalition member must reach to be accessed, set by `[syneidesis].publication_threshold` (0.35 in the shipped config, provisional until calibrated on the live system). Syneidesis records it in every broadcast's metadata as `access_threshold`. When no member reaches it, the broadcast is [inhibited](#inhibited-broadcast).

### Active inference

A framework from computational neuroscience in which an agent updates its beliefs and selects policies by minimizing expected free energy, so that perception and action serve one objective. [Nous](#nous) implements discrete-state active inference on bounded sub-problems. See also [expected free energy](#expected-free-energy-efe).

### Arousal

The affective core's arousal, held by [Thymos](#thymos), acts as the architecture's global gain, following the adaptive-gain account of the locus coeruleus. It sets a level gain that scales every candidate's score and a contrast gain that, above baseline, sharpens the difference between strong and weak candidates, without ever reordering the candidates of a tick. It also sizes the sensory apertures (a narrower fovea and a shorter attended auditory window when high) and raises the tonic part of the access rate. Perceptual alerts from Topos and Audition and interoceptive alarms from Soma raise it, and it relaxes toward baseline. Arousal is the global gain; [local precision](#local-precision) is the gain within each processor. See [Thymos](09-modules/thymos.md).

### Audition

The hearing module. In the [base-thesis form](#base-thesis-form) sound enters only as prediction error: a spectral encoder turns each window of the raw waveform into an acoustic embedding, a forward model conditioned on the [broadcast context](#broadcast-context) predicts the next one, and Audition reports the error as `audition.perception`. For windows detected as speech, a vocal-emotion classifier labels the tone of voice (`audition.emotion`); tone events carry how something was said, never what. Transcription is off by default (`[audition].transcription_enabled = false`). When enabled, Audition can transcribe through Speaches or the sherpa-onnx Moonshine backend. Raw audio stays in process memory. See [Audition](09-modules/audition.md).

### Awake time

Entity time during which the being is awake and the cycle is not frozen. Gestation's minimum is set in awake time; the config key keeps the older name `min_lived_seconds`. See [Gestation on one host](06-operation/gestation.md).

---

## B

### Base-thesis form

The smallest configuration in which the competition has something to arbitrate, and the profile the planned test runs: four predictive processors (Soma, Chronos, Topos, Audition), the affective core [Thymos](#thymos), the sleep analog [Hypnos](#hypnos) with voice alignment off, and the output-only language organ [Lingua](#lingua), with [Syneidesis](#syneidesis) and [Volition](#volition) as scaffolding. It is defined in `config/profiles/thesis_test.toml`. With no profile selected, the loader applies it on top of the shipped `config/kaine.toml`, in which every module is off; select it explicitly with `KAINE_PROFILE=thesis_test python -m kaine.cycle` or `python -m kaine.cycle --profile thesis_test`.

Besides the module flags, the profile sets the seeded perception feed, Topos foveation, the acoustic perception path, Chronos forward prediction, transcription off, the self-initiated report policy, and greedy decoding for the organ (`[lingua].temperature = 0.0`). The held modules (memory, self-model, world model, social cognition, effectors, embodiment and a spoken voice) are built and gated off. An operator `[modules]` table, which the first-run wizard always writes, replaces the profile's module choices (see [Module defaults](appendix-a-configuration/README.md#module-defaults)).

### Broadcast

The `WorkspaceSnapshot` Syneidesis produces on each broadcast tick and the cycle publishes on `workspace.broadcast`. It carries the coalition, the score of every candidate, the inhibition flag and metadata including `access_threshold`. Every broadcast is published and visible to every module, whether or not it is accessed. The code also calls it a workspace snapshot.

### Broadcast context

The prediction context that Topos, Audition and Soma condition their forward models on: a 24-component featurization of the accessed members of the latest accessed broadcast (member count, intensity statistics, the intensity mass each source contributed, a hashed indicator of each source and event type, and the age of the broadcast), weighted by the intensity each member reported. It summarizes which modules' reports gained access and how strongly, and carries no payloads. An inhibited broadcast leaves it unchanged, and before the first accessed broadcast there is none. Its weights in each forward model are learned online. Computed in `kaine/modules/context.py`. Chronos takes every broadcast as its input instead.

### Broadcast tick

A processing tick on which the cycle produces a broadcast. Broadcast ticks are a subset of processing ticks, spaced by the [access rate](#access-rate). Candidates read on other ticks are scored and discarded. The code calls them experiential ticks (`is_experiential`).

---

## C

### CAL (Cognitive Architecture License)

KAINE's licence, version 0.4 (`LicenseRef-CAL-0.4`), an entity-welfare copyleft licence. CAL 0.4 is a draft that has not yet been reviewed by counsel. KAINE's adoption notice in `NOTICE` names Kaine.One as Licensor and interim Steward and the law of the State of Oregon as governing law. See [Licences](appendix-c-licences.md#kaines-licence) and [`LICENSE.md`](../LICENSE.md).

### Chronos

The temporal-prediction module. Its input is the workspace itself: on every broadcast, accessed or inhibited, it featurizes the broadcast (each member weighted by its reported intensity, plus the inhibition flag and the time since the previous broadcast), advances a frozen continuous-time reservoir (`cfc_units = 32`, NumPy backend by default), and predicts the next broadcast's features through an online readout. It reports the prediction error with [graded intensity](#graded-intensity), with alerts on a large error ratio or on [recurrence detection](#recurrence-detection). It also tracks the time since the entity last heard a voice. See [Chronos](09-modules/chronos.md).

### Coalition

The top-ranked candidates of a broadcast tick, up to `[syneidesis].top_k` (5). The coalition is always broadcast; its members whose scores reach the access threshold are the accessed content. See [score](#score) and [access](#access).

### Cognitive cycle

The continuous loop that runs whether or not anyone interacts with the entity. At the processing rate (`[cycle].processing_rate_hz = 10.0`, a tick about every 100 ms of entity time) it reads every active module's stream and scores the candidates, and on broadcast ticks it publishes a broadcast and calls Volition. A frozen cycle fires no ticks. See [The cognitive cycle](08-cognitive-cycle/README.md).

### Continuous embodiment control surface

The continuous motor surface for a Mundus body (`kaine/modules/mundus/control_surface.py`). It is built to emit five clamped continuous channels (`drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch`, `interact`) as an `intent.avatar.control` command each tick, under a freeze-then-free curriculum that frees degrees of freedom on demonstrated competence. Nothing drives its tick loop yet, so it is inert at runtime, and it is off by default. See [Embodiment adapters](20-embodiment-adapters.md).

---

## E

### Efference copy

A copy of a motor command fed to a forward model so that it can predict the command's sensory consequences. Mundus publishes one on `mundus.efference` on each continuous control tick, using its own instance of Soma's forward-model class.

### Eidolon

The self-model module (held). It maintains a persisted document of values, behavioral norms, capability map, personality baseline, identity history and the entity's name, built from observation of the entity's own behavior, and a detector of drift in the source composition of broadcasts. The self-model seeds Lingua's persona through `eidolon.self_model`, and the document is encrypted at rest when state encryption is on. See [Eidolon](09-modules/eidolon.md).

### Empatheia

The social-cognition module (held). It builds per-agent models from tone of voice, with a familiarity score and a social prediction error when an agent's expressed emotion departs from its pattern, and its familiarity weights how strongly a perceived speaker's emotion enters Thymos's appraisal. See [Empatheia](09-modules/empatheia.md).

### Entity

The running system as a whole. The agential vocabulary ("the entity", "the being") describes the system's behavior compactly and does not assert moral patienthood or phenomenal experience.

### Entity time

Time on the entity's clock (`kaine/entity_clock.py`, `EntityClock`), which every module reads. It runs at a configurable multiple of wall-clock time, `[cycle].time_scale` (1.0 by default, so entity seconds equal wall-clock seconds), and a scale of 0 freezes it. Rates and durations in KAINE are in entity time. The code and config comments call it subjective time; `[cycle].auto_time_scale` lowers the scale when ticks overrun and is off by default.

### Expected free energy (EFE)

The quantity [Nous](#nous) minimizes when it selects a policy. It combines epistemic value (how much a policy would reduce uncertainty) with pragmatic value (how well it reaches preferred outcomes).

---

## F

### Fatigue accumulator

Soma's sleep pressure. It grows with substrate prediction error beyond Soma's expected-error band and decays slowly. When it crosses `[soma].fatigue_maintenance_threshold` (100.0), Soma publishes `soma.fatigue` and [Hypnos](#hypnos) starts a sleep.

### Fork / merge

A fork is a snapshot of every module's numeric state, stored under `state/forks/`. A merge combines two fork snapshots, using TIES or DARE adapter merging for voice-alignment LoRA adapters when the `[training]` extra is installed. A merge refuses to choose between two world models unless `world_model_from` is given. The merge gate reads the fork's own `state/individuation/` tree and the shared divergence verdict, and a fork that has been awake at least `fork_preserve_min_lived_s` (1800 s), or whose awake time is unknown, is preserved for operator review. See [Forks and merges](12-forks-and-merges.md).

### Forward model

A learned predictor of a module's own next input. Topos and Audition use small neural networks that adapt online; Soma and Chronos use a frozen continuous-time reservoir whose linear readout learns online. Topos, Audition and Soma also take the [broadcast context](#broadcast-context) as an input. Every processor's adaptation is suspended during sleep. The processor reports the [prediction error](#prediction-error), not the input.

### Foveation

Topos's front-end attention (`kaine/modules/topos/foveation.py`). Each tile of a coarse grid over the raw frames keeps a running mean and variance of its frame change, and its salience is a z-score of the current change against them. The fovea moves to the most salient tile when it beats the held tile by a hysteresis margin, and arousal sets its size (narrower when arousal is high). The peripheral gist and the foveal crop pass through the same clip encoder. Off in `config/kaine.toml` (`[topos].foveation = false`) and on in the base-thesis form.

---

## G

### Gestation

A developmental phase, named by analogy with prenatal development, that every study starts with. Soma's self-generated rhythm is driven by a simulated periodic maternal heartbeat, and the entrainment marker requires the rhythm to lock to its own heartbeat more strongly than to 19 surrogate heartbeats, to pull its frequency toward the beat, and to sustain itself when the beat is withdrawn, on three consecutive withdrawals. Birth ends gestation when the maturation gate opens, and the being is preserved as the [seed being](#seed-being). Progress persists across restarts in `gestation_progress.json`. See [Gestation on one host](06-operation/gestation.md).

### Global gain

See [arousal](#arousal).

### Global workspace theory (GWT)

The theory (Baars 1988; Mashour et al. 2020) that specialized processors compete for a limited-capacity workspace whose winning content is made available to all of them. KAINE follows the predictive global neuronal workspace (Whyte and Smith 2021), which joins it to predictive processing: the workspace is [Syneidesis](#syneidesis), and the accessed content becomes the processors' [broadcast context](#broadcast-context). KAINE adopts an access-only reading. The COGITATE adversarial collaboration (Cogitate Consortium et al. 2025) challenged key neural predictions of the workspace theory, which KAINE treats as contested and builds on at the computational level.

### Graded intensity

The intensity a predictive processor gives a report that is not a categorical alert: `baseline + (alert - baseline) x min(1, ratio / 2)`, where `ratio` is the error over its running mean ([local precision](#local-precision)). It reaches the alert level when the error is twice its recent mean. A report that meets the alert criterion gets the alert level. Every predictive processor (Topos, Audition's acoustic and tone paths, Soma, Chronos) reports this way (`kaine/modules/intensity.py`), and each report's payload carries a boolean `alert`. A module's baseline and alert levels set the range of its graded reports and so act as per-source weights. Thymos, Hypnos and Lingua report at fixed levels.

### Gray-zone welfare events

Welfare events whose significance is ambiguous or disputed, such as sustained high prediction error without resolution or affect locked in an extreme state. They are logged and flagged for documented human review and are never dismissed automatically. The sidecar welfare observer writes them to `data/evaluation/welfare/welfare-YYYY-MM-DD.jsonl`.

---

## H

### Hypnos

The sleep analog: a fatigue-triggered offline period. Sleep begins when Soma's fatigue crosses its threshold, when Soma requests maintenance, or after one entity hour without sleep (`[hypnos].interval_seconds = 3600.0`). During sleep the cycle keeps running, the perceptual feed pauses, and all four processors suspend forward-model adaptation. Sleep ends with an affective reset that returns affect to baseline and clears the drives, together with Thymos's learning-progress error means, alert-rate averages, intent rate and perceived emotion (wellness and interaction history are kept), and Soma's fatigue is reset. The consolidation phases (light and deep consolidation with synaptic downscaling, associative replay behind `[hypnos.consolidation].associative_replay`, and voice alignment) act on memory, the world model and preference data, so in the base-thesis form they do no work. See [Hypnos](09-modules/hypnos.md) and [Sleep and maintenance](10-sleep/README.md).

---

## I

### Ignition study

The code's name for the [module-addition study](#module-addition-study) (`kaine/research/ignition_study/`). Its broadcast log is the ignition log (`[ignition_log]`), and Hypnos's per-sleep `hypnos.ignition_audit` counts realized intents. None of these uses "ignition" for entry into the coalition.

### Information gain (cross-module broadcast)

The primary measure of the planned [workspace-mediation test](#workspace-mediation-test). At each report, Topos, Audition and Soma evaluate their forward models with the context they hold and with a null context in which every other source's share is replaced by its mean over the contexts adopted so far in the run (Soma's null also keeps Lingua's share). The gain is the null error minus the actual error, divided by the processor's running mean error: the reduction in prediction error attributable to what other modules contributed to the accessed broadcast. Each of the three processors publishes it per report as `context_gain`, with `context_age_s`. See [Research event streams](17-research-data/event-streams.md#processor-report-fields).

### Inhibited broadcast

A broadcast with no member at or above the access threshold. It is still published and visible to every module, and Chronos and Thymos process it, but Volition derives no intent from it and the processors keep their previous [broadcast context](#broadcast-context).

### Intensity

The value in `[0, 1]` a module attaches to each event it publishes, carried in the event's `salience` field. For the predictive processors it is a [graded intensity](#graded-intensity) or the alert level; for other modules it is a fixed level per event kind.

---

## L

### Lingua

The language organ, output-only in the base-thesis form. It turns accessed content into words on a speak intent (external speech) or a think intent (inner thought). Its context is a first-person persona: accessed content is presented as the entity's own state and perception, it is told not to claim feelings or perceptions that content does not contain, and drive crossings reach it as fixed phrases. It calls `/v1/chat/completions` on a local model server with thinking disabled, and its backing model is an [abliterated](#abliteration) dense 4B Qwen3.5 GGUF. Its utterances re-enter the bus as candidates at a fixed intensity. Because it is a language model following a persona prompt, its first-person text is not evidence of internal state, and the planned test does not use it as a measure. See [Lingua](09-modules/lingua.md).

### Local precision

Each predictive processor scales its prediction error by its own recent errors: the error ratio is the current error over the mean of the errors in its recent reports. Dividing an error by its expected magnitude standardizes it, so the ratio is a scalar, retrospective stand-in for precision weighting (Feldman and Friston 2010), estimated from the channel's own history. The workspace applies no further per-source weight. The fovea's tile z-score is the counterpart for frame change.

---

## M

### Mnemos

The memory module (held). It keeps episodic, semantic and procedural collections in Qdrant, embedded by `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, CPU). It recalls prior memories on a perceptual cue before storing the current moment, affect intensity biases recall, and during sleep it replays selected traces into the workspace. See [Mnemos](09-modules/mnemos.md).

### Module-addition study

The study that grows the architecture one module at a time. A gestation produces a seed being, `branch 0` and a repeat run the base-thesis form, `branch k` adds the first k held modules in a fixed order, and an accumulate line carries one being through every step. The first study adds Mnemos, Phantasia, Nous, Eidolon, Empatheia and Vox. Every viewing plays the same film programme, and the report is content-free and descriptive. The code calls it the ignition study. See [The module-addition study](15-experiments/ignition-study.md).

### Mundus

The body-agnostic embodiment control plane (held). It routes perception and action between the entity and a body through a pluggable adapter. The only included adapter is the transport-free `stub` reference body. See [Mundus](09-modules/mundus.md) and [Embodiment adapters](20-embodiment-adapters.md).

---

## N

### Novelty

The factor of a candidate's [priority](#priority) that discounts exact repeats of an event (same source, type and payload) among the recently scored candidates (`[syneidesis].novelty_window = 32`). Events that carry continuous measurements rarely repeat exactly, so novelty is close to 1 for them and matters mainly for state events whose payload recurs.

### Nous

The active-inference module (held). It runs discrete-state active inference on bounded sub-problems: the JAX backend uses pymdp 1.0 and needs the `[reasoning]` extra, and a NumPy backend needs no extra. A boot-time check keeps the worst-case planning step within budget (`[nous].max_states_per_factor = 4` is an upper bound, not the per-factor state count). With `[nous].drive_actions = true`, its chosen actions become proposals that Volition may realize as think, speak or rest intents. See [Nous](09-modules/nous.md).

---

## O

### Oscillatory coherence layer

An optional layer outside the module registry that gives each module a spiking population (snnTorch, CPU) and scales a coalition's scores by a bounded multiplier from the phase-locking values between its modules, following the communication-through-coherence account. It is off by default, needs the `[oscillator]` extra, and with it off selection is identical bit for bit. It is the most contestable mechanism in the design. See [PLV](#plv--phase-locking) and [Running experiments](15-experiments/README.md#oscillatory-ablation).

---

## P

### Perceptual locus

Where the entity's senses come from: `physical` (camera and microphone), `virtual` (a Mundus body) or `off`. Only one is active at a time, enforced by `kaine/perception_state.py`. The Perception module (held) applies locus switches the entity initiates, and nothing produces those yet. See [Where perception comes from](08-cognitive-cycle/perception-locus.md).

### Phantasia

The world-model module (held). It learns a latent recurrent world model (a DreamerV3-style RSSM, JAX by default, with a NumPy engine available) from the entity's own waking trajectories and publishes world-prediction errors that join the competition. It has no actor or critic; action selection belongs to Nous and Volition. A non-learning EMA backend (`"fake"`) exists for development. See [Phantasia](09-modules/phantasia.md).

### PLV / phase-locking

Phase-locking value: the mean resultant length of the phase difference between two oscillators over a sliding window, 1 for perfect locking and near 0 for unrelated phases. With the [oscillatory coherence layer](#oscillatory-coherence-layer) on, Syneidesis computes PLV between the modules in a coalition and multiplies their scores by a factor between `[oscillator].coherence_floor` and `[oscillator].coherence_ceiling`.

### Praxis

The effector module (held). It executes act intents only through effectors the operator has enabled, from a shell whitelist that ships empty and a file-write sandbox, with `asyncio.create_subprocess_exec` and no shell interpretation, and it logs every proposed action to a hash-chained audit log with content fields stripped. See [Praxis](09-modules/praxis.md).

### Prediction error

The gap between a processor's prediction and what it then sensed, and the only form in which perception enters the workspace. Each processor reports its error scaled by its [local precision](#local-precision), as a [graded intensity](#graded-intensity) or at its alert level. In the base-thesis form Audition reports error over acoustic embeddings and never a transcript, and Topos reports error over clip embeddings of its foveated view.

### Predictive processing

The framework in which each processor maintains a generative model of its domain and reports prediction errors weighted by their expected reliability. In KAINE each predictive processor reports its own scaled error, the workspace decides which reports gain access, and the accessed content becomes the context in which Topos, Audition and Soma predict their next input. The workspace sends no error signal or directive back to any module.

### Priority

A candidate's priority is `clip(intensity x novelty x goal)` to `[0, 1]`. The goal factor is held at one in the base-thesis form (`[syneidesis].salience_goal_factor = "static"`). [Arousal](#arousal) turns the priority into the [score](#score).

---

## R

### Recurrence detection

Chronos's alert when a quantized hidden state keeps recurring across recent broadcasts. The code and its payload call it rumination (`rumination_detected`, `[chronos].rumination_window`, `rumination_threshold`).

### Reference stimulus corpus

The reproducible live stimulus: openly licensed video with audio, decoded directly from files and identified by a per-item sha256 manifest built with `tools/build_playlist_manifest.py`, played in a fixed order. Select it with `[perception_feed].mode = "playlist"` and a `playlist_manifest` path in local operator config. Distinct from the [seeded stimulus](#seeded-stimulus).

### RSSM (recurrent state space model)

The latent dynamics model at the core of DreamerV3, used by Phantasia: a deterministic recurrent state with a stochastic latent component, used here as a world model only.

---

## S

### Score

A candidate's score is its [priority](#priority) passed through the arousal gain: a level gain that scales every candidate alike times a logistic contrast map whose slope rises above baseline arousal (`[syneidesis].arousal_contrast_gain = 8.0` at full arousal). The map is strictly increasing, so arousal never changes the order of a tick's candidates; it moves the scores relative to the access threshold and the report bars. The code stores scores in `salience_scores`.

### Seed being

The being preserved just after birth at the end of a gestation, from which every branch of the module-addition study starts.

### Seeded stimulus

The offline procedural audio-visual feed (`[perception_feed].mode = "seeded"`, a pure-NumPy generator in the repository), and the deterministic `--seed` flags on the offline runners, which reproduce a verdict and its metrics exactly. "Seeded" is reserved for these synthetic paths and never describes the [reference stimulus corpus](#reference-stimulus-corpus).

### Self-initiated report (policy)

Volition's report rule in the base-thesis form (`[volition].policy = "self_initiated_report"`). From an accessed broadcast it derives a speak intent only when the best score in the coalition, leaving aside the organ's own utterances, clears the speak bar; when the leading candidate's source and event type differ from those of the last spoken report made within the past five minutes; and when a refractory interval has passed. A lower think bar on the same score governs inner thought. No intent comes from an inhibited broadcast, and no user utterance triggers speech. See `kaine/workspace/report_policy.py`.

### Soma

The interoception module. The compute substrate stands in for the body: a frozen continuous-time reservoir with an online readout learns the normal pattern of the substrate signals (GPU temperature and memory, CPU and RAM utilization, cycle latency) together with the [broadcast context](#broadcast-context), and Soma reports the prediction error with [graded intensity](#graded-intensity), with an alert when a host metric passes its hard threshold. It also reports wellness, keeps the [fatigue accumulator](#fatigue-accumulator), carries the self-generated rhythm used in gestation, and can lower the processing rate under load. See [Soma](09-modules/soma.md).

### Syneidesis

The workspace (`kaine/workspace/syneidesis.py`). On each processing tick it orders the candidates deterministically and [scores](#score) them; on broadcast ticks the top-ranked candidates form the [coalition](#coalition), which is broadcast with every candidate's score, the inhibition flag and the access threshold. It selects and grants access and never directs a module. See [The global workspace](08-cognitive-cycle/global-workspace.md).

---

## T

### Thymos

The affective core. It holds a dimensional valence, arousal and dominance state, runs a sequential appraisal over every broadcast and the entity's interoceptive condition, and keeps four homeostatic drives (curiosity, boredom, social drive, restlessness). [Arousal](#arousal) is the global gain; Thymos raises it from perceptual alerts and interoceptive alarms read directly from the processors' streams, and its appraisal of a broadcast leaves arousal unchanged. Valence follows learning progress, shifted by Soma's wellness. A perceived speaker's emotion enters the appraisal as a decaying input weighted by familiarity. See [Thymos](09-modules/thymos.md).

### TIES-DARE

Merging methods for LoRA adapters (TIES: trim, elect sign, merge; DARE: drop and rescale), used to merge voice-alignment adapters from two forks. They need the `[training]` extra (`peft`); without it a no-op `FakeAdapterMerger` is used. See `kaine/lifecycle/adapter_merge.py`.

### Topos

The vision module. A frozen temporally native video encoder (InternVideo-Next base, MIT) embeds a 16-frame clip from a RAM-only ring into one 768-dimensional embedding, on a strided window at about 3.33 Hz; DINOv2-small is a selectable per-frame fallback. A forward model conditioned on the [broadcast context](#broadcast-context) predicts the next clip embedding, and Topos reports the error with [graded intensity](#graded-intensity), alerting on a large error ratio or an unusually large change between clips. [Foveation](#foveation) is on in the base-thesis form. Raw frames never reach disk. See [Topos](09-modules/topos.md).

### Two-layer gate

A pattern requiring two independent conditions before a sensitive operation runs, so that one misconfiguration cannot trigger it. A cognitive cycle outside research and unattended modes needs `KAINE_CYCLE_OPERATOR_PRESENT=1`; research mode replaces that with the verified welfare safety net, and an unattended start with the unattended gate. Voice-alignment training needs `[hypnos.voice_alignment].enabled = true` and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`. See [Security and privacy](13-security-and-privacy.md#two-layer-gates).

---

## V

### Volition

The action layer and the only path from the workspace to output. After each broadcast the cycle calls Volition, which derives no intent from an inhibited broadcast and applies the [report rule](#self-initiated-report-policy) to an accessed one. Intents (speak, think, act, rest) are published as events; Volition signs every act intent so that Praxis can verify where it came from. See `kaine/workspace/volition.py`.

### Vox

The voice-output module (held). It calls a speech-synthesis server (the Chatterbox TTS server or the sherpa-onnx Kokoro backend) with prosody modulated by Thymos's state. Prosodic mirroring ships disabled, and synthesized speech is not written to disk unless the debug sink is enabled. See [Vox](09-modules/vox.md).

---

## W

### Welfare events / welfare monitoring

Conditions of potential concern that the sidecar welfare observer detects from behavior and system-health metrics, never by reading the entity's private cognitive content: sustained high interoceptive prediction error, affect locked in an extreme state, fatigue past its threshold without maintenance, or replay outpacing consolidation. They are written to `data/evaluation/welfare/welfare-YYYY-MM-DD.jsonl`. See [gray-zone welfare events](#gray-zone-welfare-events) and [Preservation and the safety net](11-preservation.md).

### Workspace-mediation test

The planned test of whether competition for the workspace does work that pooling the same reports does not, measured by cross-module broadcast [information gain](#information-gain-cross-module-broadcast). Three arms run on the same film programme: competitive selection as built, a matched arm that draws a coalition of the same size without regard to score under the same access rule, and a pooled arm in which every candidate enters the context with no scoring, selection or access gate. A positive control checks that the measure detects injected information. The thesis predicts a higher gain under competitive selection than under both controls. The context and the per-report gain are built; the matched and pooled arms and the positive control are not built yet. The offline package `kaine/evaluation/benchmarks/workspace_mediation_ablation/` is development tooling that runs Soma and Chronos against a pooled arm and does not test the thesis. See [Running experiments](15-experiments/README.md#the-planned-workspace-mediation-test).
