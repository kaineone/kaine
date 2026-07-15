# KAINE Documentation

KAINE is a composite cognitive architecture built on **Predictive Processing**
and **Global Workspace Theory**: sixteen modules — fourteen predictive cognitive
modules plus a two-module embodiment layer (**Perception** and **Mundus**) that
ships inactive — communicate over a Redis-Streams event bus, compete for
attention in a shared workspace
(**Syneidesis**), and act through a two-layer safety gate — running ~3.3 times a
second, entirely on local hardware, persisting no raw sense data.

**The project's default, canonical configuration is the base-thesis form**: the
smallest set of *diverse* predictive processors that can genuinely exercise the
competition — **Soma**, **Chronos**, **Topos**, **Audition**, and **Lingua** —
with Syneidesis and Volition as always-on scaffolding. This is not a chatbot;
the system is **observed, not conversed with**. Perception enters only as
prediction error (no transcript path), and Lingua is an output-only,
self-initiated voice. The remaining eleven modules and the embodiment layer are
built, tested, and **gated off** until a positive result from the primary
experiment, the **workspace-mediation ablation** — see
[Architecture](architecture.md) for the full picture.

This is the entry point to the full documentation. Everything here is reference
material for operators and contributors; nothing in these pages starts or enables
the entity (all modules ship disabled). A run is **either** operator-supervised
**or**, in the unsupervised research phase, verified to have a live autonomous
safety net before it starts — never neither.

> **New here?** Read [Architecture](architecture.md) for the big picture, then
> [Getting Started](getting-started.md) to install and bring up a supervised
> first boot.

## Start here

| Doc | What it covers |
|---|---|
| [For Researchers](for-researchers.md) | The ethics-first landing page for anyone cloning KAINE to study it: the two paths (offline reproduction vs live entity), the welfare gate, and where to go next |
| [Reproducing Results](reproducing-results.md) | Path A — the safe offline run: the test suite, the controlled experiment runners, and the benchmarks, none of which boots an entity |
| [Hardware](hardware.md) | Requirements per path, GPU/VRAM guidance for the 4B organ, the CPU-only fallback, dynamic device selection, and the supporting-service footprint |
| [Architecture](architecture.md) | The whole system: PP + GWT, the cognitive cycle, the bus, Syneidesis, the safety model, the JAX stack, the module roster |
| [Getting Started](getting-started.md) | Prerequisites, install, optional extras, supporting services, supervised first boot |
| [Operations](operations.md) | Running it day-2: the Nexus dashboard, [Spot supervisor](operations.md#module-supervisor-spot), [entity decommission](operations.md#entity-decommission), [research participation](operations.md#research-participation), enabling modules, monitoring predictive signals, troubleshooting |
| [Configuration Reference](configuration.md) | Every `config/kaine.toml` section and key, defaults, and the dependency extras |
| [Tech Choices](tech-choices.md) | Every major dependency/decision and why (pymdp, DreamerV3, snnTorch, Qdrant, abliterated Qwen, …) and the licensing stance |
| [Security & Privacy](security-and-privacy.md) | Zero-raw-persistence, encryption at rest, the safety gates, the abliteration welfare veto |
| [Glossary](glossary.md) | Definitions of KAINE-specific terms and the cognitive-science concepts behind them |
| [Contributing](contributing.md) | OpenSpec rigor, the dev/test workflow, conventions, and how to add a module |
| [Licenses](licenses.md) | Dependency license manifest and CAL compatibility |
| [Research Participation](research-participation.md) | Opt-in numeric-metrics-only research submission: privacy guarantees, bundle contents, and send procedure |

## Modules

Sixteen modules — fourteen predictive cognitive modules plus the two-module
embodiment layer, **Perception** and **Mundus**, which ships inactive. Each doc
covers responsibility, inputs/outputs (exact event types and streams),
configuration, mechanisms, key files, how to enable, and zero-persistence notes.

**Base-thesis active** (enabled by the `thesis_test` profile, `config/profiles/thesis_test.toml`):
[Soma](modules/soma.md) ·
[Chronos](modules/chronos.md) ·
[Topos](modules/topos.md) ·
[Audition](modules/audition.md) ·
[Lingua](modules/lingua.md)

Everything else below is **gated** — built and tested, shipped disabled, held
behind a positive base-thesis result (Perception and Mundus ship inactive
regardless, as the always-off embodiment layer).

**Perception & substrate**
[Soma](modules/soma.md) ·
[Chronos](modules/chronos.md) ·
[Topos](modules/topos.md) ·
[Audition](modules/audition.md) ·
[Perception (locus)](modules/perception.md)

**Cognitive core**
[Nous](modules/nous.md) ·
[Mnemos](modules/mnemos.md) ·
[Eidolon](modules/eidolon.md) ·
[Phantasia](modules/phantasia.md) ·
[Empatheia](modules/empatheia.md)

**Affect, expression & regulation**
[Thymos](modules/thymos.md) ·
[Lingua](modules/lingua.md) ·
[Vox](modules/vox.md) ·
[Praxis](modules/praxis.md) ·
[Hypnos](modules/hypnos.md)

**Embodiment & test**
[Mundus](modules/mundus.md) ·
[Echo](modules/echo.md)

## Guides

Developer how-tos for extending KAINE:

- [Building embodiment adapters for Mundus](guides/embodiment-adapters.md) — give a
  KAINE entity a new body (a physical robot, a VR/game avatar, a simulator, a custom
  effector) by implementing the `EmbodimentAdapter` contract; the core never changes.

## Processes

How the modules combine into system-level behavior:

- [Cognitive Cycle](processes/cognitive-cycle.md) — the ~3.3 Hz tick, rates, regulation, freeze
- [Global Workspace](processes/global-workspace.md) — salience, coalition selection, PLV coherence, volition/intents
- [Fork / Merge Lifecycle](processes/fork-merge-lifecycle.md) — snapshots, adapter merge, one-sided Nous selection
- [Sleep & Maintenance](processes/sleep-maintenance.md) — the five-phase fatigue-triggered Hypnos cycle
- [Perception Locus](processes/perception-locus.md) — physical XOR virtual gating of camera/mic
- [Voice Alignment](processes/voice-alignment.md) — QLoRA sleep training with the capability-loss + abliteration vetoes

**Research operation & testing**

- [Research Operation](processes/research-operation.md) — an unsupervised research run end to end: mode selection, the safety-net boot gate, the seven experiments, admissibility, the autonomous safety net
- [Testing Framework](processes/testing-framework.md) — the three validation layers (instrument controls, experiment determinism/isolation, data integrity) and how they map to the seven experiments
- [Run Identity](processes/run-identity.md) — per-run seed, run id, manifest, deterministic mode, shared verdict schema
- [Run Admissibility](processes/run-admissibility.md) — completeness gating + log range validation
- [Evaluation Sidecar](processes/evaluation-sidecar.md) — the read-only observers, the content-free welfare emitter, and instruments
- [Controlled Experiment Runners](processes/controlled-experiment-runners.md) — A/B divergence, memory coherence, self-model accuracy as seeded offline runners
- [Oscillatory Ablation](processes/oscillatory-ablation.md) — coherence layer on vs off, controlled
- [Active-Inference Benchmark](processes/active-inference-benchmark.md) — Nous AIF vs an RL baseline
- [Multi-Seed Stability](processes/longitudinal-stability.md) — the live/longitudinal nondeterministic control
- [Enforcement Red-Team](enforcement-red-team.md) — the abliterated-organ action-gate protocol

**Welfare & preservation**

- [Entity Preservation & Revival](processes/entity-preservation.md) — what is preserved, divergence-triggered live preservation, the encrypted bundle, the verified revive path

## Background & design

- KAINE Paper — the architecture's conceptual basis and rationale (maintained in its own repository)
- [Vision Document](kaine-vision-document.md) — project intent
- [Architecture Roadmap](history/architecture-roadmap.md) — the (completed) build plan (historical)

## Conventions used in these docs

- Modules ship **disabled** (`[modules].<name> = false`); enabling one is a
  **local** `config/kaine.toml` edit and is never committed.
- Event types and stream names in these docs match the code exactly; a module's
  output stream is `<module>.out`.
- Diagrams are GitHub-rendered Mermaid; links are relative.
- Specifications of record live under [`openspec/specs/`](../openspec/specs); when
  a doc and a spec disagree, the spec wins.
