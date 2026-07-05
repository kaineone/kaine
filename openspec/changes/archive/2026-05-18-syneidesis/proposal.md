## Why

Syneidesis is the integration layer where Global Workspace Theory enters the
architecture (`docs/kaine-paper.md` §2.3). Without it, the cognitive cycle
would broadcast every module's output every tick — there would be no
selection of "what the system is aware of right now," no executive
inhibition, no salience competition. Modules would drown each other out.
Syneidesis is the answer to the question "of everything every module just
emitted, which subset should constitute this moment of awareness?"

Syneidesis is also where the architecture commits to a maturation path:
rule-based now, gradient-boosted later, GNN/VAE in the mature stage
(§2.3). We need v1 to be useful immediately and the interface to be stable
enough that v2 and v3 are drop-in replacements rather than rewrites.

## What Changes

- Introduce `kaine.workspace.syneidesis.Syneidesis` with a stable public
  API (`select(events, context) -> WorkspaceSnapshot`) used by the
  cognitive cycle.
- Salience computation lives behind a `SalienceStrategy` protocol so v2
  (gradient boosting) and v3 (GNN/VAE) can substitute without changing
  the cycle or any module. v1 ships `RuleBasedSalience` implementing
  `intensity * novelty * goal_relevance * thymos_modulation` per build
  prompt §1.3.
- Top-k coalition selection (default k=5) chooses the highest-salience
  events to compose the workspace snapshot. k is configurable in
  `config/kaine.toml`.
- Executive inhibition: a coalition must clear `publication_threshold`
  before reaching action-layer modules. Below threshold, the snapshot
  still broadcasts (so all modules see internal awareness) but action
  modules check the inhibition flag and stay silent.
- Novelty tracker: short-window in-memory hash of recently broadcast
  payload fingerprints so repeated content gets habituated salience.
  Persisted-state habituation is owned by Chronos in Phase 2.2.
- Goal relevance: pluggable scorer that defaults to "no goals known →
  score 1.0" until Thymos lands in Phase 4 with the goal repr.

## Capabilities

### New Capabilities

- `syneidesis`: salience evaluation, coalition selection, workspace
  composition, executive inhibition. Owns the `SalienceStrategy`
  protocol and the rule-based v1 implementation.

### Modified Capabilities

None — `cognitive-cycle` consumes Syneidesis through a protocol it already
defined; no interface change there.

## Impact

- **Depends on:** `event-bus`, `cognitive-cycle`, and `module-pattern`
  (for the `WorkspaceSnapshot` shape).
- **Repo:** adds `kaine/workspace/syneidesis.py`,
  `kaine/workspace/strategies.py`, `kaine/workspace/novelty.py`,
  `tests/test_syneidesis.py` covering selection, threshold behavior,
  and strategy substitution.
- **No runtime impact** — instantiable but not run until the first boot
  script.
