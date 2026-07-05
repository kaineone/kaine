## 1. Self-inference engine

- [x] 1.1 `kaine/modules/eidolon/self_inference.py` — `SelfInferenceEngine`: subscribe to `lingua.out`, `thymos.report`, `thymos.drive`, `nous.policy`; maintain rolling windows for VAD stats and internal-speech pattern counts
- [x] 1.2 On maintenance cycle end event: re-derive `behavioral_norms`, `personality_baseline`, `values`, `capability_map`; write to `self_model.json` atomically; leave fields empty if below `speech_pattern_min_count`

## 2. Capability map

- [x] 2.1 `kaine/modules/eidolon/capability_map.py` — read Praxis effector whitelist; aggregate Nous EFE outcome history; produce `capability_map` dict
- [x] 2.2 Update `capability_map` on each maintenance cycle end

## 3. Operator seed

- [x] 3.1 On first boot, if `[eidolon.self_inference].seed_path` is set, load seed JSONL and write all four fields to `self_model.json` as the initial state
- [x] 3.2 Subsequent inference updates are applied on top of the seed; seed is not re-applied after first boot

## 4. Eidolon module wiring

- [x] 4.1 `kaine/modules/eidolon/module.py`: include populated self-model fields in `eidolon.out` so Nexus diagnostics and the sidecar can read them

## 5. Config

- [x] 5.1 `[eidolon.self_inference]`: `enabled` (default `false`), `vad_window_cycles`, `speech_pattern_min_count`, `seed_path` (optional)

## 6. Tests

- [x] 6.1 `tests/test_eidolon_self_inference.py` — behavioral norms not populated below `speech_pattern_min_count`; populated correctly above it; VAD stats update on maintenance cycle; no raw speech text written
- [x] 6.2 `tests/test_eidolon_capability_map.py` — whitelist entries appear in capability map; EFE outcomes recorded
- [x] 6.3 `tests/test_eidolon_seed.py` — seed populates fields on first boot; observation updates on top; no seed applied without `seed_path`
- [x] 6.4 Disabled engine: no fields updated, no crash

## 7. Verification

- [x] 7.1 Full unit suite green
- [x] 7.2 `openspec validate eidolon-self-inference --strict` clean
- [x] 7.3 Commit (Kaine.One), branch-per-change, merge, archive
