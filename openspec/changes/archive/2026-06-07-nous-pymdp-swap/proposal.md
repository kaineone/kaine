## Why

`KAINE_Paper_v4.md` §3.3.2 redefines **Nous** as the **active inference engine**:
belief updating, policy selection, and epistemic (information-seeking) action via
expected-free-energy minimization using **pymdp** (Heins et al. 2022). Today Nous
wraps OpenNARS-for-Applications (a NARS symbolic reasoner) as an external NAR
subprocess. The paper makes active inference "the reasoning framework native to
predictive processing," giving theoretical coherence across the architecture, and
relegates symbolic reasoning to a *future complementary module* (§3.3.2, §10).

The operator has chosen a **full replacement**: pymdp 1.0 (JAX) becomes Nous; the
NARS integration is retired (archived for the future symbolic module, not deleted).
The JAX backend is required for the pymdp 1.0 API; `jax[cpu]` is added to the
`[reasoning]` optional extra.

## What Changes

- Replace the NAR subprocess with **pymdp 1.0 (JAX)** inside
  `kaine/modules/nous/`:
  - `generative_model.py` — constructs the pymdp 1.0 generative model (A/B/C/D)
    over a compact discrete factor set derived from workspace content; B-matrix
    indexed over the explicit v1 action space
    `{no_op, request_think, request_speak, request_maintenance}`.
  - `engine.py` — `ActiveInferenceEngine`: maps workspace broadcast to
    observations, runs belief updating (`pymdp.inference.update_posterior_states`)
    + EFE policy selection (`pymdp.control.infer_policies`); exposes posterior,
    selected policy, and epistemic-action preference; hard timeout guard returns
    the last posterior on overrun and emits `nous.timeout`.
  - `module.py` — rewritten `Nous(BaseModule)` driving the engine each broadcast.
- **EFE loop budget guards:** (a) pre-build benchmark script asserts median EFE
  ≤ 200 ms on the target CPU; (b) hard timeout guard in `engine.py`; (c) config
  complexity envelope (factors × states × actions × horizon) validated at startup.
- **Bus contract:** preserve `nous.belief` (semantics redefined: statement =
  latent-factor label, confidence = posterior certainty, frequency = posterior
  expectation) so existing consumers (Mnemos, Eidolon, Syneidesis) keep working.
  Add `nous.policy` (selected policy + EFE) and `nous.timeout` (overrun
  diagnostic). Epistemic actions emitted as `intent.act` through Volition/intent.
- **Health probe:** replace the Nexus NAR binary probe with a pymdp+jax import
  probe; remove all `binary_path` plumbing.
- **NousMergeStrategy rewrite:** drop NARS fields (`restart_count`,
  `pending_revision`); implement one-sided selection (lower-entropy wins) with a
  `nous.merge_warning` flag.
- **FaithfulRenderer templates:** add `nous.belief` and `nous.policy` templates to
  `kaine/faithful/templates.py`.
- Retire NARS: move `process.py`, `narsese.py`, `translator.py` and the
  `external/OpenNARS-for-Applications` build to an archived location; drop the NAR
  binary from setup. Keep them recoverable for the future symbolic module.
- `[nous]` config replaced: pymdp 1.0 model params (factor sizes, planning
  horizon, efe_timeout_ms, complexity envelope) instead of
  `binary_path`/`inference_steps_per_tick`.
- Archive `executive-action-intent` (already merged at `348e80d`).

## Capabilities

### New Capabilities

- `nous-active-inference`: pymdp 1.0 (JAX) belief updating, policy selection, and
  epistemic action; supersedes the NARS-based `nous` capability.

### Modified Capabilities

None expressed as deltas here (the NARS `nous` capability is superseded; the
`nous.belief` event contract is preserved so consumers are unaffected).

## Impact

- **Depends on:** `cognitive-cycle`/`syneidesis` (consumes broadcasts),
  `event-bus`, `module-pattern`, `executive-action-intent` (epistemic actions ride
  the intent path). **New deps:** `inferactively-pymdp>=1.0` (import name
  `pymdp`), `jax[cpu]`. **Removed dep:** ONA
  binary + `scripts/build-ona.sh` from the runtime path.
- **Consumers preserved:** Mnemos/Eidolon/Syneidesis still read `nous.belief`.
- **Risk:** highest-risk swap; pymdp 1.0 JAX API is the target — not the older
  NumPy A/B/C/D prototype; validate API against the installed version before
  build. Mitigated by a compact initial generative model, a `FakeEngine` for
  tests, the EFE benchmark, and NARS archived for fallback.
- Ships disabled-by-default; `external/OpenNARS-for-Applications` no longer
  required for a green build.
