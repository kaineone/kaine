# Housekeeping follow-ups and unwired code

- [x] 1.1 Fix Sam generator `load_sam_model` to assert v2 checkpoint config (`spk_id["sam"]==3000`, `tts_model_type=="custom_voice"`) for local paths, and fail (no silent fallback) if missing.
- [x] 1.2 Gate `--reference-dir` as Chatterbox-only in help text and code paths of `generate_maternal_voice.py`.
- [x] 1.3 Add adapter-boundary validation in `render_maternal_voice_sam.build_render_plan()` (rate 8000, FLAC, PCM_16, ceiling 300).
- [x] 2.1 Remove global `pytestmark = pytest.mark.asyncio` from `tests/test_stimulus_first_hours_stop.py` and `tests/test_stimulus_per_pass.py`; mark only async tests.
- [x] 2.2 Add SPDX headers to `tools/maintainer/render_maternal_story.py` (already done) and any file still flagged by `check_license_headers.py` outside configured roots.
- [x] 3.1 openspec validate housekeeping-followups --strict.
- [x] 3.2 openspec validate voice-development --strict.
- [x] 3.3 openspec validate maternal-voice-unintelligible-prosody --strict.
- [x] 3.4 openspec validate entity-key-custody-software-escrow --strict.
EOF