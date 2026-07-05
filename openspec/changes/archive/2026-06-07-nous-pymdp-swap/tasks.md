## 1. Generative model (pymdp 1.0 JAX)

- [x] 1.1 `kaine/modules/nous/generative_model.py` — build A/B/C/D over a compact discrete factor set derived from workspace content using the pymdp 1.0 JAX API; B-matrix indexed over the v1 action space `{no_op, request_think, request_speak, request_maintenance}`; seam to grow factors online
- [x] 1.2 `encode_snapshot(snapshot) -> obs_indices` — maps a WorkspaceSnapshot to pymdp observation indices; handles missing factors gracefully
- [x] 1.3 Declare `ACTION_SPACE = ["no_op", "request_think", "request_speak", "request_maintenance"]` as the authoritative constant; document that `request_think` is epistemic (no Praxis whitelist required)

## 2. EFE benchmark and complexity envelope

- [x] 2.1 `scripts/benchmark_nous_efe.py` — runs EFE 100 times with the configured complexity envelope on the target CPU; asserts median ≤ 200 ms; exits non-zero on failure; CI calls this before the main test suite when the `reasoning` extra is installed
- [x] 2.2 Config validator in `make_nous`: compute `factors × max_states × actions × horizon`; raise `ConfigurationError` at startup if the product exceeds the complexity threshold

## 3. Engine (pymdp 1.0 JAX API)

- [x] 3.1 `kaine/modules/nous/engine.py` — `ActiveInferenceEngine` protocol + pymdp 1.0 impl: snapshot → observations via `encode_snapshot`; belief update via `pymdp.inference.update_posterior_states`; EFE policy selection via `pymdp.control.infer_policies`; expose posterior, policy, epistemic-action preference
- [x] 3.2 Hard timeout guard in `engine.py`: wrap EFE call with `efe_timeout_ms` (default 250); on overrun return last posterior and publish `nous.timeout` diagnostic event; cycle must not block
- [x] 3.3 `FakeEngine` implementing the protocol — returns scripted posteriors/policies; no pymdp or subprocess dependency

## 4. Module rewrite

- [x] 4.1 Rewrite `kaine/modules/nous/module.py` to drive the engine each broadcast using the pymdp 1.0 API
- [x] 4.2 Publish `nous.belief` (preserved shape; redefined semantics: statement=dominant latent-factor label, frequency=posterior expectation, confidence=1−normalised entropy)
- [x] 4.3 Publish `nous.policy` (policy name, expected_free_energy, horizon)
- [x] 4.4 Emit chosen epistemic actions as `intent.act` through the Volition/intent path (never direct effector calls); `request_think` maps to a think intent, `request_speak` maps to a speak intent

## 5. Health probe

- [x] 5.1 Replace the Nexus NAR health probe (`binary_path` check) with a pymdp import probe: `nous_health_probe()` attempts `import pymdp; import jax`; returns `unhealthy` with the import error message on failure; remove all `binary_path` plumbing from the config and the probe

## 6. Retire NARS + config migration

- [x] 6.1 Move `process.py`, `narsese.py`, `translator.py` + `external/OpenNARS-for-Applications` build to `external/archive/`; remove the NAR binary + `scripts/build-ona.sh` from setup/CI
- [x] 6.2 Replace `[nous]` config: add `factors`, `max_states_per_factor`, `actions = 4`, `planning_horizon`, `efe_timeout_ms`; remove `binary_path`/`inference_steps_per_tick`; update `make_nous` allowed keys
- [x] 6.3 Add `pymdp>=1.0` and `jax[cpu]` to the `[reasoning]` optional extra in `pyproject.toml`

## 7. NousMergeStrategy rewrite

- [x] 7.1 Rewrite `NousMergeStrategy`: drop NARS fields (`restart_count`, `pending_revision`); implement one-sided selection (pick lower-normalised-entropy posterior); emit `nous.merge_warning` when the discarded state's posterior differs by more than a configured threshold
- [x] 7.2 Update `tests/test_nous_merge_strategy.py`: replace NARS field assertions with one-sided-selection assertions and warning-flag assertions

## 8. FaithfulRenderer templates

- [x] 8.1 Add `nous.belief` template to `kaine/faithful/templates.py`: renders as `"[Nous] {statement} (certainty {confidence:.0%})"`
- [x] 8.2 Add `nous.policy` template to `kaine/faithful/templates.py`: renders as `"[Nous] policy={policy} EFE={expected_free_energy:.3f}"`

## 9. Archive executive-action-intent

- [x] 9.1 Verify `executive-action-intent` is fully merged (git log confirms merge commit `348e80d`); run `openspec archive executive-action-intent` to move it to the archive

## 10. Tests

- [x] 10.1 `tests/test_nous_generative_model.py` — model construction shapes using pymdp 1.0 JAX API; factor seam; B-matrix has four action dimensions; `encode_snapshot` handles missing factors
- [x] 10.2 `tests/test_nous_engine.py` — FakeEngine protocol; belief update changes posterior; policy selection returns lowest-EFE policy; timeout guard returns last posterior on overrun and emits `nous.timeout`
- [x] 10.3 `tests/test_nous_module.py` — broadcast → `nous.belief` (preserved shape) + `nous.policy`; epistemic action emitted as `intent.act`; opt-in real-pymdp test (`KAINE_NOUS_RUN_REAL_PYMDP=1`)
- [x] 10.4 Update `tests/test_hypnos_*` (belief-revision phase no longer steps a NAR subprocess); remove/retire NARS-specific test files
- [x] 10.5 Confirm Mnemos/Eidolon consumers still parse `nous.belief`
- [x] 10.6 `tests/test_nous_health_probe.py` — probe returns healthy when pymdp+jax importable; returns unhealthy on ImportError; no binary_path reference

## 11. Verification

- [x] 11.1 Full unit suite green **without** the ONA binary present
- [x] 11.2 EFE benchmark passes (median ≤ 200 ms) on the target CPU with the default config envelope
- [x] 11.3 `openspec validate nous-pymdp-swap --strict` clean
- [x] 11.4 Commit (Kaine.One), branch-per-change, merge, archive
