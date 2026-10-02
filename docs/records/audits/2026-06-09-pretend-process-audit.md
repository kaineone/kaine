# Pretend-process audit — findings (kaine repo)

Read-only sweep of the `kaine` repo (2026-06-09) for code that fakes/stubs/no-ops
real work while presenting or claiming success it didn't earn. These are **kaine
findings**, recorded here so they aren't lost; they get fixed *in the kaine repo*
as **"Change 5"** (real implementation or honest failure — never a silent fake).

Standard for a finding: does it **lie about having done the work**, or feed a
fabricated value into the cognition/eval pipeline without disclosure? Honest
graceful degradation that logs truthfully is NOT a finding.

## Must-fix before the first boot (experiment validity)

These would make fakery look like real cognition / corrupt the core metrics:

- **H5 — eval embedder silently falls back to a lexical hash.** `evaluation/registry.py:114-121`: if `SentenceTransformerTextEmbedder` fails to load, `SidecarRegistry` silently uses `HashEmbedder` (a bag-of-words hash, "not semantically meaningful"). A/B-divergence and memory-probe `cosine_similarity` are then **lexical, not semantic**, with no disclosure in the logs or JSONL. This corrupts the project's *core evidence metric*. **Fix:** log a prominent warning + record `"embedder": "hash"|"sentence_transformers"` in every record; consider failing closed when the sidecar is enabled.
- **H7 — imagination ships as a stub by default.** `config/kaine.toml` ships `[phantasia].backend = "fake"`; the live loop runs `FakeWorldModel` (an EMA filter) and publishes `phantasia.world_error` as if it were DreamerV3 RSSM prediction error, with no backend disclosure in the event. **Fix:** at minimum stamp `"backend"` into the event; decide whether the shipped default should be `fake` at all, or fail-closed/log when imagination is enabled without the real world model.
- **H3 — emotion fabricates "neutral" when the model is absent.** `audition/emotion.py:144-152` + `module.py:267-274`: with `funasr` unavailable, `classify()` returns `neutral / confidence 0.0 / raw{degraded:True}`, and `_publish_emotion` **strips the degraded flag** — Empatheia and the forward model ingest a fake neutral reading as real. **Fix:** raise (→ existing error path) or carry `"degraded": True` on the `audition.emotion` event.
- **H2 — a Scherer appraisal dimension is hardcoded zero.** `thymos/module.py:239-240`: `norm_compatibility = 0.0` always, published in `thymos.emotion` as a real dimension; the DISGUST branch can never fire. **Fix:** wire from Eidolon or mark the dimension unavailable in the payload.
- **H1 — Nous hides inference crashes as a forced no_op.** `nous/engine.py:280-291`: a non-timeout exception is swallowed and returns a well-formed result (`timed_out=False`, `action=no_op`) from stale priors; `nous.belief`/`nous.policy` publish as if computed. **Fix:** flag the error (`error=True`/`nous.error`) instead of emitting fabricated belief/policy.
- **M5 — two of four salience factors are inert in the live cycle.** `workspace/strategies.py` + `salience.py`: `StaticGoalScorer`/`StaticThymosModulator` return constant `1.0`, so live salience is effectively `intensity*novelty`. Docstrings are honest, but there's no runtime disclosure. **Fix:** one-time `log.warning` when the static placeholders are wired in, so the degraded salience is visible.

## High

- **H4 — eval claim signals never populated.** `evaluation/eidolon_accuracy.py`: `CLAIM_KEYWORDS` advertises `honest`→`belief_confidence` and `open`→`openness`, but `_signals_snapshot` never sets them (abandoned `# Default 0.` stub). Those claim types are silently dropped from accuracy. **Fix:** wire the signals or remove the unsupported keywords.
- **H6 — adapter merge silently no-ops.** `lifecycle/manager.py:42-70`: `FakeAdapterMerger.merge()` concatenates path lists without merging weights; the `adapter_merge_skipped` metadata isn't surfaced in the CLI/Nexus merge output. **Fix:** surface the skip to the operator; refuse/require-ack when both parents have adapters and no real merger is configured.
- **H8 — FakeTrainer in the runtime voice-alignment path.** `hypnos/voice_alignment.py` + `module.py:85` + `boot.py`: when `voice_alignment.enabled=True` but the `[training]` extras are missing, Hypnos silently falls back to `FakeTrainer` (only a `log.warning`). **Fix:** `enabled=True` + no real trainer should be a config error, not a silent fake.

## Medium

- **M1 — decommission backup: encryption failure leaves plaintext but reports `ok=True`.** `lifecycle/decommission.py:393-397`. **Fix:** `ok=False` (or prominent manifest `encryption_failed:true` + operator warning) when encryption was enabled and failed.
- **M2 — research bundle: same encryption-failure-as-plaintext, no error to caller.** `research/submission.py:349-356`. **Fix:** distinguish "disabled" from "enabled-but-failed".
- **M3 — Thymos regulation is a silent no-op.** `thymos/regulation.py:33-34` (`PassiveDecay` default returns zero every tick, no log). **Fix:** log once / gate so the no-op is visible.
- **M4 — goal_significance is undisclosed token-overlap.** `thymos/goals.py:98-115` feeds a bag-of-words proxy into the appraisal as `goal_significance` with no method tag in the event. **Fix:** tag the method / guard to 0 when no goals.
- **M6 — eval curiosity is a file-nonempty proxy.** `evaluation/eidolon_accuracy.py:141-152`, undisclosed. **Fix:** label it `curiosity_proxy` in the record.
- **M7 — Mnemos recall swallows storage errors.** `mnemos/storage.py:288-290`: a Qdrant failure looks like an empty recall (`count=0`), no failure signal on `mnemos.recall`. **Fix:** surface an error field / don't publish a fake empty recall.

## Low

- **L1** — `chronos/featurizer.py:115`: reserved `vec[23]` permanently 0.0 (wasted feature dim; future weight bias).
- **L2** — `empatheia/module.py:202-225`: double-counts interactions off the degraded emotion path (downstream of H3; resolved once H3 carries the flag).
- **L3** — `evaluation/observers/empatheia_observer.py:128-130`: missing `confidence` defaults to 0.5 → inflated accuracy. **Fix:** skip or tag.
- **L4** — `lifecycle/decommission.py:484-510`: Qdrant `get_collections()` failure assumes all collections exist. **Fix:** log + record in errors.
- **L5** — `nexus/health.py:524-544`: Nous probe checks importability only, reports `UP` even if the engine can't build. **Fix:** attempt a cheap `build_generative_model()`.

## Clean (audited, no findings)

Soma, Chronos (core), Eidolon, Lingua, Topos, Vox, Praxis, Perception, Mundus,
Hypnos phases; `security/crypto` (real AES-GCM, fails loud when enabled+keyless),
snapshot/fork/restore, divergence, the decommission CLI gates, Nexus health
network probes + diagnostics, the setup wizard + `dependencies.py` (honest
detect-and-guide), transfer/email (no silent send), `hardware.py`, `boot.py`,
`perception_state.py`, `scripts/`, the bus client, the cycle engine/spot/preflight/
control_state, and most evaluation observers + individuation.

## Shape of the fixes

Most are small and honest: **surface a flag / log truthfully / fail closed** — not
rewrites. The few genuine fakes wired into runtime (H5 embedder fallback, H7
`backend="fake"` default, H6 adapter merge, H3 emotion, H1 nous) are the priority.
Recommend a `pretend-process-fixes` OpenSpec change in `kaine`, must-fix set landed
before the supervised boot.
