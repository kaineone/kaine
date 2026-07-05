# Design — Nous as active inference (pymdp 1.0 JAX)

## What is being replaced

`NARProcess` (subprocess), `narsese.py` (Narsese gen/parse), `translator.py`
(events→Narsese), and the ONA binary. The clean seam is `NARProcessProtocol`; the
preserved seam is the `nous.belief` bus event consumed by Mnemos, Eidolon, and
Syneidesis.

## pymdp version

This change targets **pymdp 1.0** (the installed package is
`inferactively-pymdp` 1.0.2; the import name is `pymdp`). It ships a JAX/equinox
agent-centric API that differs from the older NumPy prototype. Verified against
the installed library:

- The idiomatic entry point is the **`pymdp.agent.Agent`** class. The
  generative model is passed as **lists of `jax.numpy` arrays over
  factors/modalities** (A=likelihood, B=transition, C=preferences, D=prior); the
  constructor casts them to JAX and adds a leading `batch_size` dimension.
- Belief updating is `Agent.infer_states(observations, empirical_prior=agent.D)`.
  Observations are batched integer arrays, one per modality
  (`[jnp.array([idx]), ...]`). It returns `qs`, a list (per factor) of posteriors
  shaped `(batch, T, states)`. (Internally this wraps
  `pymdp.inference.update_posterior_states`.)
- Policy selection is `q_pi, neg_efe = Agent.infer_policies(qs)`. `neg_efe` is
  the **negative** expected free energy per policy (higher is better); the
  selected policy is `argmax(neg_efe)` i.e. lowest EFE. (Internally this wraps
  `pymdp.control.update_posterior_policies_inductive`.)
- NOTE: the symbols `pymdp.control.infer_policies`,
  `pymdp.control.get_expected_states`, and `pymdp.control.get_expected_observations`
  named in earlier drafts **do not exist** in 1.0.2; the `Agent` methods above
  are the real API and were verified before implementation.
- Per-call Python dispatch of the Agent methods costs ~130 ms; the engine
  `jax.jit`-compiles `infer_states`+`infer_policies` into one traced function,
  dropping the warm step to <1 ms (CPU).
- The `[reasoning]` optional extra in `pyproject.toml` SHALL include both
  `inferactively-pymdp>=1.0` and `jax[cpu]` so the backend works without a CUDA
  install. (The bare `pymdp` PyPI name is an unrelated 0.0.1 stub — do not use it.)

## v1 action space

The generative model's B-matrix is indexed over a **fixed four-element action
space** defined in `kaine/modules/nous/generative_model.py`:

| Index | Name | Semantics |
|-------|------|-----------|
| 0 | `no_op` | No outward action this cycle |
| 1 | `request_think` | Epistemic: internal elaboration (think intent) |
| 2 | `request_speak` | Communicative: external speech (speak intent) |
| 3 | `request_maintenance` | Metacognitive: signal need for rest/consolidation |

`request_think` is an epistemic action — it keeps computation internal and does
not require a Praxis whitelist. The absence of a Praxis whitelist for speak/
maintenance is handled by Syneidesis inhibition in the intent path; Nous proposes,
the executive path disposes. This unblocks v1 EFE planning.

## Generative model

pymdp needs a discrete generative model: observations **O**, hidden states **S**,
the likelihood **A** = P(O|S), transition **B** = P(S'|S,action), preferences
**C** over observations, and prior **D**. KAINE's challenge is that the workspace
is open-ended. v1 keeps a **compact, fixed factor set** derived from workspace
content (e.g., salience-band of the dominant coalition, affect quadrant from
Thymos, a small set of recurring event-type clusters), with a documented seam to
grow factors online. We start small deliberately — the paper flags pymdp at scale
as unvalidated (§9).

The config key `[nous]` declares a **complexity envelope**:
`factors`, `max_states_per_factor`, `actions`, `horizon`. `make_nous` validates
this envelope at startup and raises `ConfigurationError` if the estimated worst-
case step count exceeds the threshold. This prevents silent performance
degradation from misconfiguration.

## EFE planning loop budget

The cognitive cycle runs at ~3.3 Hz (300 ms budget). EFE on a compact model is
fast, but the budget must be validated empirically on the target CPU:

1. **Pre-build benchmark** (`scripts/benchmark_nous_efe.py`): runs EFE 100 times
   with the configured envelope and asserts median ≤ 200 ms. CI calls this before
   the main test suite when the `nous` optional extra is installed.
2. **Hard timeout guard** in `engine.py`: a `threading.Timer` or
   `concurrent.futures.ThreadPoolExecutor` with `timeout=efe_timeout_ms/1000`
   wraps the EFE call. On overrun, the engine returns the last computed posterior
   and publishes `nous.timeout` (salience 0.3) to flag the overrun to the sidecar.
3. The config validator rejects envelopes whose complexity product exceeds the
   threshold; this is checked at import time via `make_nous`.

## Mapping the loop

Each broadcast: encode the snapshot → observation indices (via
`generative_model.encode_snapshot`); call `Agent.infer_states(obs,
empirical_prior=agent.D)` to update the posterior over hidden states; call
`Agent.infer_policies(qs)` (returns `q_pi, neg_efe`) to score policies by EFE;
read off the preferred action as `argmax(neg_efe)` (lowest EFE). The v1 model
has a single control factor whose four states ARE the action space, so the four
policies map one-to-one to `ACTION_SPACE`.

## Bus contract preservation

`nous.belief` is kept so downstream consumers do not break, but its fields are
reinterpreted:
- `statement` → the latent-state-factor label that moved most (human-readable).
- `frequency` → the posterior expectation (was NARS frequency).
- `confidence` → posterior certainty (1 − normalized entropy).
- `kind` → `"belief"` (NARS Derived/Revised/Answer kinds retire).

New events:
- `nous.policy` → `{policy, expected_free_energy, horizon}` for diagnostics + the
  sidecar.
- `nous.timeout` → emitted when EFE planning overruns `efe_timeout_ms`; carries
  the elapsed time and the complexity envelope for operator review.
- Epistemic action → emitted as `intent.act` through the existing Volition/intent
  path (`executive-action-intent`), **never** as a direct effector call — keeps
  the two-layer safety gates in charge of all outward action.

## Health probe

The old Nexus NAR health probe (`nar_health_probe`, `binary_path` check) is
replaced by a **pymdp import probe**: at startup Nexus calls
`nous_health_probe()`, which attempts `import pymdp` and `import jax`; if either
fails, the probe returns `unhealthy` with the import error message. No binary
path plumbing is required.

## NousMergeStrategy

`NousMergeStrategy` (used in the fork/merge subsystem) is rewritten:

- **Drop** the NARS-specific fields `restart_count` and `pending_revision` — these
  belonged to the NAR subprocess lifecycle and are meaningless for a JAX engine.
- **Replace** with one-sided selection: when two forked Nous states are merged, the
  strategy picks the state with lower normalised entropy (more certain posterior)
  and emits a `nous.merge_warning` event if the discarded state's posterior differs
  by more than a threshold. No field-level merging of NARS fields occurs.
- The updated `NousMergeStrategy` test replaces NARS field assertions with
  one-sided-selection assertions + warning-flag assertions.

## FaithfulRenderer templates

`kaine/faithful/templates.py` SHALL include templates for:
- `nous.belief` → renders as `"[Nous] {statement} (certainty {confidence:.0%})"`.
- `nous.policy` → renders as `"[Nous] policy={policy} EFE={expected_free_energy:.3f}"`.

## Why route action through intents

Active inference *selects* actions; KAINE's safety model requires every outward
action to pass Syneidesis inhibition + Praxis whitelists. So Nous proposes
(`intent.act`); the existing executive path disposes. Epistemic (`request_think`)
actions are the common case, stay internal/cheap, and do not require whitelisting.

## Retiring NARS, not deleting it

Move the NARS files + build under `external/archive/` (or a tagged commit
referenced in the change) so the future "complementary symbolic reasoning module"
(paper §10) can resurrect them. Remove the ONA binary from setup and CI so a green
build no longer depends on compiling ONA.

## Testing

`FakeEngine` implementing the engine protocol returns scripted posteriors/policies
so module-level tests need neither pymdp nor a subprocess. A pymdp-backed
integration test is opt-in (`KAINE_NOUS_RUN_REAL_PYMDP=1`), mirroring the prior
opt-in real-NAR test.

## Out of scope

The future symbolic-reasoning complementary module; learned (continuous) active
inference; growing the generative model automatically; GPU-accelerated JAX.
