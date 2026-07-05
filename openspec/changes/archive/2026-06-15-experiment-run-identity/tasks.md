# Tasks

## 1. experiment package
- [x] 1.1 New `kaine/experiment/__init__.py`.
- [x] 1.2 `kaine/experiment/seeding.py` — `set_global_seed(seed)` (random/numpy/torch best-effort).
- [x] 1.3 `kaine/experiment/run_context.py` — `RunContext` dataclass + `set_run_context`/`get_run_context` (process-global), `git_sha` best-effort, `config_digest` helper.
- [x] 1.4 `kaine/experiment/manifest.py` — atomic write of the manifest to `data/evaluation/runs/<run_id>/manifest.json`.
- [x] 1.5 `kaine/experiment/verdict.py` — `Outcome` enum + `Verdict` dataclass + `to_dict`.

## 2. record stamping
- [x] 2.1 `AsyncJsonlSink` stamps `run_id` (setdefault) + per-sink monotonic `seq` when `get_run_context()` is set; inert otherwise.
- [x] 2.2 Verify the import into `kaine/persistence/` keeps the sidecar boundary tests green.

## 3. boot wiring
- [x] 3.1 `kaine/cycle/__main__.py`: read `[experiment].seed` (or generate), `set_global_seed`, build + `set_run_context`, write manifest. Model ids gathered from the resolved config's documented model keys only.
- [x] 3.2 `config/kaine.toml`: `[experiment]` block (`seed`, `write_manifest`), shipped safe.

## 4. export + verdict adoption
- [x] 4.1 Add `runs` to `METRICS_ONLY_DIRS` in `kaine/research/submission.py`; confirm no deny-pattern collision.
- [x] 4.2 AIF benchmark report + red-team report include a `verdict` object using the shared schema (additive; existing fields kept).

## 5. tests + docs
- [x] 5.1 Tests: seeding reproducibility + torch-optional; RunContext/manifest round-trip + git fallback; sink stamping present-with-context / absent-without; config_digest stability; METRICS_ONLY_DIRS membership; boot wiring; verdict serialization.
- [x] 5.2 Docs: present-tense section on run identity / seeding / manifest under `docs/`.
- [ ] 5.3 Full suite green; `openspec validate experiment-run-identity --strict`.
