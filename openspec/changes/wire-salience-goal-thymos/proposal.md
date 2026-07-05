# Wire the goal and Thymos factors into live workspace salience

## Why

The paper (§3.2, §3.4.3) defines the precision-weighted salience that drives
workspace selection as a product of four factors: `intensity × novelty × goal ×
thymos`. The *running* cognitive cycle does not compute that product. It wires
two constant-returning placeholders:

- `kaine/cycle/__main__.py:647-650` constructs `RuleBasedSalience` with
  `goal_scorer=StaticGoalScorer()` and `thymos_modulator=StaticThymosModulator()`.
- Both placeholders (`kaine/workspace/strategies.py:29-58`) `return 1.0` for every
  event; their docstrings say "used until Phase 4 lands."
- `RuleBasedSalience` itself emits a runtime warning that it is running in a
  "degraded" two-factor mode (`kaine/workspace/salience.py:45-60`).

So operative salience collapses to `intensity × novelty`. The affective and
goal-directed weighting that the architecture claims shapes conscious access is
absent from every live run and therefore from every research verdict about what
the entity attends to.

The gap is not "unbuilt" — a **real** arousal-weighted Thymos modulator,
`StateModulator` (`kaine/modules/thymos/modulator.py:19`), already exists and is
instantiated on the Thymos module (`kaine/modules/thymos/module.py:106`).
Syneidesis simply never connects to it, and there is no config knob to swap the
real modulator in. No real goal scorer exists at all.

This is the single largest paper-versus-code gap in the operative loop. Per the
project's governing principle (bring the code up to the paper's full design, not
the reverse), the fix is to compute the real four-factor salience, not to weaken
the paper's claim.

## What Changes

**Plan-only. Ships no behavior code.** This change is the design-of-record and a
task roadmap for a later, approved implementation pass.

1. Connect the existing `StateModulator` (arousal-weighted Thymos factor) into the
   live `RuleBasedSalience` strategy in place of `StaticThymosModulator`, sourcing
   the current affect state from the same Thymos state the module already holds,
   without adding a cross-module import that violates the architecture boundaries.
2. Define and build a real **goal scorer** grounded in the paper's appraisal
   framing (an event's relevance to the entity's current drives/preferred states),
   replacing `StaticGoalScorer`. Where the paper leaves the goal signal
   under-specified, record the engineering choice honestly in `design.md` and in a
   source-site comment, as the codebase does elsewhere.
3. Add `[syneidesis]` config to select factor sources (real vs. static), defaulting
   to the **real** four-factor product, with the static placeholders retained only
   as an explicitly dev-only fallback (mirroring the DreamerV3/EMA and CfC patterns).
4. Remove or downgrade the "degraded two-factor mode" runtime warning once the real
   factors are the default; keep a warning only when an operator deliberately
   selects the static fallback.
5. Preserve determinism and the read-only/observer invariants: the salience change
   must be a pure function of the event and the current affect/goal state, with no
   new bus writes and no injection into the loop.

## Impact

- Affected specs: `syneidesis` (salience computation requirement), `thymos-affect-coupling`.
- Affected code (later pass): `kaine/workspace/strategies.py`,
  `kaine/workspace/salience.py`, `kaine/cycle/__main__.py`,
  `kaine/modules/thymos/modulator.py` (reuse), a new goal-scorer module, `config/kaine.toml`.
- Research impact: every subsequent live run computes the salience the paper
  describes, so A/B-divergence, workspace-trajectory, and attribution streams
  reflect affect- and goal-weighted access rather than a two-factor approximation.
- No change to the bus schema, determinism guarantees, or privacy boundary.
