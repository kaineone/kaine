## 1. Audition fixes

- [x] 1.1 `acoustic.py`: `attend_recent(audio_bytes, fraction, sample_rate, min_seconds)` returns the most recent fraction of the window (at least one frame); `_log_spaced_edges` returns strictly increasing indices starting at bin 1; `model_id` is `spectral-logband-{n}-v2`.
- [x] 1.2 `module.py`: compute the window before encoding and encode and measure energy on the attended span; publish `attended_seconds`.
- [x] 1.3 `module.py`: the tone feature is the utterance's audio duration over 30 s; serialize tags `forward_model_features = "utterance_duration_v2"`; deserialize discards an untagged speech-path checkpoint.
- [x] 1.4 Tests: the window shrinks the encoded span with arousal and never below one frame; no two bands share their edge pair and none starts at DC; the feature uses audio duration, independent of classifier latency; untagged checkpoint discarded; model_id bump; mutation-check.
- [x] 1.5 Docs: `docs/09-modules/audition.md`; note in `openspec/changes/attention-driven-audition/tasks.md`.
- [x] 1.6 `openspec validate audition-window-duration-bands --strict`.
