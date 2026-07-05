## 1. Mirroring

- [x] 1.1 `kaine/modules/vox/mirroring.py` — `blend_prosody(params, speaker_prosody, strength) -> ChatterboxParams` pure function; bounded residual; affect-driven params remain primary
- [x] 1.2 Mirror residual decays over `decay_s` after the partner stops speaking

## 2. Module wiring

- [x] 2.1 Subscribe Vox to `audition.prosody`; cache latest features with timestamp
- [x] 2.2 Apply `blend_prosody` after `affect_to_chatterbox` when `[vox.mirroring].enabled`; skip when disabled or no prosody seen

## 3. Config

- [x] 3.1 `[vox.mirroring]`: `enabled`, `mirror_strength`, `mirror_ceiling`, `decay_s`; update `make_vox` allowed keys

## 4. Tests

- [x] 4.1 `tests/test_vox_mirroring.py` — pure-function blend; residual bounded by ceiling; strength 0 → affect-only; decay reduces residual over time
- [x] 4.2 `tests/test_vox_module.py` — `audition.prosody` cached and applied; no prosody → affect-only; disabled → affect-only

## 5. Verification

- [x] 5.1 Full unit suite green
- [x] 5.2 `openspec validate vox-prosodic-mirroring --strict` clean
- [x] 5.3 Commit (Kaine.One), branch-per-change, merge, archive
