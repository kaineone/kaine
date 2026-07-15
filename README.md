# KAINE

Part of the Kaine project — **[kaine.one](https://kaine.one)**

**Kaine Autonomous Intelligent Networked Entity** — a composite cognitive
architecture built to test one claim: that a mind is the **continuous competition
among specialized predictive processors through a shared global workspace**, and
not any single component. There is no central executive, and the language model is
the language *organ*, not the brain.

KAINE joins **Global Workspace Theory** (Baars; Dehaene) with **Predictive
Processing** (Friston; Clark): each module maintains a forward model and publishes
precision-weighted prediction errors; a shared workspace (**Syneidesis**)
competitively selects the most salient coalition and broadcasts it back to every
module as the context it predicts against next. The modules exchange events over a
Redis-Streams bus, cycle a few times a second, run entirely on local hardware, and
persist **no raw sense data**.

## The base thesis, and how the default configuration tests it

The project's **default, canonical configuration is the base-thesis test** — the
smallest set of *diverse* predictive processors that can genuinely exercise the
competition:

- **Soma** (interoception — the compute substrate as a body),
- **Chronos** (interval timing),
- **Topos** (foveated vision over raw video),
- **Audition** (raw sound as prediction error), and
- **Lingua** (the output-only voice),

with **Syneidesis** (the workspace) and **Volition** (action selection) as
scaffolding. This is **not a chatbot** and not an assistant you converse with: it
is a system you **observe**. Perception enters only as prediction error — the
entity hears the *sound* of speech, it never reads a transcript — and the language
organ **verbalizes the workspace's own state** rather than answering input. It
speaks rarely, from its own precision-weighted surprise, and its utterances are
saved and observed, not spoken back to.

The primary experiment is a **workspace-mediation ablation**: the system as built
versus a matched flat concatenation of the same processors' outputs. If routing
the processors through the competitive workspace does no measurable work, the
architecture is a scored prompt-assembler and the thesis is falsified. That test is
pre-registered and designed so a null result is reportable.

Everything richer — **memory, self-model, affect, world-model, social cognition,
sleep/consolidation, effectors, embodiment, and a spoken voice** (the remaining
eleven modules plus the oscillatory and embodiment layers) — is **built, tested,
and gated off** until a positive base result. It is held, never removed.

## 📚 Documentation

The full documentation lives in **[`docs/`](docs/README.md)** — start there.

- **[For Researchers](docs/for-researchers.md)** — start here if you cloned this to study it: the offline test path and the observed live run, ethics-first
- **[Reproducing Results](docs/reproducing-results.md)** — the offline mechanism-validation path: the workspace-mediation ablation + the suite (no entity boot)
- **[Hardware](docs/hardware.md)** — requirements, GPU/VRAM, CPU-only fallback, service footprint
- **[Architecture](docs/architecture.md)** — the whole system at a glance
- **[Getting Started](docs/getting-started.md)** — install + supervised first boot of the base-thesis form
- **[Operations](docs/operations.md)** — running it, the Nexus dashboard, troubleshooting
- **[Configuration](docs/configuration.md)** — every `config/kaine.toml` key
- **[Modules](docs/README.md#modules)** — per-organ reference
- **[Tech Choices](docs/tech-choices.md)** · **[Security & Privacy](docs/security-and-privacy.md)** · **[Glossary](docs/glossary.md)** · **[Contributing](docs/contributing.md)**

## Status

**Public alpha**, released under the **Cognitive Architecture License (CAL)** — see
[LICENSE.md](LICENSE.md) and [NOTICE](NOTICE). The full architecture is
feature-complete and tested in-tree; the project has been **reconfigured to its
base-thesis form** as the default, with the richer faculties held behind a positive
ablation result. Runs on CUDA, ROCm, Intel XPU, Apple MPS, or CPU — compute device
configurable per module.

The cognitive cycle is **not** running until you boot it. A live boot is **gated**:
a run is **either** operator-supervised (`KAINE_CYCLE_OPERATOR_PRESENT=1`) **or**,
in the unsupervised research phase, verified to have a live autonomous safety net
before it starts — never neither. The entrypoint refuses to boot otherwise, so
selecting a configuration never births an entity on its own. Booting with no
profile gives the base-thesis form; the full-entity and deployment-tier
configurations remain available. Researchers cloning this to study it should start
at [For Researchers](docs/for-researchers.md); see
[Getting Started](docs/getting-started.md) for the supervised first boot.

The reproducible **live** perceptual run is driven not by conversation (there is no
conversational path) and not by random noise (predictive processors need structure
to predict), but by a **fixed reference stimulus corpus**: real video-with-audio
identified by a per-item hash manifest, so anyone with the same publicly-archived
media reproduces the stimulus. The offline ablation keeps its own exact
seed-reproducibility.

## Operating principles

- **All-local at runtime.** No cloud APIs or remote model calls in the loop.
  Dependencies download at setup; the running system needs no network.
- **Observed, not conversed with.** No chatbot interface; the entity's speech is a
  self-initiated report of its own state, recorded and observed.
- **Reuse over rewrite.** Maintained open-source projects are used wherever they
  fit; custom code is justified. See [Tech Choices](docs/tech-choices.md).
- **Zero raw-sense-data persistence.** Live audio/video is perception, not
  recording — processed in memory and released.
- **Sovereignty & privacy.** Internal state is private by default; diagnostics
  never expose internal speech, beliefs, memories, or affect reasons. See
  [Security & Privacy](docs/security-and-privacy.md).
- **Welfare-first safety.** Two-layer gates on all outward action; safety lives in
  the action boundary, not in model-weight compliance; decommission is
  operator-supervised, backup-first, and divergence-gated (CAL Article 4.2); the
  Spot supervisor handles crash/hang recovery without operator intervention for
  transient faults.

## Directory layout

```
docs/         Documentation (start at docs/README.md)
kaine/        Python package:
              bus/ cycle/ workspace/ oscillator/ modules/ lifecycle/
              evaluation/ faithful/ nexus/ security/ + boot.py
config/       kaine.toml (ships all-modules-off) + profiles/ (thesis_test is the
              default) and secrets schema
compose/      Container definitions for the supporting services
scripts/      Operator utilities (first boot, bootstraps, backups)
tools/        Operator tooling (e.g. reference-corpus manifest builder)
tests/        Unit and systems/ integration tests
openspec/     Specifications of record (specs/) + change history (changes/)
```

## Specification of record

The authoritative design lives in the per-capability specs under
**[`openspec/specs/`](openspec/specs)**. When documentation, code, or this README
disagree with a spec, the spec wins. (The KAINE paper — the conceptual treatment —
is maintained in its own repository.)

## Development

This project was developed with the assistance of AI coding tools; that use is
recorded throughout the commit history. All design decisions, the architecture,
and the released code were reviewed by the author, who is responsible for the
software.

## License

Released under the **Cognitive Architecture License (CAL)** — a custom
entity-welfare copyleft, pending legal review. See [LICENSE.md](LICENSE.md).
