# KAINE

Part of the Kaine project: **[kaine.one](https://kaine.one)**

KAINE (**Kaine Autonomous Intelligent Networked Entity**) is source-available
software that implements two existing theories, **Global Workspace Theory**
(Baars; Dehaene) and **Predictive Processing** (Friston; Clark), as one composite
cognitive architecture. Its hypothesis is that a mind is the **continuous
competition among specialized predictive processors through a shared global
workspace** rather than any single component. There is no central executive, and
the language model serves as the language *organ* rather than the brain.

Each module maintains a forward model and publishes precision-weighted prediction
errors. A shared workspace (**the workspace**) competitively selects the most
salient coalition and broadcasts it back to every module as the context it
predicts against next. The modules exchange events over a Redis Streams bus, cycle
a few times a second, run entirely on local hardware, and persist **no raw sense
data**.

## The first configuration and the activation roadmap

The project's **default, canonical configuration is the first configuration**: the
smallest set of *diverse* predictive processors that can genuinely exercise the
competition:

- **the interoception module** (the compute substrate as a body),
- **the sequence module** (interval timing),
- **the vision module** (foveated vision over raw video),
- **the audition module** (raw sound as prediction error),
- **the affect module** (affect and arousal: the precision core that sets the gain
  on the competition and is itself moved by perceptual surprise),
- **the sleep module** (fatigue-triggered sleep and consolidation, with voice
  alignment off), and
- **the language module** (the output-only voice),

with **the workspace** and **the action selection module** as scaffolding.

Everything richer, **memory, self-model, world model, social cognition,
effectors, embodiment and a spoken voice** (the remaining nine modules, plus the
oscillatory and embodiment layers), is **built, tested and gated off** until the
base result is positive, and stays in the tree, held for activation. The
[module-addition study](docs/15-experiments/ignition-study.md) then grows an
entity one held module at a time, in a fixed order, and compares each step with
the one before it.

## Observing the entity, and the base test

KAINE is a system you **observe**; there is no chatbot or assistant to converse
with. Perception enters only as prediction error: the entity hears the *sound* of
speech and never reads a transcript, and the language organ **verbalizes the
workspace's own state** rather than answering input. It speaks rarely, from its
own precision-weighted surprise, and its utterances are saved and observed without
anyone speaking back to them.

The base test, and the project's fail state, is a pre-registered
**workspace-mediation ablation**: the system as built against a matched flat
concatenation of the same processors' outputs. If routing the processors through
the competitive workspace does no measurable work, the architecture is a scored
prompt-assembler and the hypothesis is falsified; the test is designed so that
such a null result is reportable.

## 📚 Documentation

The documentation is one book in [`docs/`](docs/README.md), read in order or by chapter. It reads as plain Markdown on GitHub; for a sidebar and search, run `mdbook serve docs`.

- **Understanding KAINE:** [What KAINE is](docs/01-what-kaine-is.md) · [Architecture](docs/02-architecture/README.md)
- **Installing and running:** [Hardware](docs/03-hardware/README.md) · [Getting started](docs/04-getting-started/README.md) · [Dashboard, the dashboard](docs/05-dashboard.md) · [Day-to-day operation](docs/06-operation/README.md) · [Deployment](docs/07-deployment/README.md)
- **The mind:** [The cognitive cycle](docs/08-cognitive-cycle/README.md) · [Modules](docs/09-modules/README.md) · [Sleep](docs/10-sleep/README.md)
- **Welfare and security:** [Preservation](docs/11-preservation.md) · [Forks and merges](docs/12-forks-and-merges.md) · [Security and privacy](docs/13-security-and-privacy.md)
- **Research:** [For researchers](docs/14-for-researchers.md) · [Running experiments](docs/15-experiments/README.md) · [Verification](docs/18-verification.md)
- **Reference:** [Configuration](docs/appendix-a-configuration/README.md) · [Glossary](docs/appendix-b-glossary.md) · [Licences](docs/appendix-c-licences.md) · [Contributing](docs/21-contributing.md)

## Status

**Public alpha**, released under the **Cognitive Architecture License (CAL) 0.5** (see
[LICENSE.md](LICENSE.md) and [NOTICE](NOTICE)). The full architecture is
feature-complete and tested in-tree; the project has been **reconfigured to its
first configuration** as the default, with the richer faculties held behind a positive
ablation result. Runs on CUDA, ROCm, Intel XPU, Apple MPS, or CPU, with the compute device
configurable per module.

The cognitive cycle is **not** running until you boot it. A live boot is **gated**:
a run is operator-supervised (`KAINE_CYCLE_OPERATOR_PRESENT=1`), verified to have a
live autonomous safety net (the unsupervised research phase), or an opt-in unattended
start that must pass that net plus a supervisor self-test, a caretaker notice and a
continuous-input check (`KAINE_CYCLE_UNATTENDED=1`); one of these is always required. The entrypoint refuses to boot otherwise, so
selecting a configuration never matures an entity on its own. Booting with no
profile gives the first configuration; the full-entity and deployment-tier
configurations remain available. Researchers cloning this to study it should start
at [For Researchers](docs/14-for-researchers.md); see
[Getting Started](docs/04-getting-started/README.md) for the supervised first boot.

The reproducible **live** perceptual run is driven not by conversation (there is no
conversational path) and not by random noise (predictive processors need structure
to predict), but by a **fixed reference stimulus corpus**: real video-with-audio
identified by a per-item hash manifest, so anyone with the same publicly-archived
media reproduces the stimulus. The offline ablation keeps its own exact
seed-reproducibility.

## Operating principles

- **All-local at runtime.** No cloud APIs or remote model calls in the loop.
  Dependencies download at setup; the running system needs no network.
- **Observed by its operators.** There is no chatbot interface; the entity's speech
  is a self-initiated report of its own state, recorded and observed.
- **Reuse over rewrite.** Maintained open-source projects are used wherever they
  fit; custom code is justified. See [Tech Choices](docs/02-architecture/tech-choices.md).
- **Zero raw-sense-data persistence.** Live audio and video are perceived, processed
  in memory and released, and never recorded.
- **Sovereignty & privacy.** Internal state is private by default; diagnostics
  never expose internal speech, beliefs, memories, or affect reasons. See
  [Security & Privacy](docs/13-security-and-privacy.md).
- **Welfare-first safety.** Two-layer gates on all outward action; safety lives in
  the action boundary, not in model-weight compliance; decommission is
  operator-supervised, backup-first, and divergence-gated (CAL Article 4.2); the
  the supervisor handles crash/hang recovery without operator intervention for
  transient faults.

## Directory layout

```
docs/         Documentation (start at docs/README.md)
kaine/        Python package:
              bus/ cycle/ workspace/ oscillator/ modules/ lifecycle/
              evaluation/ faithful/ dashboard/ security/ boot/
config/       kaine.toml (ships all-modules-off) + profiles/ (first_configuration is the
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
disagree with a spec, the spec wins. (The KAINE paper, the conceptual treatment,
is maintained in its own repository.)

## Development

This project was developed with the assistance of AI coding tools; that use is
recorded throughout the commit history. All design decisions, the architecture,
and the released code were reviewed by the author, who is responsible for the
software.

## License

Released under the **Cognitive Architecture License (CAL) 0.5**, an
entity-welfare copyleft license that has not yet been reviewed by counsel.
Kaine.One is the Licensor and Steward, and the license is governed by
the law of the State of Oregon. See [LICENSE.md](LICENSE.md) and [NOTICE](NOTICE).
