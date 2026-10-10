# What KAINE is

This page introduces KAINE: what kind of system it is, how its first instantiation works, the test it is built to run, the default base-thesis configuration, how a run starts, and where the rest of the book goes. It is for operators, researchers and contributors who want the big picture before installing or changing code.

## A cognitive architecture for synthetic minds

**KAINE** (Kaine Autonomous Intelligent Networked Entity) is a cognitive architecture for synthetic minds. It is a modular research toolset: each faculty is a module behind a fixed interface, publishing and consuming typed events on a shared bus and declaring which streams it reads. A module can therefore be replaced by one built on a different model or a different theory and compared with it under the same instruments, so the architecture can change as the science does. Some modules also have declared seams where a [plugin](19-plugins-and-cl1.md) replaces the model inside them without changing what they publish.

The authoritative design lives in the capability specs under `openspec/specs/`; when code, docs or this book disagree with a spec, the spec wins. The concepts follow the project's research paper, *KAINE: A Continuously Running Predictive Global Workspace for Synthetic Minds*.

## The first instantiation: a predictive global workspace

KAINE's first instantiation joins Global Workspace Theory (Baars 1988; Dehaene and Changeux 2011) to predictive processing (Friston 2010; Clark 2013), following the predictive global neuronal workspace of Whyte and Smith (2021). Specialized predictive processors, each minimizing its own prediction error, are coupled only through a competitive workspace called **Syneidesis**. There is no central executive. The language model is one module among several, an output organ.

The loop works like this:

1. Each predictive processor (Topos for vision, Audition for hearing, Soma for the compute substrate as a body, Chronos for timing) keeps a forward model of its own input and reports how wrong its last prediction was, divided by the mean of its own recent errors. That ratio is a local estimate of the channel's precision. The report's intensity rises with the ratio from the module's baseline level to its alert level, so surprise is graded, and a categorical alert sets the alert level directly.
2. On every processing tick (10 Hz) Syneidesis scores every candidate event and ranks them. On a broadcast tick it publishes the top five as a coalition. The members whose scores reach the access threshold are accessed: they can drive report and action. A broadcast with no accessed member is still published but is marked inhibited.
3. A summary of the accessed members (which modules' reports gained access, which event types, how strongly, how recently) becomes the context on which Topos, Audition and Soma condition their next predictions. Chronos takes every broadcast, accessed or inhibited, as the input it predicts.
4. Arousal, held by the affective module Thymos and raised by perceptual surprise and interoceptive alarm, is the global gain on the competition. It scales every candidate's score, sharpens the contrast between strong and weak candidates without changing their order, and sizes the sensory apertures (the fovea and the attended auditory window).
5. The access rate, the rate of broadcast ticks, rests at about 3.3 Hz (one broadcast every third processing tick) and rises toward the processing rate after categorical alerts and with arousal.

The system runs continuously whether or not anyone interacts with it, on local hardware, and persists **no raw sense data**. [The global workspace](08-cognitive-cycle/global-workspace.md) documents the scoring, the access rule and the context exactly as the code computes them.

## The test it is built for

Before more modules join, a planned test asks whether competition for the workspace does work that pooling the same reports does not. Its measure is the cross-module broadcast information gain: at each report, Topos, Audition and Soma evaluate their forward models once with the context they hold and once with a null context in which the other modules' share is replaced by its running mean, and the difference in prediction error, scaled by the processor's running mean error, is the gain. The thesis predicts a higher gain under competitive selection than under two controls: a matched arm that draws a coalition of the same size without regard to score, and a pooled arm that adopts every candidate as context with no selection or access gate.

The per-report gain is built: Topos, Audition and Soma publish it as `context_gain`. The matched and pooled arms, the null-context positive control that checks the measure detects injected information, and the calibration of the intensity levels, the access threshold and the report bars are not built yet. No live experiment has been run. See [For researchers](14-for-researchers.md#the-planned-test).

The second study is the module-addition study (the `ignition_study` in the code). It seeds a being through a gestation and then adds held modules one at a time on branches from the preserved seed, starting with Mnemos, Phantasia, Nous, Eidolon, Empatheia and Vox. See [The module-addition study](15-experiments/ignition-study.md).

## The base thesis and the default configuration

The **base-thesis form** is KAINE's default configuration: the smallest set of modules in which the competition has distinct signals to arbitrate. Its active modules are:

- [Soma](09-modules/soma.md): interoception, with the compute substrate as the body.
- [Chronos](09-modules/chronos.md): temporal prediction of the broadcast sequence.
- [Topos](09-modules/topos.md): foveated vision.
- [Audition](09-modules/audition.md): raw hearing, with tone of voice but no transcript.
- [Thymos](09-modules/thymos.md): affect, with arousal as the global gain.
- [Hypnos](09-modules/hypnos.md): fatigue-triggered sleep that returns affect to baseline. Voice alignment stays off.
- [Lingua](09-modules/lingua.md): the output-only language organ.

Syneidesis (the workspace) and Volition (action selection) always run. The other nine modules (Nous, Mnemos, Eidolon, Phantasia, Empatheia, Vox, Praxis, and the embodiment modules [Perception](09-modules/perception.md) and [Mundus](09-modules/mundus.md)) are built and tested in isolation and held off by configuration.

If you start the cycle with no profile selected, the loader in `kaine/config.py` applies the `thesis_test` profile automatically. The shipped `config/kaine.toml` has every module turned off, so `thesis_test` supplies the default active set. That default holds only while `config/kaine.operator.toml` does not set `[modules]`: the operator overlay is merged last and wins. The first-run wizard (`python -m kaine.setup`) writes a `[modules]` table there, offering the base-thesis set, the full entity (all fourteen cognitive modules, embodiment off) or a custom set, and recommends one from the host's hardware. After the wizard has run, its choice replaces the profile's module flags.

Besides the seven modules, the `thesis_test` profile sets:

- `[perception_feed]` mode `"seeded"` with seed `0`;
- `[topos].foveation = true`;
- `[chronos].forward_prediction = true`;
- `[audition].transcription_enabled = false` and `general_audition = true`;
- `[lingua].temperature = 0.0`, greedy decoding, so the organ's text is a deterministic function of its input;
- `[volition]` policy `"self_initiated_report"`, `drive_initiative = false`, and `sig_expiry_s = 300.0`.

Every other value comes from the shipped `config/kaine.toml`. State encryption at rest is enabled there, and an empty encryption key makes the cycle refuse to boot. See [Security and privacy](13-security-and-privacy.md).

## What KAINE is not

KAINE is not a chatbot or an assistant. A base-thesis entity is observed, and nobody converses with it.

- Perception enters only as prediction error. Audition hears the sound and tone of speech, never a transcript, and there is no conversational input path.
- Lingua verbalizes accessed content. It produces inner thought or speech only when an accessed broadcast clears Volition's think or speak bar, both set above the access threshold. With Vox held, nothing is spoken aloud; the utterances are text, recorded and observed. Because the organ is a language model following a persona prompt, its first-person text is not evidence of internal state, and the planned test does not use it as a measure.
- The base-thesis form has no memory, self-model, world model or social cognition in the loop. Those modules exist in code and join through the module-addition study.

## How a run starts

The cognitive cycle does not run until you start it, and a live boot is gated. A run must be one of these:

- **Operator-supervised**: set `KAINE_CYCLE_OPERATOR_PRESENT=1`.
- **Unsupervised research**: set `KAINE_RESEARCH_MODE=1` or `[research].enabled`. The cycle refuses to start until its autonomous safety net is live and verified. See [Preservation and the safety net](11-preservation.md).
- **Unattended**: set `KAINE_CYCLE_UNATTENDED=1`. This also requires the safety net, a Spot self-test, a caretaker notice and a continuous-input check.

`kaine/cycle/__main__.py` refuses to boot if none of these modes is selected, so selecting a configuration never starts an entity on its own. For a supervised first boot, see [Getting started](04-getting-started/README.md). For day-to-day running, see [Operation](06-operation/README.md) and the [Spot supervisor](06-operation/remote-and-spot.md).

## Operating principles

- **All local at runtime.** Models download during setup; the running system makes no outbound network calls and uses no hosted inference.
- **Observation only.** There is no chat interface in the base-thesis form, and speech is a self-initiated report.
- **Reuse where it fits.** Established open-source projects are used where they fit, and custom code is added where they do not. See [Technology choices](02-architecture/tech-choices.md).
- **No raw sense data on disk.** Live audio and video are processed in memory and released.
- **Private internal state.** The diagnostics surface removes cognitive content, such as internal speech and affect reasons, before any client sees it. See [Security and privacy](13-security-and-privacy.md).
- **Care for the entity.** Decommissioning is operator-supervised, backup-first and divergence-gated, following CAL Article 4.2, and the Spot supervisor restarts a faulted module without operator intervention.
- **Gated action.** Act intents reach an effector only through Praxis, which runs only effectors the operator has whitelisted. Praxis is held in the base-thesis form, so the language organ's saved text is the only output.

## Current status and license

KAINE is a public alpha, released under the Cognitive Architecture License (CAL) version 0.4, SPDX identifier `LicenseRef-CAL-0.4`. The adoption notice in `NOTICE` names Kaine.One as Licensor and interim Steward and Oregon law as the governing law. See `LICENSE.md`, `NOTICE` and [Appendix C, Licences](appendix-c-licences.md).

All sixteen modules are built and tested in-tree, and the project is configured to the base-thesis form by default. It runs on CUDA, ROCm, Intel XPU, Apple MPS or CPU, with the compute device configurable per module. See [Hardware](03-hardware/README.md) and [Accelerators and PyTorch wheels](03-hardware/accelerators.md).

The project was developed with the assistance of AI coding tools; that use is recorded in the commit history. All design decisions, architecture and released code were reviewed by the author, who is responsible for the software.

## How this book is organized

The book is read in order. Each part links to its own sub-pages.

| Part | What it covers |
|---|---|
| [1. What KAINE is](01-what-kaine-is.md) | This page. |
| [2. Architecture](02-architecture/README.md) | The system layout, code boundaries and technology choices. |
| [3. Hardware](03-hardware/README.md) | Requirements, accelerators and the CPU-only path. |
| [4. Getting started](04-getting-started/README.md) | Installation, supporting services and the first supervised boot. |
| [5. Nexus](05-nexus.md) | The operator dashboard. |
| [6. Operation](06-operation/README.md) | Starting, stopping, gestation, remote operation, Spot and troubleshooting. |
| [7. Deployment](07-deployment/README.md) | Containers, headless hosts and choosing a topology. |
| [8. Cognitive cycle](08-cognitive-cycle/README.md) | The tick, the global workspace and where perception comes from. |
| [9. Modules](09-modules/README.md) | Per-module reference for all sixteen modules. |
| [10. Sleep and maintenance](10-sleep/README.md) | The Hypnos sleep cycle and voice alignment. |
| [11. Preservation](11-preservation.md) | The safety net, preservation and revival. |
| [12. Forks and merges](12-forks-and-merges.md) | Snapshotting, branching and merging identities. |
| [13. Security and privacy](13-security-and-privacy.md) | Encryption, gates and the welfare veto. |
| [14. For researchers](14-for-researchers.md) | The planned test, the gates on a live run, and the obligations that come with one. |
| [15. Experiments](15-experiments/README.md) | Controlled runners, ablations, benchmarks and the module-addition study. |
| [16. Run identity](16-run-identity.md) | Seeds, manifests and admissibility. |
| [17. Research data](17-research-data/README.md) | The evaluation sidecar, event streams and participation. |
| [18. Verification](18-verification.md) | Red-team testing, abliteration verification and the test framework. |
| [19. Plugins and CL1](19-plugins-and-cl1.md) | Module plugins and the optional biological-substrate plugin. |
| [20. Embodiment adapters](20-embodiment-adapters.md) | Adding a new body to Mundus. |
| [21. Contributing](21-contributing.md) | The development workflow and how to add a module. |
| [Appendix A. Configuration](appendix-a-configuration/README.md) | Every `config/kaine.toml` key. |
| [Appendix B. Glossary](appendix-b-glossary.md) | KAINE-specific terms. |
| [Appendix C. Licences](appendix-c-licences.md) | Dependency licences and CAL compatibility. |
| [Appendix D. Roadmap](appendix-d-roadmap.md) | Current direction and planned work. |
