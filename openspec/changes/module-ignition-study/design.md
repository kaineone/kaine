# Design — `module-ignition-study`

## Lines and isolation

- **Working directory.** Every state path in KAINE is relative to the process's working directory: the stage file, the Eidolon self-model, perception state, control files and runtime state. Each line therefore runs from its own directory (`studies/<study-id>/<line>/`), holding a `config/` that overlays the study profile and its own `state/`.
- **Memory.** The Qdrant collection names (`[mnemos].collection_prefix`, `[empatheia].collection`) and the bus database (`[bus].db`) are set per line. A Qdrant import upserts rather than replacing, so lines must never share collections.
- **Research log.** Each line's research event log goes to its own directory.

## Steps

- **Step 0: gestation.** A base-thesis entity with staging on and the local womb. It is born under `faculty-relative-birth` once its readiness holds.
- **Birth.** At birth the womb blooms and falls silent. The runner preserves the being and stops it: preservation P0.
- **Forking.** Both lines are revived from P0. Each line's step k revives the preservation from its own step k−1. The main line adds the k-th module in the order; the control line keeps the base five.
- **Each viewing.** Mode `playlist` with the four-film manifest. At the end of the programme, `film-end-preserve` freezes, preserves and stops. The runner records the step manifest: line, step, module set, preservation ids, run id and research-log path.
- **Order within a step.** The main and control steps run one after the other on one host (never together): main k, then control k.

## Ignition analysis

- **Inputs.** The research event log's workspace broadcasts, with the fields restored by `film-aligned-ignition-log`: entry ids, run id, broadcast time and film position.
- **Per viewing:**
  - broadcasts per minute;
  - coalition size;
  - share of broadcasts containing each module;
  - salience distribution;
  - broadcasts per film-minute (aligned by film position, so Hypnos's pauses do not smear time).
- **Per step:** the main-minus-control difference, and the change from step k−1 on each line.
- **Output.** Content-free: counts, rates and module shares only. No percept content leaves the logs.

## What this study cannot show

- **It is not a clean per-module experiment.** The main line accumulates modules in one order. An effect at step k is that module's effect *given* the modules before it and the being's history, not its isolated effect. The control line removes familiarity, not order.
- **Faculties without an input channel on this host are expected nulls:** Praxis, Perception and the Mundus stub. They are reported as such.
