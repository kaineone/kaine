## 1. Affect tagging

- [x] 1.1 Subscribe Mnemos to `thymos.state`; cache latest affect (intensity + VAD)
- [x] 1.2 Tag each stored trace with the cached affect; ensure recall affect-bias uses it

## 2. Replay selection + re-injection

- [x] 2.1 `kaine/modules/mnemos/replay.py` — selection by `affect_weight × intensity + recency_weight × recency`, top-k
- [x] 2.2 `replay(window)` publishes selected traces as `mnemos.replay` events (trace content for re-processing) only during an active Hypnos replay window; if called outside a window, raise a precondition error and emit nothing
- [x] 2.3 Each `mnemos.replay` serves as Phantasia's seed cue

## 3. Redact-content option

- [x] 3.1 Add `redact_content` (default `true`) to `[mnemos.replay]` config; when true, `mnemos.replay` events delivered to the sidecar replay observer carry only memory IDs, not trace text content

## 4. Config

- [x] 4.1 `[mnemos.replay]`: `selection_top_k`, `affect_weight`, `recency_weight`, `redact_content`; update `make_mnemos` allowed keys

## 5. Tests

- [x] 5.1 `tests/test_mnemos_replay.py` — selection ranks high-affect/recent traces first; `replay()` emits `mnemos.replay` with trace content inside a replay window; `replay()` raises precondition error and emits nothing outside a window
- [x] 5.2 `tests/test_mnemos_replay_redact.py` — with `redact_content=true`, observer payload contains only memory IDs; with `redact_content=false`, observer payload contains full text content
- [x] 5.3 `tests/test_mnemos_module.py` — stored traces carry affect tags from `thymos.state`; recall bias intact

## 6. Verification

- [x] 6.1 Full unit suite green
- [x] 6.2 `openspec validate mnemos-replay --strict` clean
- [x] 6.3 Commit (Kaine.One), branch-per-change, merge, archive
