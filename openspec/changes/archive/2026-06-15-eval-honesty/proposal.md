## Why

The evaluation sidecar contains five honesty violations discovered in the
pretend-process audit (2026-06-09). Each silently misrepresents metric
quality, scores missing data as valid, or advertises signals that do not
exist.

- **H5 (CRITICAL):** `SidecarRegistry._embedder_default()` silently falls
  back to `HashEmbedder` when `sentence_transformers` fails. Cosine metrics
  in A/B-divergence and memory-probe JSONL records then measure lexical
  token-hash similarity, not semantic similarity, with no disclosure. Anyone
  reading logs or running analysis sees plausible-looking cosine numbers that
  are quietly meaningless.

- **H4:** `CLAIM_KEYWORDS` in `eidolon_accuracy.py` maps `"honest"` →
  `belief_confidence` and `"open"` → `openness`, but neither signal is ever
  populated in `_signals_snapshot()`. The metric advertises scoring those
  claim types when it actually returns `None` (unavailable) for both.

- **M6:** In the same file, the `curiosity` signal is derived from whether
  today's proactive-audit JSONL is non-empty — a file-existence proxy — but
  is stored under the plain key `"curiosity"`, indistinguishable from a real
  drive measurement in downstream logs.

- **L3:** `EmpatheiaObserver` defaults `observed_confidence` to `0.5` when
  the audition event carries no `confidence` field. A missing value is scored
  as accuracy ≈ 1.0 (because `|reliability - 0.5|` is small for any
  prediction near the centre), inflating the metric for no-op pairings.

- **L5:** The Nous health probe returns `UP` if `pymdp` and `jax` are
  importable, without verifying that the generative model can actually be
  built. A broken numpy ABI or missing dependency that only surfaces at
  construction time passes the probe.

## What Changes

The changes SHALL make every evaluation output honest — disclose the
embedder kind used in each record, remove unsupported claim keywords, label
proxy signals as proxies, skip no-data pairings, and extend the Nous probe
to perform a real build check.

### Embedder disclosure (H5)

- `HashEmbedder` and `SentenceTransformerTextEmbedder` SHALL each carry a
  `kind: str` class attribute (`"hash"` and `"sentence_transformers"`
  respectively).
- Every A/B-divergence JSONL record SHALL include an `"embedder"` field
  equal to the embedder's `kind`.
- Every memory-probe JSONL record SHALL include an `"embedder"` field equal
  to the embedder's `kind`.
- On fallback to `HashEmbedder`, `SidecarRegistry._embedder_default()` SHALL
  log at `ERROR` level (not `WARNING`) with an explicit statement that cosine
  metrics will be lexical.
- `EvaluationConfig` SHALL gain a `require_semantic_embedder: bool = False`
  field. When `True`, `_embedder_default()` SHALL raise instead of falling
  back.

### Unsupported claim removal (H4)

- `CLAIM_KEYWORDS` SHALL NOT contain `"honest"` or `"open"`. A comment
  SHALL explain they are absent because no real signal source exists.

### Curiosity proxy labelling (M6)

- The curiosity signal key SHALL be `"curiosity_proxy"` in both
  `_signals_snapshot()` and `CLAIM_KEYWORDS`, making it machine-distinguishable
  from real drive measurements.
- Eidolon accuracy JSONL records SHALL include `"curiosity_proxy_used": bool`
  so downstream readers can filter out proxy-scored claims.

### Empatheia confidence guard (L3)

- When an audition event carries no `confidence` key, `EmpatheiaObserver`
  SHALL skip the pairing and write no record.
- When `confidence` is present, records SHALL include `"confidence_present":
  true`.

### Nous build check (L5)

- After confirming `pymdp` and `jax` are importable, `nous_health_probe()`
  SHALL attempt `build_generative_model()` with default parameters.
- If the build succeeds, the probe returns `UP` with a message including
  "generative model built".
- If the build fails, the probe returns `DEGRADED` with a short detail message.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `evaluation-sidecar`: embedder kind disclosed in every A/B-divergence and
  memory-probe record; fallback logs at ERROR; `require_semantic_embedder`
  config flag added; `CLAIM_KEYWORDS` no longer advertises unsupported claims;
  curiosity signal renamed to `curiosity_proxy`; eidolon records carry
  `curiosity_proxy_used`.
- `evaluation-observers`: empatheia observer skips pairings with absent
  confidence rather than scoring fabricated defaults.
- `nexus-observability`: Nous health probe verifies the generative model
  builds, not just that pymdp/jax import.

## Impact

- **Code (edit):**
  - `kaine/evaluation/embeddings.py` — add `kind` attribute to both classes
  - `kaine/evaluation/registry.py` — error log on fallback; fail-closed when flag set
  - `kaine/evaluation/config.py` — add `require_semantic_embedder` field
  - `kaine/evaluation/ab_divergence.py` — thread `embedder` field into records
  - `kaine/evaluation/memory_probes.py` — thread `embedder` field into records
  - `kaine/evaluation/eidolon_accuracy.py` — remove `honest`/`open`; rename
    curiosity key; add `curiosity_proxy_used` to output
  - `kaine/evaluation/observers/empatheia_observer.py` — skip absent confidence
  - `kaine/nexus/health.py` — extend Nous probe with build check
- **Tests:** `tests/test_evaluation_honesty.py` (new file covering all five findings)
- **Safety:** all changes tighten honesty; no new data collection, no module enables
