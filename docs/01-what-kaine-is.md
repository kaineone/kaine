# What KAINE is

This page introduces KAINE: the claim it is built to test, the default base-thesis form, what the system is and is not, how a run starts, and where the rest of the book goes. It is for operators, researchers, and contributors who want the big picture before installing or changing code.

## The claim KAINE tests

**KAINE** stands for the **Kaine Autonomous Intelligent Networked Entity**. It is a composite cognitive architecture built to test the claim that a mind is the **continuous competition among specialized predictive processors through a shared global workspace**, not any single component. There is no central executive. The language model is one organ among several — the language organ, not the brain.

KAINE combines two ideas:

- **Global Workspace Theory** (Baars; Dehaene): conscious content arises when specialized processes compete to broadcast their signals.
- **Predictive Processing** (Friston; Clark): each process maintains a forward model and publishes the precision-weighted error between what it expected and what it sensed.

In the system, every module publishes prediction errors to a Redis-Streams event bus. A shared workspace called **Syneidesis** selects the most salient coalition of signals and broadcasts it back to every module, so each module predicts against the same current context on the next cycle. The modules run entirely on local hardware, cycle a few times a second, and persist **no raw sense data**.

The main experiment is the **workspace-mediation ablation**: the full architecture is compared to a flat concatenation of the same module outputs. If routing the modules through the competitive workspace does no measurable work, the architecture is just a scored prompt-assembler and the thesis is falsified. The experiment is pre-registered, and a null result is reportable.

For the full technical layout, see [Architecture](02-architecture/README.md). The authoritative design lives in the capability specs under `openspec/specs/`; when code, docs, or this book disagree with a spec, the spec wins.

## The base thesis and the default configuration

The **base-thesis form** is KAINE's canonical default configuration: the smallest set of diverse predictive processors that can genuinely test the workspace competition. In this form the active modules are:

- **[Soma](09-modules/soma.md)** — interoception and the compute substrate as a body.
- **[Chronos](09-modules/chronos.md)** — interval timing.
- **[Topos](09-modules/topos.md)** — foveated vision over raw video.
- **[Audition](09-modules/audition.md)** — raw sound as prediction error.
- **[Thymos](09-modules/thymos.md)** — affect and arousal, setting the gain on the competition.
- **[Lingua](09-modules/lingua.md)** — the output-only voice.

**Syneidesis** (the workspace) and **Volition** (action selection) run as always-on scaffolding. The remaining ten module slots, including the embodiment layer **[Perception](09-modules/perception.md)** and **[Mundus](09-modules/mundus.md)**, are built and tested but disabled until a positive base-thesis result. The Mundus control surface is built, but nothing drives its per-tick loop yet; only the `stub` adapter ships, and a virtual-world adapter is planned.

If you start the cycle with no profile selected, the loader in `kaine/config.py` applies the base-thesis `thesis_test` profile automatically. The shipped `config/kaine.toml` has every module turned off, so `thesis_test` supplies the default active set. That default holds only while `config/kaine.operator.toml` does not set `[modules]`: the operator overlay is merged last and wins, and the first-run wizard (`python -m kaine.setup`) always writes a full `[modules]` table there. After the wizard has run, its choices replace the profile's module flags. The wizard's own defaults are Soma, Chronos, Thymos, Eidolon, Mnemos, and Lingua on, with Topos and Audition off.

The `thesis_test` profile enables only:

- the six modules listed above;
- `[perception_feed]` mode `"seeded"` with seed `0`;
- `[topos].foveation = true`;
- `[audition].transcription_enabled = false` and `general_audition = true`;
- `[volition]` policy `"self_initiated_report"`, `drive_initiative = false`, and `sig_expiry_s = 300.0`.

Every other value — organ model, Whisper model, encryption, rates, backends, and so on — comes from the shipped `config/kaine.toml`.

State encryption at rest is **enabled** in the shipped `config/kaine.toml`; an empty encryption key causes the cycle to refuse boot. See [Security and privacy](13-security-and-privacy.md) for the full model.

## What KAINE is not

KAINE is **not a chatbot** and not an assistant you converse with. It is a system you **observe**.

- Perception enters only as prediction error. Audition hears sound, not a transcript. There is no conversational input path.
- Lingua verbalizes the workspace's own state. It speaks rarely and only when its internal surprise rises above threshold. Its utterances are recorded and observed, not spoken back into the microphone.
- The base-thesis form has no memory, self-model, world-model, social cognition, or sleep in the loop. Those modules exist in code but are held off by configuration until the workspace ablation shows they are justified.

## How a run starts

The cognitive cycle is not running until you start it. A live boot is **gated**: a run must be one of the following, never none:

- **Operator-supervised** — set `KAINE_CYCLE_OPERATOR_PRESENT=1`.
- **Unsupervised research** — set `KAINE_RESEARCH_MODE=1` or `[research].enabled`; the system verifies it has a live autonomous safety net before it starts. See [Preservation and the safety net](11-preservation.md).
- **Opt-in unattended** — set `KAINE_CYCLE_UNATTENDED=1`; this also passes the safety net, a Spot self-test, a caretaker notice, and a continuous-input check.

`kaine/cycle/__main__.py` refuses to boot if none of these modes is selected, so selecting a configuration never births an entity on its own. The base-thesis form is what you get with no profile. Full-entity and deployment-tier configurations remain available.

For a supervised first boot, see [Getting started](04-getting-started/README.md). For day-to-day running, see [Operation](06-operation/README.md) and the [Spot supervisor](06-operation/remote-and-spot.md).

## Operating principles

- **All-local at runtime.** No cloud APIs or remote model calls are used in the loop. Dependencies download during setup; the running system needs no network.
- **Observed, not conversed with.** No chat interface. Speech is a self-initiated report of the workspace state.
- **Reuse over rewrite.** Established open-source projects are used where they fit; custom code is added only when justified. See [Technology choices](02-architecture/tech-choices.md).
- **Zero raw-sense-data persistence.** Live audio and video are processed in memory and released, not stored.
- **Sovereignty and privacy.** Internal state is private by default. Diagnostics do not expose internal speech, beliefs, memories, or affect reasons. See [Security and privacy](13-security-and-privacy.md).
- **Welfare-first safety.** Outward action passes a two-layer gate. The safety model lives in the action boundary, not in the weights of the language model. Decommission is operator-supervised, backup-first, and divergence-gated under CAL Article 4.2. The Spot supervisor recovers from transient crashes or hangs without operator intervention.

## Current status and license

KAINE is a **public alpha**, released under the **Cognitive Architecture License (CAL)** — see `LICENSE.md` and [Appendix C — Licences](appendix-c-licences.md). The full architecture is feature-complete and tested in-tree. The project is configured to the base-thesis form by default; the richer faculties remain gated behind a positive ablation result.

It runs on CUDA, ROCm, Intel XPU, Apple MPS, or CPU, with the compute device configurable per module. See [Hardware](03-hardware/README.md) and [Accelerators and PyTorch wheels](03-hardware/accelerators.md) for details.

The project was developed with the assistance of AI coding tools; that use is recorded in the commit history. All design decisions, architecture, and released code were reviewed by the author, who is responsible for the software.

## How this book is organized

This book is read in order. Each part links to its own sub-pages.

| Part | What it covers |
|---|---|
| [1. What KAINE is](01-what-kaine-is.md) | This page. |
| [2. Architecture](02-architecture/README.md) | The system layout, code boundaries, and technology choices. |
| [3. Hardware](03-hardware/README.md) | Requirements, accelerators, and the CPU-only path. |
| [4. Getting started](04-getting-started/README.md) | Installation, supporting services, and the first supervised boot. |
| [5. Nexus](05-nexus.md) | The operator dashboard. |
| [6. Operation](06-operation/README.md) | Starting, stopping, gestation, remote operation, Spot, and troubleshooting. |
| [7. Deployment](07-deployment/README.md) | Containers, headless hosts, and choosing a topology. |
| [8. Cognitive cycle](08-cognitive-cycle/README.md) | The tick, the global workspace, and where perception comes from. |
| [9. Modules](09-modules/README.md) | Per-module reference for all sixteen modules. |
| [10. Sleep and maintenance](10-sleep/README.md) | The Hypnos sleep cycle and voice alignment. |
| [11. Preservation](11-preservation.md) | The safety net, preservation, and revival. |
| [12. Forks and merges](12-forks-and-merges.md) | Snapshotting, branching, and merging identities. |
| [13. Security and privacy](13-security-and-privacy.md) | Encryption, gates, and the welfare veto. |
| [14. For researchers](14-for-researchers.md) | The ethics-first landing page for study. |
| [15. Experiments](15-experiments/README.md) | Controlled runners, ablations, benchmarks, and the ignition study. |
| [16. Run identity](16-run-identity.md) | Seeds, manifests, and admissibility. |
| [17. Research data](17-research-data/README.md) | The evaluation sidecar, event streams, and participation. |
| [18. Verification](18-verification.md) | Red-team testing, abliteration verification, and the test framework. |
| [19. Plugins and CL1](19-plugins-and-cl1.md) | Module plugins and the optional biological-substrate plugin. |
| [20. Embodiment adapters](20-embodiment-adapters.md) | Adding a new body to Mundus. |
| [21. Contributing](21-contributing.md) | The development workflow and how to add a module. |
| [Appendix A. Configuration](appendix-a-configuration/README.md) | Every `config/kaine.toml` key. |
| [Appendix B. Glossary](appendix-b-glossary.md) | KAINE-specific terms. |
| [Appendix C. Licences](appendix-c-licences.md) | Dependency licences and CAL compatibility. |
| [Appendix D. Roadmap](appendix-d-roadmap.md) | Current direction and planned work. |
