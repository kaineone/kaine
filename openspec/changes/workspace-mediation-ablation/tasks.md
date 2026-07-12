<!-- Implementation status (branch feat/workspace-mediation-ablation, uncommitted):
groups 1–4 + 6 implemented and tested, plus suite wiring (2.8b) and boot-integration
(3.2). 41 new assertions across 4 test files pass; the evaluation-suite tests pass
with the mediation ablation as the 8th experiment; lint-imports 5/5 kept; adjacent
suites green. ONLY remaining: the review-gated paper reconciliation (group 5), which
is deliberately not committed by this change. -->

## 1. Flat-fan-in conditioning path (eval-layer only)

- [x] 1.1 Add a helper that builds a "flat snapshot" of all current module outputs
  (no scoring / top-k / inhibition) suitable for the same renderer the on-arm uses
  (`faithful/renderer.py:render_snapshot_bounded`) — `conditioning.flat_fan_in_snapshot`.
- [x] 1.2 Enforce matched rendering budget (same max-events / char-budget bounds) as
  the workspace-on path, so the off arm is neither starved nor advantaged.
- [x] 1.3 Test (spec `workspace-mediation-ablation` fair-null): all candidates retained
  with raw salience; the off arm differs only in selection structure.

## 2. Workspace-mediation ablation runner

- [x] 2.1 Create `kaine/evaluation/benchmarks/workspace_mediation_ablation/` running the
  REAL Soma + two identically-seeded Chronos arms by hand (deterministic; Soma shared,
  arm-independent). On-arm Chronos predicts the competitively-selected coalition; off-arm
  Chronos predicts the flat snapshot (Chronos only predicts snapshots — "flat" is the
  faithful, error-sample-parity off-arm, not a separate raw-stream path).
- [x] 2.2 PRIMARY measure 1 — cross-module error coupling: mean sliding-window Pearson
  correlation of Soma's and Chronos's error series per arm; directional criterion =
  `coupling_delta = coupling_on - coupling_off` (`measures.mean_windowed_correlation`).
- [x] 2.3 PRIMARY measure 2 — coalition-selection structure: Shannon entropy /
  entropy-fraction of the on-arm coalition-source sequence (`measures.shannon_entropy`).
- [x] 2.4 SECONDARY measure — conditioning divergence (cosine via `text_embedding`
  HashEmbedder over the rendered content = the deterministic greedy-output proxy),
  reported as propagation confirmation only.
- [x] 2.5 Record the candidate-vs-`top_k` regime per run (`competing_fraction`); the
  summary warns when capacity was never exceeded (broadcast-mediation, not competition).
- [x] 2.6 Neutral + soma_salient + decoupled batteries; substrate perturbations make Soma
  salient on a reported fraction of ticks; a Soma-never-salient run is flagged
  `underpowered`, not NULL.
- [x] 2.7 `_classify → Verdict` with a real `min_effect`; WIN / NULL (prompt-assembler) /
  NEGATIVE all reachable (verified empirically across seeds/batteries).
- [x] 2.8a Add `__main__.py` CLI and a `run_multi_seed` stability adapter (`stability.py`).
- [x] 2.8b Wire the runner into the suite orchestrator (`benchmarks/suite.py`) as an
  eighth experiment and second p-value producer: a dependency-free sign-test over the
  per-seed `coupling_delta` distribution feeds the Holm-Bonferroni family; aggregate
  WIN/NULL/NEGATIVE verdict from mean delta + p. Suite test asserts it joins the family.
- [x] 2.9 Test: same seed reproduces effect + verdict; indistinguishable arms yield NULL;
  the adverse case yields NEGATIVE; a Soma-never-salient run is flagged underpowered;
  WIN detail states "does work," not "is better" / "beats every aggregation."

## 3. Minimal run configuration

- [x] 3.1 Add the labeled minimal experiment overlay `config/profiles/minimal_experiment.toml`
  enabling only `soma/chronos/lingua`, `volition.drive_initiative=false`, Lingua greedy
  (`temperature=0.0`), and `syneidesis.top_k=2`; documented as NOT a deployment tier.
- [x] 3.2 Test: booting the overlay through the real `build_registry` registers exactly
  Soma/Chronos/Lingua, drags in no disabled module (mnemos/eidolon/thymos/…), and a
  disabled toggle flipped back on re-registers — proving no work is lost
  (`tests/test_minimal_experiment_profile.py`).

## 4. Operator text-stimulus injection

- [x] 4.1 Add a headless injector (`inject.py`) that writes an encoded
  `source="audition", type="audition.transcription"` event onto an active `.out` stream
  the cycle reads, plus `read_latest_external` from `lingua.external`.
- [x] 4.2 Test: an injected utterance lands as an audition-typed event on an active stream
  (Volition-matchable) with no Audition module registered; response reader is safe when
  silent. (Full cycle→speak-intent→Lingua roundtrip is left to an integration run.)

## 5. Paper reconciliation (review-gated, NOT committed by this change)

- [ ] 5.1 Reconcile §1.2 / §3.2 / §6.3 / abstract to the competitive-mediation framing;
  audit the §4 sixteen-module count. (Largely already done in `paper-preprint-minimal_02.md`.)
- [ ] 5.2 Add to §6.3 / §9 the two construct-validity caveats: (a) competition is only
  exercised when `top_k` < candidate count; (b) the faithful off-arm has Chronos predict
  the FLAT snapshot (Chronos only predicts snapshots), so the primary measure is
  cross-module correlation, not absolute error.
- [ ] 5.3 Draft the pre-registration (controls, metrics, thresholds, window/significance
  params, `top_k`, Soma-salience coverage, coherence-vs-divergence limit) for Erik.

## 6. Verification

- [x] 6.1 `lint-imports` (5/5 kept); shipped-config all-off guard
  (`test_committed_config_ships_all_modules_disabled`) still passes; no module default
  changed; adjacent suites (config, soma, chronos, oscillatory, dual-path) green.
- [x] 6.2 Ran the ablation end-to-end on single seeds (CLI, writes JSONL) and across the
  multi-seed battery (stability adapter); all three verdicts reachable, run reproducible.
