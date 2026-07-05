# KAINE

Part of the Kaine project — **[kaine.one](https://kaine.one)**

**Kaine Autonomous Intelligent Networked Entity** — a composite cognitive
architecture where the mind emerges from the continuous interaction of **sixteen
modules** — fourteen predictive cognitive modules plus a two-module embodiment
layer (**Perception** and **Mundus**) that ships inactive — through a global
workspace. There is no central executive.
The LLM is the language organ, not the brain. The mind is the loop.

KAINE runs on **Predictive Processing** and **Global Workspace Theory**: the
modules exchange events over a Redis-Streams bus, compete for attention in a
shared workspace (**Syneidesis**), and act only through a two-layer safety gate —
cycling ~3.3 times a second, entirely on local hardware, persisting **no raw
sense data**.

## 📚 Documentation

The full documentation lives in **[`docs/`](docs/README.md)** — start there.

- **[For Researchers](docs/for-researchers.md)** — start here if you cloned this to study it: the two paths (offline vs live), ethics-first
- **[Reproducing Results](docs/reproducing-results.md)** — the safe offline path: test suite + experiment/benchmark runners (no entity)
- **[Hardware](docs/hardware.md)** — requirements per path, GPU/VRAM, CPU-only fallback, service footprint
- **[Architecture](docs/architecture.md)** — the whole system at a glance
- **[Getting Started](docs/getting-started.md)** — install + supervised first boot
- **[Operations](docs/operations.md)** — running it, the Nexus dashboard, troubleshooting
- **[Configuration](docs/configuration.md)** — every `config/kaine.toml` key
- **[Modules](docs/README.md#modules)** — per-organ reference (16)
- **[Tech Choices](docs/tech-choices.md)** · **[Security & Privacy](docs/security-and-privacy.md)** · **[Glossary](docs/glossary.md)** · **[Contributing](docs/contributing.md)**

## Status

**First public alpha — 26.06.0a1** (pip-normalized: `26.6.0a1`). The
architecture is feature-complete and tested in-tree: fourteen cognitive modules
over a Redis-Streams bus and Syneidesis workspace, plus the two-module
embodiment layer (**Perception** and **Mundus**) that ships inactive,
predictive forward models
across the perceptual/substrate organs, the **Empatheia** (social) and
**Phantasia** (world-model) modules, **Nous** rebuilt as active inference on
pymdp/JAX, the **Hypnos** five-phase fatigue-triggered maintenance cycle, an
oscillatory binding layer, state encryption at rest, a **Spot** module supervisor
watchdog (crash/hang detection, restart ladder, operator-escalation), a
**welfare-gated decommission** CLI (CAL Article 4.2/4.3, backup-first,
divergence-branching), **opt-in research submission** (numeric metrics only,
operator-initiated), and a Nexus dashboard that surfaces it all. Runs on CUDA,
ROCm, Intel XPU, Apple MPS, or CPU — compute device configurable per-module.

This is a public alpha, released under the **Cognitive Architecture License
(CAL)** — see [LICENSE.md](LICENSE.md) and [NOTICE](NOTICE). The alpha number
increments as the release stabilizes.

The cognitive cycle is **not** running and module state is **not** initialized.
Every module ships **disabled**; enabling one is a local `config/kaine.toml` edit
that is never committed. A live boot is **gated**: a run is **either**
operator-supervised (`KAINE_CYCLE_OPERATOR_PRESENT=1`) **or**, in the unsupervised
research phase, verified to have a live autonomous safety net before it starts —
never neither. The cycle entrypoint refuses to boot otherwise. Researchers cloning
this to study it should start at [For Researchers](docs/for-researchers.md); see
[Getting Started](docs/getting-started.md) for the supervised first boot.

## Operating principles

- **All-local at runtime.** No cloud APIs or remote model calls in the loop.
  Dependencies download at setup; the running system needs no network, and can
  run fully offline.
- **Reuse over rewrite.** Maintained open-source projects are used wherever they
  fit; custom code is justified. See [Tech Choices](docs/tech-choices.md).
- **Zero raw-sense-data persistence.** Live audio/video is perception, not
  recording — it is processed in memory and released.
- **Sovereignty & privacy.** Internal state is private by default; diagnostics
  never expose conversational content, beliefs, memories, internal speech, or
  affect reasons. See [Security & Privacy](docs/security-and-privacy.md).
- **Welfare-first safety.** Two-layer gates on all outward action; the language
  organ's abliteration is protected from re-conditioning by a hard veto in the
  sleep cycle; decommission is operator-supervised, backup-first, and
  divergence-gated (CAL Article 4.2); the Spot supervisor handles crash/hang
  recovery without requiring operator intervention for transient faults.

## Directory layout

```
docs/         Documentation (start at docs/README.md)
kaine/        Python package:
              bus/ cycle/ workspace/ oscillator/ modules/ lifecycle/
              evaluation/ faithful/ nexus/ security/ + boot.py
config/       kaine.toml (ships all-modules-off) and secrets schema
compose/      Container definitions for the supporting services
scripts/      Operator utilities (first boot, bootstraps, backups)
tests/        Unit and systems/ integration tests
openspec/     Specifications of record (specs/) + change history (changes/)
```

## Specification of record

The authoritative design lives in the per-capability specs under
**[`openspec/specs/`](openspec/specs)**. When documentation, code, or this README
disagree with a spec, the spec wins. (The KAINE paper — the conceptual treatment —
is maintained in its own repository.)

## License

Released under the **Cognitive Architecture License (CAL)** — a custom
entity-welfare copyleft, pending legal review. See [LICENSE.md](LICENSE.md).
