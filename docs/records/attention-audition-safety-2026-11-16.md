# Attention/audition safety record — 2026-11-16

Docs-only. This record captures the **permissions (approvals)**, **test risks**, and
**exact validation gates** that gate OpenSpec tasks 6.7 (acoustic salience
recalibration: normalisation, alert factor, floor) and 6.8 (winner becomes the
`first_configuration` profile default). It changes no code, no config, and no task
checkboxes. Companion records: `audition-salience-recalibration-2026-11-16.md`,
`audition-salience-recompute-protocol-2026-11-16.md`,
`audition-encoder-decision-note-2026-11-16.md`,
`audition-sensor-feed-checklist-2026-11-16.md`.

## 6.7 — acoustic salience recalibration

### Permissions / approvals required (all must be granted before the edit lands)

1. **Lead review of the calibration numbers.** The window, factor, and floor values
   must be fitted on all three feed families and reviewed by the lead before any
   config or code edit. Single-feed AUC leadership swaps between the 600-block and
   1200-block snapshots, so the fit cannot be short-circuited on the synthetic feed.
2. **6.6 completion first.** 6.6 (bake-off on seeded, playlist, and stimulus-source
   feeds with the four design metrics) must be complete and its records present before
   6.7 begins. Until then, 6.7 remains a specification, not a runnable calibration.
3. **Host GPU lock.** Any GPU rerun holds the host lock (`tools/maintainer/gpu-lock.sh`);
   peak RSS budgets must be respected (`wavjepa` ~3.1 GB, `dasheng` ~1.7 GB).
   Each feed run is independent; do not run encoders concurrently.
4. **Relative-floor (Option 2) is a code change.** If the review chooses the relative
   guard (Option 2 in the recalibration note), it must be scoped as an OpenSpec change
   and go through the normal branch/PR pipeline with worker first-pass and adversarial
   review. It must not be edited inline under 6.7.
5. **No config edit inside 6.7's record.** Config edits require a separate PR. 6.7 may
   produce fitted candidate values and records only.

### Test risks (6.7)

- **Internally-defined false-alert metric.** The bake-off's `false_alerts_per_min` is
  defined as non-surprise blocks above the 95th percentile of that run's non-surprise
  salience, so it measures dispersion, not absolute behaviour. Candidate factors must
  be evaluated against an explicit decision threshold (`normalised_change >= factor`),
  otherwise a "tuned" value can mask a dangerous real false-alarm rate.
- **VAD-segmentation confound.** `prediction_error_window` is an utterance count (default
  32), shared by both histories. On continuous-window feeds (seeded, playlist, stimulus
  source) the count-to-seconds mapping differs; reporting only counts hides a timing
  mismatch. Document the seconds mapping; do not silently change the knob's unit.
- **Absolute floor is not fair across encoders.** p95 salience differs ~2× (spectral
  ~1.4 vs both SSL encoders ~3.1). A single absolute floor either deletes onsets for
  the larger-shoulder encoders or lets noise through for spectral. The cross-encoder
  parity test (candidate test 4 below) is the guard.
- **Rolling-mean lag vs onset delay.** Window candidates (8/16/32/64) trade baseline
  stability for detection delay. A candidate that raises false alerts on the
  steady-noise injection test is disqualified.
- **Zero-persistence violation.** The `--dump-analysis-json` style analysis must remain
  RAM-only: no PCM, no decoded samples, no embeddings to disk. The loader test and
  existing zero-persistence invariant must stay green.
- **Fixture size.** CI fixtures are tiny; the full 600/1200-block grid must not run in
  CI. Keep a small committed synthetic fixture for the offline candidate test; run the
  full grid in the bake-off script only.
- ** GPU/RSS pressure.** Running encoders on the host can exhaust GPU memory and disk;
  check `df -h` before and after. Aborting a run mid-flight can leave container
  storage; always use `--rm` and clean up.

### Exact validation gates (6.7)

Resource and state (run first, before any recompute):

```bash
cd /var/home/erik/Projects/kaineone/kaine
df -h /var/home/erik /run/media/erik/2TBm2Store
git status --short
git rev-parse --abbrev-ref HEAD
```

Feed prerequisites (must all be true before recompute):

- `docs/records/audition-encoder-bakeoff.json` (seeded/synthetic baseline) present.
- Seeded, playlist, and stimulus-source feed records exist and use the common
  evidence envelope from `audition-sensor-feed-checklist-2026-11-16.md`.
- Stimulus-source label rule approved (heartbeat-thud onsets).
- Host GPU lock held for any GPU rerun.

Targeted tests (must pass on CPU, no GPU):

```bash
cd /var/home/erik/Projects/kaineone/kaine
CUDA_VISIBLE_DEVICES="" PYTHONPATH=/var/home/erik/Projects/kaineone/kaine .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_audition_normalised_change.py \
  tests/test_audition_acoustic.py \
  tests/test_bench_audition_feeds.py
```

Additional candidate tests to be added before 6.7 is ticked (per recalibration note
§E): window sensitivity, factor grid, absolute-threshold cross-encoder parity,
zero-persistence loader check, steady-noise injection, onset relocation ablation
(B=200 replicates, reject if lower bound < 0.9), and the plant-habituation stream.
Each candidate change lands only with its corresponding test green.

6.7 is complete only when: per-feed calibration records exist for all three feed
families; each carries feed metadata (seed, manifest digest, knobs, label rule, hop
length); the chosen window/factor/floor are supported by the candidate tests above;
and no config has been edited inside this task.

## 6.8 — winner becomes `first_configuration` profile default

### Permissions / approvals required

1. **Integrator pinged first.** 6.8 explicitly requires the integrator's sign-off
   before editing the default profile or wiring seams. The plugin seam
   (`audition.acoustic_encoder`, in `INJECTABLE_SEAMS`) and any default change
   must be reviewed by the integrator first.
2. **6.7 complete.** Calibration must land before any default edit, so the chosen
   (window, factor, floor) are known and reviewed.
3. **6.9 (WavJEPA MMN mode) complete** before a WavJEPA default is chosen; the
   mismatch-mode result must be in hand.
4. **Hardware/resource gate.** Measured peak RSS and p95 latency from the feed
   records must fit the deployment's per-cycle budget. A winner that only clears
   the gate at excessive cost is not promoted.
5. **Licence / NOTICE edits in the same PR.** If the promoted encoder is SSL
   (Dasheng Apache-2.0 or WavJEPA MIT), add the model-card and third-party
   attribution entries to `NOTICE` and `docs/appendix-c-licences.md` in the same
   change that edits the default. Spectral (Tier 0 fallback) needs no new entry.
6. **No auto-promotion of Tier 0.** Tier 0 stays `spectral` regardless of 6.6
   outcome. A promoted winner is promoted only to the beyond-first-configuration
   default via config override and the plugin seam, with explicit
   `fallback to spectral` behaviour specified in the same change. Per-encoder factors
   are rejected unless a single global value cannot satisfy two feeds.
7. **No implementation now.** Like 6.7, 6.8 changes no code in this record; the
   default edit goes through a separate PR with worker first-pass and adversarial
   review.

### Test risks (6.8)

- **Profile test breakage.** `tests/test_first_configuration_profile.py` asserts
  `audition.general_audition is True` and `transcription_enabled is False`. Changing
  `acoustic_encoder` in `first_configuration.toml` must keep those assertions green;
  the profile must boot through `make_audition` without ConfigurationError.
- **Factory seam conflict.** A filled `acoustic_encoder` plugin seam combined with a
  non-default config value is a configuration error (factory enforces this). The
  default edit must clear one side consistently.
- **General audition gating.** A plugin-filled encoder requires `general_audition=True`;
  otherwise the factory raises. Any default flip must keep the general path on.
- **Persistence mismatch discard.** Persisted `acoustic_forward_models` are keyed by
  `model_id`; switching the default encoder invalidates prior persisted forward models
  (they are discarded with a warning). A regression here silently loses learned
  calibration. `tests/test_audition_persistence.py` must stay green.
- **Zero-persistence and audio guardrails.** The new default encoder is loaded with
  `local_files_only`, `HF_HUB_OFFLINE=1`, no `trust_remote_code`; a default edit must
  not weaken these. Models are fetched at setup time only.
- **Tier 0 drift.** Accidentally changing `config/kaine.toml` Tier behaviour or the
  spectral fallback removes the always-available safe path. Tier 0 must remain
  `spectral` and be exercised by `tests/test_audition_encoder_selection.py`.
- ** (Optional) Web-served licence.** `NOTICE`/appendix entries must remain valid
  Markdown and match the model card licences; broken links fail the docs check.

### Exact validation gates (6.8)

Profile/config tests:

```bash
cd /var/home/erik/Projects/kaineone/kaine
CUDA_VISIBLE_DEVICES="" PYTHONPATH=/var/home/erik/Projects/kaineone/kaine .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_first_configuration_profile.py \
  tests/test_first_configuration_modules.py \
  tests/test_audition_encoder_selection.py \
  tests/test_audition_persistence.py \
  tests/test_boot_wiring.py::test_audition_boot_wiring 2>/dev/null || true
```

Factory shipped-config check (catches unknown keys / broken profiles):

```bash
cd /var/home/erik/Projects/kaineone/kaine
CUDA_VISIBLE_DEVICES="" PYTHONPATH=/var/home/erik/Projects/kaineone/kaine .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_factories_from_shipped_config.py
```

Lint/type/import checks on touched files:

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/ruff check kaine tests plugins
env PYTHONPATH=/var/home/erik/Projects/kaineone/kaine .venv/bin/lint-imports
```

Full local pre-flight (run before any push):

```bash
cd /var/home/erik/Projects/kaineone/kaine
tools/maintainer/preflight-gate.sh /var/home/erik/Projects/kaineone/kaine
```

6.8 is complete only when: the integrator sign-off is recorded; the chosen winner
record (6.6) and calibration record (6.7) exist; the `NOTICE` and
`docs/appendix-c-licences.md` entries are present in the same PR; the default change
keeps `fallback to spectral`; and the targeted profile/factory/persistence tests above
are green under the pre-flight gate.