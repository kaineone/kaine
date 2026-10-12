# About this book

This is the documentation for KAINE, a cognitive architecture for synthetic minds: a modular framework whose modules can be replaced, and whose first instantiation is a predictive global workspace. The documentation is written as one book. Read it in order to learn the system from the ideas behind it to how to extend it, or jump to the chapter you need. The reference appendices at the end list every configuration key, define the terms, and record licences and the roadmap.

The chapters are plain Markdown and read fine on GitHub. To read them as a book with a sidebar, search and next/previous pages, install [mdBook](https://rust-lang.github.io/mdBook/) and run `mdbook serve docs` from the repository root; the built book is written to `book/` and is not committed.

## Contents

**Understanding KAINE**

- [What KAINE is](01-what-kaine-is.md)
- [Architecture](02-architecture/README.md)
  - [Code boundaries](02-architecture/boundaries.md)
  - [Technology choices](02-architecture/tech-choices.md)

**Installing and running**

- [Hardware](03-hardware/README.md)
  - [Accelerators and PyTorch wheels](03-hardware/accelerators.md)
- [Getting started](04-getting-started/README.md)
  - [Supporting services](04-getting-started/services.md)
  - [First boot](04-getting-started/first-boot.md)
- [Dashboard, the dashboard](05-dashboard.md)
- [Day-to-day operation](06-operation/README.md)
  - [Development on one host](06-operation/development.md)
  - [Remote operation and the Supervisor supervisor](06-operation/remote-and-supervisor.md)
  - [Troubleshooting](06-operation/troubleshooting.md)
- [Choosing a deployment](07-deployment/README.md)
  - [Containers](07-deployment/containers.md)
  - [A dedicated headless host](07-deployment/headless-host.md)

**The mind**

- [The cognitive cycle](08-cognitive-cycle/README.md)
  - [The global workspace](08-cognitive-cycle/global-workspace.md)
  - [Where perception comes from](08-cognitive-cycle/perceptual-locus.md)
- [The modules](09-modules/README.md)
  - [Audition](09-modules/audition.md)
  - [Sequence](09-modules/sequence.md)
  - [Recorder](09-modules/recorder.md)
  - [Self-model](09-modules/self-model.md)
  - [Social cognition](09-modules/social-cognition.md)
  - [Sleep](09-modules/sleep.md)
  - [Language](09-modules/language.md)
  - [Episodic memory](09-modules/episodic-memory.md)
  - [Embodiment](09-modules/embodiment.md)
  - [Planning](09-modules/planning.md)
  - [Perceptual locus](09-modules/perceptual-locus.md)
  - [World model](09-modules/world-model.md)
  - [Effectors](09-modules/effectors.md)
  - [Interoception](09-modules/interoception.md)
  - [Affect](09-modules/affect.md)
  - [Vision](09-modules/vision.md)
  - [Vocal](09-modules/vocal.md)
- [Sleep and maintenance](10-sleep/README.md)
  - [Voice alignment](10-sleep/voice-alignment.md)

**Lifecycle, welfare and security**

- [Preservation and the safety net](11-preservation.md)
- [Forks and merges](12-forks-and-merges.md)
- [Security and privacy](13-security-and-privacy.md)

**Research**

- [For researchers](14-for-researchers.md)
- [Running experiments](15-experiments/README.md)
  - [The module-addition study](15-experiments/ignition-study.md)
- [Run identity and admissibility](16-run-identity.md)
- [The evaluation sidecar](17-research-data/README.md)
  - [Research event streams](17-research-data/event-streams.md)
  - [Research participation](17-research-data/participation.md)
- [Verification](18-verification.md)

**Extending KAINE**

- [Plugins and CL1](19-plugins-and-cl1.md)
- [Embodiment adapters](20-embodiment-adapters.md)
- [Contributing](21-contributing.md)

**Reference**

- [Configuration reference](appendix-a-configuration/README.md)
  - [Core, cycle and host](appendix-a-configuration/core.md)
  - [Modules](appendix-a-configuration/modules.md)
  - [Perception feed and sleep](appendix-a-configuration/perception-and-sleep.md)
  - [Lifecycle, evaluation and research](appendix-a-configuration/lifecycle-and-research.md)
  - [Security and Dashboard](appendix-a-configuration/security-and-dashboard.md)
- [Glossary](appendix-b-glossary.md)
- [Licences](appendix-c-licences.md)
- [Roadmap](appendix-d-roadmap.md)

Dated records (audits, history and shakedown reports) are kept as written in [records](records/README.md).
