# Proposal

## Why

The module-ignition study was designed as a controlled experiment: one seed, branching lines, a noise reference and an accumulate line, comparing workspace ignitions across module configurations. The CTO decided (2026-10-31) that the goal is a working synthetic mind, not a publishable experiment. The study converts into a single-entity development run: one entity boots, develops, held modules join in the existing order, and each new architecture component is added as built. The three-arm ablation, pilot boots and calibration chain no longer gate builds. This unblocks the first boot without discarding the study runner infrastructure already built and merged.

## What Changes

- **Protocol simplification.** The branch/repeat/accumulate line structure is replaced by a single progressive line: the entity gestates, matures, then gains modules one at a time in the existing order (base set → episodic memory → world model → planning → self-model → social cognition → vocal). After each module addition the entity watches the four-film programme.
- **No branching.** No seed revived multiple times. No noise reference. No familiarity-control accumulate line. The entity is one continuous individual that develops.
- **Module addition is a revive.** After each viewing the entity is preserved. The next step revives it with one more module enabled. This reuses the existing revive-with-extra-module infrastructure.
- **Recording unchanged.** Every viewing records workspace trajectory, ignition log, dashboard data (privacy-filtered), and language utterances. Inner speech is never recorded. Each step has its own working directory and bus database.
- **K=1 revisited.** The architecture program noted that continuous competition with K=1 (one winner per broadcast) is revisited at study conversion, not carried by default. The development run's runner accepts a `broadcast_capacity` parameter (default: current K from config).
- **Runner refactoring.** The existing `kaine-study` compose service, study runner, step loop, manifest, dry-run harness and disk guard are reused. The plan generator changes from the branch/repeat/accumulate grid to a linear sequence of progressive steps.
- **Analysis adapts.** Comparisons become step-over-step: each viewing is compared against the previous one (one more module) rather than across branches from a common seed. The analysis still produces ignition reports and feeds Claude Science (metrics-only, with operator consent).
- **Welfare indicator response required.** The safety net's response to the welfare indicators is built and second-reviewed before the first boot (architecture program decision). Already completed.
- **Paper alignment.** The paper's preregistered-test section becomes a descriptive account of the development run. A REVISION-NOTES entry records the change. The paper keeps "access summary; content is future work" until the content-workspace-level is operational.

## Capabilities

### New Capabilities
- `development-run-protocol`: the single-entity progressive development run — step ordering, module addition sequence, per-step isolation, recording, and analysis

### Modified Capabilities
- `module-ignition-study`: the study runner's plan generator, step loop and analysis change from branching to progressive; the branch/repeat/accumulate plan types are removed; the step manifest adds `modules_added` and `step_index`

## Impact

- `kaine/study/plan.py`: plan generator produces a linear sequence instead of a branch grid
- `kaine/study/runner.py`: step loop simplified; no line isolation beyond per-step directories; revive always adds exactly one module
- `kaine/study/analysis.py`: step-over-step comparison instead of branch-vs-branch
- `config/profiles/development-run.toml`: new profile with `broadcast_capacity` and progressive module order
- `compose/kaine.study.local.yml`: unchanged (compose service reused)
- Tests: dry run with progressive steps, step manifest validation, analysis on progressive data
