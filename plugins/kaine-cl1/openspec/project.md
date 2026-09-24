# Project context: kaine-CL1

**What this is.** A strictly-downstream research overlay that runs selected KAINE
cognitive-architecture modules on **Cortical Labs CL1** biological neural compute,
via the **free CL API simulator**. It never edits pure KAINE.

**Upstreams.**
- KAINE (`kaineone/kaine`): 16-module predictive-processing / global-workspace
  architecture. Each module maintains a forward model and publishes
  precision-weighted prediction errors over a Redis-Streams bus; the cognitive
  cycle runs ~3.3 Hz. Heavy modules already select a runtime backend behind their
  client seam (`kaine/modules/backends.py:BackendRegistry`). Consumed as a
  **pinned git dependency**, never vendored.
- cl-sdk (`Cortical-Labs/cl-sdk`): the CL1 **simulator**. 64-channel MEA;
  `cl.open()` → `neurons.stim(ChannelSet, StimDesign)` /
  `neurons.loop(ticks_per_second=…)` → `LoopTick.analysis.spikes`; `cl.analysis`
  gives criticality / LZ-complexity / entropy / firing-stats / functional
  connectivity. Vendored read-only under `vendor/cl-sdk/`.

**Core idea.** Replace a module's silicon forward model with the biological
substrate *behind its existing client seam*: encode input → stim, record spikes →
decode as prediction / prediction-error, publish the **same event shape**.
KAINE's predictive-processing + free-energy thesis and Cortical Labs' DishBrain
free-energy paradigm are the same theory, so the mapping is principled.

**Hard invariants (see docs/downstream-isolation.md).**
- Never modify pure KAINE. Inject behind seams; if a seam is missing, upstream a
  *vendor-neutral* one (silicon default unchanged), never a CL1-specific edit.
- Never modify `vendor/cl-sdk/`.
- A converted module keeps its `name`, bus subscriptions, and `<name>.out` event
  shapes byte-for-byte.
- The goal is to run on **real CL1 tissue**, which is not available to this
  project yet. Until then we build and validate on the **simulator**
  (`cl.is_simulator()`); hardware runs are a deliberate, reviewed step, never
  an accidental default.
- 64 electrodes / one culture is a hard ceiling; converted modules share it via
  disjoint channel territories (the substrate broker).

**Conventions.**
- Python 3.12+. Package `kaine_cl1` under `src/`.
- OpenSpec `schema: spec-driven`. Changes carry `proposal.md`, `tasks.md`,
  optionally `design.md`, and delta specs under `specs/<capability>/spec.md`
  using `## ADDED Requirements` with at least one `#### Scenario:` each.
- Scope is tiered by fit: strong-tier full conversions first, hybrid-tier
  (silicon + wetware together, sometimes permanent; default off) next,
  ill-fitting modules stay silicon.
