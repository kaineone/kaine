## 1. Foundation

- [x] 1.1 `kaine/evaluation/__init__.py` re-exports
- [x] 1.2 `kaine/evaluation/config.py` — `EvaluationConfig` + `load_evaluation_config`
- [x] 1.3 `[evaluation]` block in `config/kaine.toml`
- [x] 1.4 `kaine/evaluation/sink.py` — `AsyncJsonlSink` + daily rotation + retention
- [x] 1.5 `kaine/evaluation/embeddings.py` — small embedder wrapper

## 2. Observers (bus subscribers, async)

- [x] 2.1 `trajectory.py` — workspace snapshot logger
- [x] 2.2 `attribution.py` — module contribution histogram
- [x] 2.3 `proactive_audit.py` — unprompted output logger
- [x] 2.4 `sleep_snapshots.py` — Hypnos before/after
- [x] 2.5 `voice_tracking.py` — Hypnos cycle stats
- [x] 2.6 `affect_correlation.py` — Thymos+Lingua paired logger + batch correlator

## 3. Active observers (issue their own queries)

- [x] 3.1 `ab_divergence.py` — second-inference + similarity
- [x] 3.2 `memory_probes.py` — periodic probe runner
- [x] 3.3 `eidolon_accuracy.py` — daily self-description scorer

## 4. Registry + cycle integration

- [x] 4.1 `kaine/evaluation/registry.py` — `SidecarRegistry`
- [x] 4.2 `kaine/cycle/__main__.py` — boot sidecar when enabled
- [x] 4.3 `.gitignore` data/ + `.gitkeep` for the directories

## 5. Nexus integration

- [x] 5.1 `kaine/evaluation/nexus_tab.py` — evaluation router
- [x] 5.2 Template + diagnostics page link
- [x] 5.3 Nexus entrypoint wires the eval router into Nexus when enabled

## 6. Tests

- [x] 6.1 Sink + rotation (10 tests)
- [x] 6.2 Each observer (16 tests)
- [x] 6.3 Registry boots from config (5 tests)
- [x] 6.4 `no_core_import` boundary test
- [x] 6.5 Nexus eval route (5 tests)

## 7. Verification

- [x] 7.1 Full suite passes (681 / 8 skipped)
- [x] 7.2 `openspec validate evaluation-sidecar --strict` clean
- [ ] 7.3 Commit, merge, archive, tag v1.1-evaluation
