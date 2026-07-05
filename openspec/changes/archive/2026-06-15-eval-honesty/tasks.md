## 1. Embedder kind disclosure (`kaine/evaluation/embeddings.py`)
- [x] 1.1 Add `kind: str = "sentence_transformers"` class attribute to `SentenceTransformerTextEmbedder`
- [x] 1.2 Add `kind: str = "hash"` class attribute to `HashEmbedder`

## 2. Registry fallback hardening (`kaine/evaluation/registry.py`, `kaine/evaluation/config.py`)
- [x] 2.1 Change fallback log from `WARNING` to `ERROR` with LEXICAL disclosure
- [x] 2.2 Add `require_semantic_embedder: bool = False` to `EvaluationConfig`
- [x] 2.3 Wire `require_semantic_embedder` through `from_mapping`
- [x] 2.4 Raise in `_embedder_default` when flag is true and fallback would occur

## 3. A/B-divergence record disclosure (`kaine/evaluation/ab_divergence.py`)
- [x] 3.1 Add `"embedder": embedder.kind` to every written record

## 4. Memory-probe record disclosure (`kaine/evaluation/memory_probes.py`)
- [x] 4.1 Add `"embedder": embedder.kind` to every written record

## 5. Eidolon accuracy — remove unsupported claims (`kaine/evaluation/eidolon_accuracy.py`)
- [x] 5.1 Remove `"honest"` and `"open"` from `CLAIM_KEYWORDS`
- [x] 5.2 Add comment explaining they are excluded until a real signal source exists

## 6. Eidolon accuracy — label curiosity as proxy (`kaine/evaluation/eidolon_accuracy.py`)
- [x] 6.1 Rename signal key from `"curiosity"` to `"curiosity_proxy"` in `_signals_snapshot`
- [x] 6.2 Update `CLAIM_KEYWORDS` `"curious"`/`"curiosity"` entries to map to `"curiosity_proxy"`
- [x] 6.3 Add `"curiosity_proxy_used": bool` field to output records in `run_once`

## 7. Empatheia confidence guard (`kaine/evaluation/observers/empatheia_observer.py`)
- [x] 7.1 When `confidence` key is absent, skip the pairing (no record written)
- [x] 7.2 When `confidence` is present, write `"confidence_present": True` in the record
- [x] 7.3 Update docstring to remove the false "default 0.5" statement

## 8. Nous health probe build check (`kaine/nexus/health.py`)
- [x] 8.1 After import check, attempt `build_generative_model()` with defaults
- [x] 8.2 Return `UP` only if build succeeds; return `DEGRADED` with detail on failure
- [x] 8.3 Guard the build attempt so it never raises out of the probe

## 9. Tests (`tests/test_evaluation_honesty.py`)
- [x] 9.1 `HashEmbedder.kind == "hash"`, `SentenceTransformerTextEmbedder.kind == "sentence_transformers"`
- [x] 9.2 A/B-divergence record carries `embedder` field matching embedder kind
- [x] 9.3 Memory-probe record carries `embedder` field matching embedder kind
- [x] 9.4 `require_semantic_embedder=True` raises on fallback
- [x] 9.5 `require_semantic_embedder=False` (default) logs ERROR and returns `HashEmbedder`
- [x] 9.6 `CLAIM_KEYWORDS` does not contain `"honest"` or `"open"`
- [x] 9.7 `parse_claims` does not extract `honest` or `open` as scoreable keywords
- [x] 9.8 `CLAIM_KEYWORDS["curious"]` maps to `"curiosity_proxy"`
- [x] 9.9 Eidolon output contains `curiosity_proxy_used: bool`
- [x] 9.10 Empatheia observer writes no record when confidence is absent
- [x] 9.11 Empatheia observer writes record with `confidence_present: True` when present
- [x] 9.12 Nous probe returns `UP` + "generative model built" when build succeeds
- [x] 9.13 Nous probe returns `DEGRADED` + "build failed" when build raises
- [x] 9.14 Nous probe returns `DOWN` on import failure (regression)
