## Why

Four "no pretend process" findings from the 2026-06-09 pretend-process audit
(`docs/audits/2026-06-09-pretend-process-audit.md`) require honest signalling
fixes across the reasoning, imagination, and salience subsystems.

**H1 — Nous hides inference crashes as a forced no_op.**
A non-timeout exception in `PymdpEngine.step()` returned a well-formed
`EngineResult` with `timed_out=False` and `action="no_op"` — indistinguishable
from a genuine reasoned no_op. Downstream, Nous published `nous.belief` and
`nous.policy` from stale priors as if freshly computed this cycle.

**H7 — Phantasia's backend is undisclosed on the bus.**
`phantasia.world_error` and `phantasia.scenario` were published with no indication
of whether they came from the real DreamerV3 RSSM or the `FakeWorldModel` EMA
stub. Consumers could not tell whether the signal was grounded in learned dynamics.

**M5 — Two of four salience factors are inert in the live cycle.**
`StaticGoalScorer` and `StaticThymosModulator` return a constant `1.0` and are
wired into the live `RuleBasedSalience` product
(`intensity * novelty * goal * thymos`), so live salience is effectively only
`intensity * novelty`. This is architecturally correct but was entirely invisible
without source inspection.

**L1 — Chronos has a permanently-zero reserved feature slot.**
`SnapshotFeaturizer.featurize()` vec[23] is always 0.0 and is fed silently into
the CfC and forward-prediction models. Introducing a real feature here later
requires a model-weight reset, but no comment documented that cost.

## What Changes

- **H1:** `EngineResult` SHALL carry `error: bool` and `error_reason: str` fields.
  `PymdpEngine.step()` SHALL set `error=True` (and log at `ERROR` level) on any
  non-timeout exception. `Nous.on_workspace()` SHALL publish `nous.error` and
  skip publishing `nous.belief` / `nous.policy` when `result.error` is set.
  The timeout path is unaffected.

- **H7:** Every `phantasia.world_error` and `phantasia.scenario` payload SHALL
  include `"backend": <backend_name>` so downstream consumers and operators can
  see whether signals come from the real RSSM or the EMA stub.
  The `[phantasia]` config SHALL include a plain-language comment distinguishing
  the two backends.

- **M5:** `RuleBasedSalience.__init__()` SHALL emit a one-time `log.warning`
  when the injected `goal_scorer` is a `StaticGoalScorer` and/or the
  `thymos_modulator` is a `StaticThymosModulator`, naming which factors are
  bypassed. Scoring math is unchanged.

- **L1:** `featurizer.py` vec[23] SHALL carry an explicit comment documenting
  the permanent-zero invariant and the retrain cost of changing it.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `nous-active-inference`: `EngineResult` gains `error`/`error_reason` fields;
  Nous publishes `nous.error` on inference crash and skips fabricated
  belief/policy.
- `phantasia`: every `phantasia.*` event payload includes `backend`.
- `syneidesis` / `action-selection`: live salience degradation (two factors
  inert) is now visible in operator logs.

## Impact

- **Code (edit):** `kaine/modules/nous/engine.py` (EngineResult + PymdpEngine +
  FakeEngine), `kaine/modules/nous/module.py` (on_workspace + _publish_error),
  `kaine/modules/phantasia/module.py` (_publish_world_error + generate_scenario),
  `config/kaine.toml` ([phantasia] comment), `kaine/workspace/salience.py`
  (RuleBasedSalience.__init__), `kaine/modules/chronos/featurizer.py` (comment).
- **Tests:** `tests/test_nous_engine.py`, `tests/test_nous_module.py`,
  `tests/test_phantasia_module.py`, `tests/test_workspace_salience.py`,
  `tests/test_chronos_featurizer.py`.
- **Safety:** all changes are log/diagnostic additions or skipping publication of
  stale data; no module-enable flag changes; no scoring math changes.
