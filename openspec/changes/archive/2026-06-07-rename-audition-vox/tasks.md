## 1. Rename hearing module (audio_in → audition)

- [x] 1.1 `git mv kaine/modules/audio_in kaine/modules/audition`; rename class `AudioInput` → `Audition`, `name = "audition"`
- [x] 1.2 Rename published event types: `audio.in.transcription` → `audition.transcription`, `audio.in.emotion` → `audition.emotion`
- [x] 1.3 Update `kaine/modules/__init__.py` export

## 2. Rename voice module (audio_out → vox)

- [x] 2.1 `git mv kaine/modules/audio_out kaine/modules/vox`; rename class `AudioOutput` → `Vox`, `name = "vox"`
- [x] 2.2 Rename published event type `audio.out.synthesized` → `vox.synthesized`; sink dir `state/audio_out/` → `state/vox/`
- [x] 2.3 Update `kaine/modules/__init__.py` export

## 3. Boot + config

- [x] 3.1 Rename `make_audio_in`/`make_audio_out` → `make_audition`/`make_vox`; update `SIMPLE_FACTORIES` keys and allowed-key sets
- [x] 3.2 Rename `[audio_in]`/`[audio_out]` config sections → `[audition]`/`[vox]`; update `[modules]` toggles (still `false`)
- [x] 3.3 Update `pyproject.toml` setuptools packages list

## 4. Cross-references

- [x] 4.1 Update `kaine/workspace/volition.py` constants (`USER_COMMUNICATION_SOURCE="audition"`, `USER_COMMUNICATION_TYPE="audition.transcription"`, own-speech constants)
- [x] 4.2 Update Nexus stream lists + health probes in `kaine/nexus/`
- [x] 4.3 Grep the repo for residual `audio_in`/`audio_out`/`audio.in.`/`audio.out.` references in BOTH code and docs and update all hits not already covered by other tasks
- [x] 4.4 Update `DEFAULT_USER_INPUT_STREAMS` in `kaine/modules/chronos/module.py` to `("audition.out",)`, and update the assertion in `tests/test_config_stream_wiring.py` for that code default

## 5. Tests

- [x] 5.1 `git mv` the `test_audio_in_*`/`test_audio_out_*` files to `test_audition_*`/`test_vox_*`; update all references and the `subsystem` tests
- [x] 5.2 Update `test_boot_wiring.py` SIMPLE_FACTORIES expected set, `test_config_stream_wiring.py`, `test_volition.py`, `test_module_device_pinning.py`
- [x] 5.3 Update hardcoded `audio_in`/`audio.in.transcription` references in `tests/test_drive_policy.py`, `tests/test_cycle_volition.py`, `tests/test_nexus_perception.py`, and `tests/test_lingua_module.py`

## 6. Verification

- [x] 6.1 Full unit suite green; no residual `audio_in`/`audio_out` references (grep clean except this change's history)
- [x] 6.2 `openspec validate rename-audition-vox --strict` clean
- [x] 6.3 Commit (Kaine.One identity), branch-per-change, merge, archive
