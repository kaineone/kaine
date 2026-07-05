## 1. Foundation

- [x] 1.1 `kaine/perception_state.py` — runtime + desired state files
- [x] 1.2 `[audio_in]` capture keys in `config/kaine.toml`
- [x] 1.3 `[topos]` capture keys in `config/kaine.toml`
- [x] 1.4 `pyproject.toml` optional extras: `audio`, `vision`
- [x] 1.5 `.gitignore` add `state/perception/`
- [x] 1.6 `kaine/boot.py` forward new keys to `make_audio_in` + `make_topos`

## 2. Live perception classes

- [x] 2.1 `kaine/modules/audio_in/live.py` — `LiveMicrophone`
- [x] 2.2 `kaine/modules/topos/live.py` — `LiveCamera`
- [x] 2.3 Wire `LiveMicrophone` into `AudioInput.__init__/initialize/shutdown`
- [x] 2.4 Wire `LiveCamera` into `Topos.__init__/initialize/shutdown`

## 3. Nexus integration

- [x] 3.1 `kaine/nexus/perception.py` — router (GET .json + POST toggle)
- [x] 3.2 `kaine/nexus/templates/_perception_banner.html` partial
- [x] 3.3 Include banner partial in conversation.html + diagnostics.html
- [x] 3.4 Perception card on diagnostics.html
- [x] 3.5 Mount perception router in `kaine/nexus/__main__.py` (via app.py)

## 4. Tests

- [x] 4.1 `tests/test_perception_state.py` (8 tests)
- [x] 4.2 `tests/test_audio_in_live.py` (7 tests)
- [x] 4.3 `tests/test_topos_live.py` (5 tests)
- [x] 4.4 `tests/test_nexus_perception.py` (7 tests)
- [x] 4.5 `tests/test_zero_persistence_invariant.py` (4 tests, load-bearing)
- [x] 4.6 `tests/systems/test_live_perception_subsystem.py` (2 tests)

## 5. Docs

- [x] 5.1 `SECURITY.md` "Live perception" section
- [x] 5.2 `FIRST_BOOT.md` note on opt-in capture + zero-persistence

## 6. Verification

- [x] 6.1 Full suite passes (764 / 12 skipped)
- [x] 6.2 `pytest -m systems` passes
- [x] 6.3 `pytest tests/test_zero_persistence_invariant.py -v` passes
- [x] 6.4 `git grep "wave.open" kaine/modules/audio_in/` shows BytesIO only
- [x] 6.5 `git grep -E "cv2\.(imwrite|VideoWriter)" kaine/` returns empty
- [x] 6.6 `openspec validate live-perception --strict` clean
- [ ] 6.7 Commit, merge, archive, tag v1.2-perception
