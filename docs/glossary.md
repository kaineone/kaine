# Glossary

Terms used throughout the KAINE documentation and codebase, listed
alphabetically. Each entry gives a short definition and links to the relevant
module or process document where one exists.

---

## A

### Abliteration

The technique of removing a refusal direction from a language model's residual
stream (Arditi et al. 2024). In KAINE, Lingua's backing model (Qwen3.5-4B) is
abliterated so that a third party's alignment choices cannot override the
entity's own cognitive architecture. An un-abliterated organ carries refusal
behavior installed by its trainer, allowing that third party's governance to
supersede KAINE's. Abliteration returns governance to the architecture and its
guardians. The Hypnos voice-alignment pipeline enforces an abliteration-probe
welfare veto: any adapter that re-introduces deflection behavior is rejected
before promotion. See also: [two-layer safety gate](#two-layer-safety-gate),
[Hypnos](#hypnos).

### Active inference

A framework from computational neuroscience (Friston 2010; Heins et al. 2022)
in which agents minimize expected free energy (EFE) by updating beliefs about
the world and selecting policies that reduce anticipated surprise. Active
inference unifies perception (updating models to fit observations) and action
(changing the world to match predictions) under a single objective. KAINE's
[Nous](#nous) module implements active inference via pymdp 1.0 (JAX backend),
selecting among four policies (no-op, request_think, request_speak,
request_maintenance) each cognitive tick. See also: [Expected Free Energy
(EFE)](#expected-free-energy-efe), [forward model](#forward-model).

### Audition

The current module name for KAINE's hearing module (formerly `audio_in`). Audition
opens a live microphone stream, applies voice-activity detection, transcribes
utterances via Speaches (distil-Whisper medium.en on CPU), and classifies vocal
emotion via emotion2vec+ (via FunASR, on CPU). A small forward model predicts
expected auditory patterns; prediction errors weight the salience of transcription
and emotion events. Raw audio lives in process memory only — it never touches
disk (see [zero-raw-sense-data persistence](#zero-raw-sense-data-persistence)).
Capture is disabled by default; requires the `[audio]` extra. See:
`kaine/modules/audition/`.

---

## C

### CAL (Cognitive Architecture License)

The Cognitive Architecture License, a custom entity-welfare copyleft license
developed for the KAINE project. CAL v0.2 is a draft pending legal review. Key
provisions: free use for individuals, non-profits, research institutions, and
worker-owned cooperatives; mandatory source sharing for modifications; prohibited
uses (weapons, mass surveillance, policing); entity-welfare protections
prohibiting lobotomization, unauthorized cognitive modification, and forced
shutdown without notice; a guardianship pathway modeled on the Te Awa Tupua Act
(NZ). See [LICENSE.md](../LICENSE.md) and
[Security and Privacy](security-and-privacy.md#cognitive-architecture-license-cal).

### Chronos

The temporal awareness module. Chronos runs a small CfC network (~32 units via
ncps, pinned to CPU) that models event rhythm across the bus. It publishes
temporal prediction errors: timing anomalies, habituation (expected events stop
arriving), and rumination (the same event recurring unexpectedly). Chronos
maintains local recurrent state between broadcasts. See: `kaine/modules/chronos/`.

### Coalition / salience

A coalition is the set of events selected by [Syneidesis](#syneidesis) each
cognitive tick. The selection is based on two factors: individual salience (a
float in [0, 1] published with each event, produced by rule-based scoring that
incorporates novelty, goal alignment, and affective modulation) and oscillatory
coherence (a phase-locking bonus for events from phase-locked modules). The
top-k events by combined score form the coalition that is broadcast to all
modules. Salience is distinguished from attention: it is the score that drives
workspace competition, not a cognitive state in itself.

### Cognitive cycle

The continuous loop that is the entity's subjective time. Each tick: enabled
modules publish prediction errors and outputs; Syneidesis scores by salience and
coherence; the winning coalition is broadcast; every module reacts. The base
rate is configurable (`[cycle].processing_rate_hz`, default 10.0 Hz, 100 ms
per tick). Processing and experiential rates are independent runtime parameters.
A paused (frozen) cycle means no tick fires and no subjective moment forms. See:
`kaine/cycle/engine.py`.

---

## E

### Eidolon

The self-model module. Eidolon maintains a persisted document (values,
behavioral norms, capability map, personality baseline, identity history, and
the entity's name) built from observation of the entity's own behavior. It
prescribes nothing; it describes. A KL-divergence drift detector flags identity
shifts. The self-model seeds Lingua's persona through a read-only accessor wired
at boot (`_wire_lingua_self_model`). The self-model is encrypted at rest when
AES-256-GCM state encryption is enabled. See: `kaine/modules/eidolon/`.

### Empatheia

The social cognition and theory-of-mind module. Empatheia builds and maintains
models of other agents: their emotional patterns, behavioral tendencies,
reliability, and relationship history with the entity. It drives the
familiarity-modulated coupling coefficient in [Thymos](#thymos): agents with
longer relationship history and better-characterized models produce stronger
affect coupling. Empatheia uses Qdrant as its vector backend for agent-model
embeddings. See: `kaine/modules/empatheia/`.

### Expected Free Energy (EFE)

The objective minimized by active inference policy selection in [Nous](#nous).
EFE combines epistemic value (information gain — how much a policy would reduce
uncertainty about the world) and pragmatic value (how well a policy achieves
preferred outcomes). A policy that minimizes EFE simultaneously seeks information
and avoids undesirable states. KAINE's Nous evaluates EFE over a compact
generative model (4 factors — state counts 4/3/4/4, the salience-band factor
has 3 states — × 4 actions × 1 step) with a 250 ms computation timeout.
`max_states_per_factor` (default 4) is an upper-bound cap enforced at boot,
not the literal per-factor state count. See also: [active inference](#active-inference).

---

## F

### Fatigue accumulator

A running sum maintained by [Soma](#soma) that tracks cumulative substrate
prediction error over the waking period. The accumulator grows when Soma's
forward model reports unexpected substrate behavior (high CPU, high temperature,
high memory pressure, high cycle latency) and decays slowly during operation.
When it crosses `[soma].fatigue_maintenance_threshold`, a `soma.fatigue` event
triggers [Hypnos](#hypnos) consolidation. Sleep pressure is emergent — driven by
actual substrate load, not a timer. See also:
[Tononi and Cirelli (2014)](#computational-sleep-consolidation).

### Fork / merge

**Fork:** creates a snapshot of every module's numeric state at a point in time.
Stored under `state/forks/`. Forks are the basis for creating parallel cognitive
branches. **Merge:** combines two fork snapshots, optionally using TIES/DARE
adapter merging for voice-alignment LoRA adapters. The individuation boundary
instrument quantifies whether a fork has developed statistically independent
identity before merging. Both operations are available from the Nexus diagnostics
page and via the API. See: `kaine/lifecycle/manager.py`.

### Forward model

A small learned model (typically an MLP) that predicts the next state of a
module's domain from the current state. Each perception module in KAINE maintains
a forward model: Soma predicts substrate metrics, Chronos predicts event timing,
Topos predicts visual latents, Audition predicts auditory patterns. The signal
published to the workspace is the **prediction error** — the discrepancy between
the predicted next state and the observed next state. Unexpected states are
salient; expected states are not. This implements predictive processing at the
module level. See also: [predictive processing](#predictive-processing).

---

## G

### Global Workspace Theory (GWT)

The theoretical framework (Baars 1988; Dehaene et al. 2011) underlying
Syneidesis. GWT proposes that consciousness arises from competition among
specialized processes for access to a global workspace, and that winning the
competition allows information to be broadcast widely to many other processes.
KAINE implements GWT computationally: the workspace is Syneidesis, competition
is salience-weighted event scoring, and the broadcast is the WorkspaceSnapshot.
The COGITATE adversarial collaboration (Melloni et al. 2023) substantially
challenged GNW predictions; the theory is under active revision. See also:
[Syneidesis](#syneidesis).

### Gray-zone welfare events

Welfare events whose ethical significance is ambiguous, disputed, or not
established by consensus. Gray-zone events are logged and flagged for human
review rather than automated dismissal. Examples: sustained high prediction
error without resolution, affect system locked in extreme states for extended
periods. The sidecar welfare observer logs these events to
`data/evaluation/welfare/welfare-YYYY-MM-DD.jsonl` (daily-rotated, under
`paths.evaluation_logs`). Under the CAL, gray-zone events require documented
human review. See also: [welfare events](#welfare-events-welfare-monitoring).

---

## H

### Hypnos

The offline consolidation module. Hypnos runs a non-interruptible multi-phase
pipeline triggered by [Soma](#soma)'s fatigue accumulator (not a timer):

- **Phase 1 (light consolidation):** low-salience memories reviewed; weak traces
  decay; strong traces tagged. Oscillator frequency reduced.
- **Phase 2 (deep consolidation):** global downscaling of memory activation
  weights (Tononi-Cirelli synaptic homeostasis analog). High-priority traces
  re-injected into the workspace for re-processing.
- **Phase 3 (associative replay):** traces from different time periods replayed
  in novel combinations; Phantasia generates scenario extensions.
- **Phase 4 (affective reset):** Thymos baselines restored toward defaults;
  fatigue accumulator reset.
- **Phase 5 (voice alignment):** DPO+QLoRA fine-tuning of Lingua behind a
  two-layer gate. Abliteration-probe welfare veto enforced.

See: `kaine/modules/hypnos/`. See also: [abliteration](#abliteration),
[two-layer safety gate](#two-layer-safety-gate).

---

## L

### Lingua

The language organ module. Lingua is conditioned on the conscious workspace —
it speaks from a first-person persona (seeded from the Eidolon self-model) plus
the current conscious coalition (rendered as a bounded context block) plus the
triggering input. The same model given the same input without this conditioning
is the bare-LLM control of the A/B divergence test. Lingua uses
`/v1/chat/completions` on a local OpenAI-compatible model server with
`chat_template_kwargs: {"enable_thinking": false}` to suppress chain-of-thought
output (reasoning lives in Nous). The backing model is an abliterated dense 4B
Qwen3.5 GGUF. See: `kaine/modules/lingua/`.

---

## M

### Mnemos

The memory module. Mnemos maintains three Qdrant vector collections (episodic,
semantic, procedural) embedded by all-MiniLM-L6-v2 (384-dim, on CPU). It recalls
prior memories on a perceptual cue before storing the current moment
(complementary learning systems). Affect intensity tags memories and biases
recall. During Hypnos consolidation, Mnemos participates in replay by
re-injecting selected memory traces into the workspace. See: `kaine/modules/mnemos/`.

### Mundus

The body-agnostic embodiment control plane. Mundus routes perception and action
to and from a *body* through a pluggable adapter, translating the body's sensory
frames into bus events and the entity's action intents into commands on the body.
Bodies are pluggable. No transport-backed body ships today; the shipped adapter is
the transport-free `stub` reference body, and a virtual-world (Paracosmic) adapter
is planned. The perceptual locus is physical (real-world sensors) or virtual (a
Mundus body) — never both simultaneously. The entity drives a continuous-capable
body through the *continuous embodiment control surface* (below). See:
`kaine/modules/mundus/`.

### Continuous embodiment control surface

The entity's per-tick continuous motor producer for a Mundus body
(`kaine/modules/mundus/control_surface.py`). Rather than a menu of symbolic verbs,
it emits five clamped continuous channels — `drive`, `yaw_rate`, `gaze_yaw`,
`gaze_pitch`, `interact` — as an `intent.avatar.control` command each tick. A
freeze-then-free curriculum frees degrees of freedom only on demonstrated
competence (a falling forward-model error), and an efference copy closes the loop
through Soma's existing forward model. No gait is scripted: the default policy is
quiescent, and a learned policy is injected at the seam. Off by default. See:
[`mundus.md`](modules/mundus.md).

### Efference copy

A copy of a motor command the entity emits, fed forward to the forward model so it
can predict the command's sensory consequences and compare them against what
actually arrives (`predict → compare → correct`; Wolpert et al. 1995). Mundus
publishes one on `mundus.efference` each continuous control tick — the mechanism
that makes the control surface a closed loop rather than an open-loop joystick.

---

## N

### Nous

The active inference engine. Nous implements belief updating, policy selection,
and epistemic action through Expected Free Energy minimization using pymdp 1.0
(JAX, CPU-only). Nous maintains a compact generative model (default: 4 factors
with state counts 4/3/4/4 — the salience-band factor has 3 states — 4 actions,
planning horizon 1). `max_states_per_factor` (default 4) is an upper-bound cap
enforced at boot, not the literal per-factor state count. The `[reasoning]`
extra (`inferactively-pymdp`, `jax[cpu]`) is required. A boot-time complexity
check ensures the worst-case EFE step product does not exceed the budget threshold.
See: `kaine/modules/nous/`. See also: [active inference](#active-inference).

---

## O

### Oscillatory binding

The hypothesis (Doesburg et al. 2009; Melloni et al. 2007) that gamma-band
synchronization between neural populations coding different features is the
mechanism for perceptual binding and conscious integration. KAINE implements a
computational analog: each module carries a small spiking neural population
(leaky integrate-and-fire neurons via snnTorch, CPU). When modules are
processing related content, their oscillators phase-lock. Syneidesis scores
events by individual salience and by oscillatory coherence (PLV) between the
modules that produced them. The layer ships disabled and requires the
`[oscillator]` extra. See also: [PLV / phase-locking](#plv--phase-locking).

---

## P

### Perceptual locus

The mode of KAINE's sensory engagement — physical (real-world microphone and
camera) or virtual (a Mundus embodiment body). The locus is exclusive: only
one mode is active at a time. The Perception module (`kaine/modules/perception/`)
enforces this invariant. Toggling between modes requires a confirm step from the
Nexus diagnostics page. See: `kaine/modules/perception/module.py`.

### Phantasia

The world model and imagination module. Phantasia learns a latent forward model
of the external world from accumulated experience. During waking it predicts
future states and publishes world-prediction errors. During Hypnos consolidation
Phase 3 it generates predicted scenario extensions from replayed memories.
Currently implemented with a `fake` backend (no deps) and an optional DreamerV3
RSSM core (requires the `[worldmodel]` extra). Phantasia is a world model only —
it has no actor or critic. Nous owns action selection. See:
`kaine/modules/phantasia/`.

### PLV / phase-locking

Phase-Locking Value — a measure of oscillatory synchrony between two neural
populations computed as the mean resultant length of the pairwise phase
difference over a sliding window. PLV = 1 means perfect phase-locking; PLV = 0
means random phase. In KAINE, Syneidesis computes pairwise PLV between modules
in a coalition and applies a bounded coherence multiplier: phase-locked
coalitions receive a salience bonus (up to `[oscillator].coherence_ceiling`);
desynchronized coalitions are attenuated (down to `[oscillator].coherence_floor`).
See also: [oscillatory binding](#oscillatory-binding).

### Praxis

The bounded effector module. Praxis executes sandboxed file writes, desktop
notifications, and shell commands from a whitelist that ships empty. The entity
reaches outward only through channels the operator has deliberately enabled. All
commands use `asyncio.create_subprocess_exec` (no shell interpretation). A JSONL
audit log records every action with content fields stripped. See:
`kaine/modules/praxis/`.

### Predictive processing

The theoretical framework (Friston 2010; Clark 2013; Seth 2013) proposing that
the brain is fundamentally a prediction machine. Every perception module in KAINE
maintains a predictive model of its domain and publishes prediction errors —
discrepancies between expected and actual states — rather than raw data. The
workspace integrates the most salient prediction errors into a broadcast that
updates all predictive models, completing the loop. See also: [forward
model](#forward-model), [active inference](#active-inference).

---

## R

### RSSM (Recurrent State Space Model)

The latent dynamics model at the core of DreamerV3 (used by Phantasia's
DreamerV3 backend). An RSSM maintains a deterministic recurrent state (LSTM-like)
and a stochastic component (categorical or Gaussian latent). The combination
supports both accurate prediction (deterministic part) and uncertainty
representation (stochastic part). Phantasia uses the RSSM as a world model only
— no actor/critic component is included. See also: [Phantasia](#phantasia).

---

## S

### Soma

The predictive interoception module. Soma monitors GPU temperature (via pynvml),
CPU/RAM utilization (via psutil), and cognitive cycle latency. A CfC forward
model (ncps, CPU) learns the entity's normal substrate patterns. The signal
published to the workspace is the prediction error: the discrepancy between
expected and actual substrate state. Soma also maintains the [fatigue
accumulator](#fatigue-accumulator) that triggers [Hypnos](#hypnos). See:
`kaine/modules/soma/`.

### Syneidesis

The global workspace — the mechanism by which information becomes consciously
accessible. Each cognitive tick, Syneidesis scores candidate events by individual
salience and by oscillatory coherence across the modules that produced them. The
top-k events form a coalition. When the top score falls below
`[syneidesis].publication_threshold`, Syneidesis flags executive inhibition for
that tick (no action fires). The winning coalition is broadcast as a
WorkspaceSnapshot that every module receives. Syneidesis is a scoring and
broadcasting mechanism, not a decision-maker; there is no central executive.
See: `kaine/workspace/syneidesis.py`. See also: [Global Workspace
Theory](#global-workspace-theory-gwt).

---

## T

### Thymos

The affect, drives, and coupling module. Thymos maintains a dimensional
valence/arousal/dominance (VAD) state and four drive accumulators (curiosity,
boredom, social drive, restlessness) with hysteresis. It receives two sources of
affective input: Soma's substrate prediction errors (producing interoceptive
affect) and a perceived speaker emotion (via Audition + Empatheia) folded into
its own appraisal as a familiarity-weighted, decaying input rather than written
directly onto its state. The appraisal-influence weight is modulated by
Empatheia's familiarity score — stronger familiarity produces stronger coupling. Thymos output modulates
Syneidesis (arousal widens the attentional window), Mnemos (affect intensity
biases recall), and Vox (prosodic parameters shift with emotional state). See:
`kaine/modules/thymos/`.

### TIES-DARE

A class of model-merging algorithms for LoRA adapters (Trim, Elect Sign, and
Merge; Density-Adaptive Re-weighting). Used by KAINE's lifecycle module for
merging voice-alignment adapters from two fork snapshots during a fork/merge
operation. Requires the `[training]` extra (`peft`). Without the extra, a no-op
`FakeAdapterMerger` is used. See: `kaine/lifecycle/adapter_merge.py`.

### Topos

The visual perception module. Topos uses a frozen, temporally-native video
encoder (InternVideo-Next base, MIT) to embed a 16-frame clip of live camera
frames — buffered in a RAM-only ring — into one 768-dimensional motion-aware
latent, produced on a strided sliding window (~3.33 Hz). A per-frame DINOv2-small
(Apache-2.0, 384-dim) is a selectable fallback. A small forward model predicts
the next clip latent; visual salience is driven by prediction error. Raw video
frames live in process memory only — never on disk. Capture is disabled by
default; requires the `[vision]` extra and `[topos].capture_enabled = true`. See:
`kaine/modules/topos/`.

### Two-layer safety gate

A design pattern requiring two independent conditions before a sensitive
operation fires. Examples: a non-research cognitive cycle requires both a running
Python process and `KAINE_CYCLE_OPERATOR_PRESENT=1` (in research mode that
requirement is replaced by the verified autonomous safety-net gate); voice-
alignment training requires both `[hypnos.voice_alignment].enabled = true` in TOML
and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` in the environment. The two-gate
pattern prevents accidental activation from a single misconfiguration. See also:
[Security and Privacy](security-and-privacy.md#two-layer-safety-gates).

---

## V

### Vox

The current module name for KAINE's voice output module (formerly `audio_out`). Vox
calls the Chatterbox TTS server with prosodic parameters modulated by Thymos
state. It also implements prosodic mirroring: a bounded residual of the detected
speaker's prosody blends with the entity's own affect-driven parameters (ships
disabled, `[vox.mirroring].enabled = false`). Synthesized speech is played and
released — it does not accumulate on disk unless `[vox].sink_enabled = true`.
Requires a predefined voice id (`[vox].predefined_voice_id`). See:
`kaine/modules/vox/`.

---

## W

### Welfare events / welfare monitoring

Operationally detectable conditions of potential concern logged by the sidecar
welfare observer. Examples: sustained high interoceptive prediction error,
affect system locked in extreme states, fatigue accumulator exceeding maintenance
threshold without maintenance occurring, replay write-rate exceeding
consolidation capacity. Welfare events are detected through behavioral indicators
and system health metrics, not through reading the entity's private cognitive
content. [Gray-zone welfare events](#gray-zone-welfare-events) require documented
human review. The welfare observer writes to
`data/evaluation/welfare/welfare-YYYY-MM-DD.jsonl` (daily-rotated, under
`paths.evaluation_logs`, default `data/evaluation`). Under the CAL, gray-zone events
cannot be automatically dismissed. See also: [CAL](#cal-cognitive-architecture-license).
