# KAINE

Part of the Kaine project: **[kaine.one](https://kaine.one)**

KAINE (**Kaine Autonomous Intelligent Networked Entity**) is source-available
software, a cognitive architecture that implements computational readings of two
existing theories, Global Workspace Theory (Baars; Dehaene) and Predictive
Processing (Friston; Clark), so that design hypotheses drawn from them can be
tested in one system. It proposes no new theory of consciousness and tests none of
those theories' neural predictions. Its hypothesis is that a mind, if one can be
built, may be the **continuous competition among specialized predictive processors
through a shared global workspace** rather than any single component. There is no
central executive, and the language model is the language *organ* rather than the
brain.

Each predictive processor maintains a forward model and reports its prediction
error divided by its recent mean error, a proxy for precision weighting. The
shared global workspace competitively selects a coalition of reports and
broadcasts it to every module. A summary of which modules' reports gained access,
and how strongly, becomes the context the perceptual and interoceptive processors
predict against next; none of them reads what another reported. Arousal, raised by
surprise, is a global gain on access. The modules exchange events over a Redis
Streams bus, with a few direct control couplings, broadcast a few times a second,
run entirely on local hardware, and persist no raw sense data.

## The first configuration and the activation roadmap

The project's **default, canonical configuration is the first configuration**: the
smallest set of *diverse* predictive processors that can genuinely exercise the
competition:

- the interoception module (the compute substrate as a body),
- the sequence module (interval timing),
- the vision module (foveated vision over raw video),
- the audition module (raw sound as prediction error),
- the affect module (affect and arousal, the global gain on access, itself moved
  by perceptual surprise and interoceptive alarm),
- the sleep module (fatigue-triggered sleep and consolidation, with voice
  alignment off), and
- the language module (the voice, which hears no speech),

with the workspace and the action selection module as scaffolding.

The remaining nine modules, plus the oscillatory and embodiment layers, add
memory, a self-model, a world model, social cognition, effectors, embodiment and a
spoken voice. They are built and unit-tested, and each stays off until its turn in
the research order. The base result has to be positive first. The
[module-addition study](docs/15-experiments/ignition-study.md) then grows an
entity one held module at a time, in a fixed order, and compares each step with
the one before it, so a change in what the entity does can be traced to the
module that was added.

## Observing the entity, and the base test

KAINE is a system you observe; there is no chatbot or assistant to converse with.
Perception enters only as prediction error: the entity hears the *sound* of speech
and never reads a transcript. The language organ verbalizes accessed broadcasts
and answers no input. It speaks rarely, when an accessed report's score clears its
report bar, and its utterances are saved and observed without anyone speaking back
to them.

The base test is a planned **workspace-mediation ablation**. It compares
competitive selection with a score-blind coalition of the same size and with a
pool of every candidate, by how much the shared context improves each processor's
prediction. A gain at or below both controls is this form's fail state. The test
is designed so that a null result is reportable, and its rules are recorded before
any live run. No live experiment has been run.

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
[LICENSE.md](LICENSE.md) and [NOTICE](NOTICE)). All sixteen modules are
built and unit-tested in-tree. The **first configuration** is the default, and the
held modules wait for a positive ablation result. Runs on CUDA, ROCm, Intel XPU, Apple MPS, or CPU, with the compute device
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
- **Observation only.** There is no chatbot interface; the entity's speech is a
  self-initiated report of its own state, recorded and observed.
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
  supervisor, when enabled, handles crash and hang recovery without operator
  intervention for transient faults.

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

The reference implementation was written largely by AI coding agents (Anthropic
Claude models and open-weight models) under the author's direction and review;
Claude co-authorship is recorded in commit trailers. The architecture, the design
hypothesis and the experimental design are the author's, and the author is
responsible for the software.

## License

Released under the **Cognitive Architecture License (CAL) 0.5**, an
entity-welfare copyleft license that has not yet been reviewed by counsel.
Kaine.One is the Licensor and Steward, and the license is governed by
the law of the State of Oregon. See [LICENSE.md](LICENSE.md) and [NOTICE](NOTICE).
