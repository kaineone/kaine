## 1. Band-step check (done before code)

- [x] 1.1 Offline band-step check, three seeds, with and without the melody and a proxy outside voice: harness `tools/research/band_step_check.py`, `band_step_report.py`, `run_band_step_check.sh` (branch `research/band-step-check`); record `docs/records/validation/band-steps/2026-10-31-summary.json`. Result: the 12-minute saturation is the estimator restart; steps 1 and 2 register; steps 3 and 4 add almost nothing; no implementation fault; the short-transient fixes are rejected. The selected fix (full-span saturation) is in this change's spec.
- [ ] 1.2 Merge the harness and the record with this change, at `tools/research/` as built.

## 2. Full-span release rule

- [ ] 2.1 `WindowedProgress` exposes its completed-bin count since the last restart; `Affect.audition_learning_progress(stage)` returns None until it reaches `learning_progress_span_s / learning_progress_bin_s`. Tests in the affect tests for both spec scenarios, including that the drives' learning progress and the `affect.state` field are unchanged.
- [ ] 2.2 `HearingStageState` drops the minimum dwell; `min_dwell_seconds` is accepted with a warning and ignored; boot checks `learning_progress_span_s + saturation_window_seconds <= max_dwell_seconds`. Tests for every scenario of the modified requirements, and a mutation check that returning a partial-window reading makes "Saturation before the minimum dwell does not advance" fail.
- [ ] 2.3 Replay the band-step record's traces through the new rule and record the stage dwells (expected: 2.6 to 5.3 h for stages 0 to 2, about 1.67 h for stages 3 and 4).

## 3. Live gap and welfare (before the development run)

- [ ] 3.1 After the perception-feed fixes (video drift with variable-frame-rate files, `kaine/modules/vision/feed.py`; padded PyAV audio planes, `kaine/modules/audition/feed.py`) are merged: rerun the harness with an arousal trace, rests that suspend adaptation and a broadcast-context input, or replay a test boot's audition errors through the same estimator. Store the record, naming the method, with the alert rate and arousal per stage. If steps 1 and 2 stay under `lp_0`, open a separate calibration change for audition's `lp_0`.
- [ ] 3.2 Through the real affect module in the same harness: boredom's deprivation share over a simulated developmental span, with and without the added sounds.
- [ ] 3.3 `tests/test_band_step_records.py`: both records exist and name the shipped stimulus version.
- [ ] 3.4 Give both records to the operator with `welfare-indicator-response`'s replay before the development run starts.

## 4. Added sounds

- [ ] 4.1 Confirm against Partanen et al. (2013) which melody they played; write its note list (public-domain tune, G4 to E5) and `tools/maintainer/render_melody.py` (harmonic tones, smooth envelopes, seeded tempo and level variants, 8 kHz mono FLAC, manifest entries).
- [ ] 4.2 `tools/maintainer/generate_outside_voice.py` on the maternal-voice tool's pattern: Chatterbox TTS at the pinned revision, a male CMU ARCTIC reference speaker, texts in `added_sounds_data/texts.toml` written for KAINE with no names, two takes per item, 8 kHz FLAC, manifest with sha256, seed and settings; `--verify` checks shipped files. Rendered in a GPU window with no entity running. Then run the harness's outside-voice arm with the real takes.
- [ ] 4.3 `added_sounds_data/README.md` with provenance; the speaker database notice in `THIRD_PARTY_LICENSES.md`; `docs/appendix-c-licences.md`.
- [ ] 4.4 `kaine/modules/audition/added_sounds.py`: manifest check, slot plan on `(seed, slot)` after the maternal-voice plan (at most one sound per slot), levels and ramps, the outside voice's 3000 Hz low-pass; mixed in `kaine/modules/audition/feed.py` before the hearing band; `[perception_feed.stimulus_source.added_sounds]` parses `enabled`, `melody_probability`, `outside_voice_probability` with ranges checked and unknown keys refused; the Partanen and Querleu citations at the code site. Tests in `tests/test_added_sounds.py` for every added-sound scenario.

## 5. Docs, review and checks

- [ ] 5.1 The developmental-phase chapter (the full-span rule, the added sounds, the band-step records, steps 3 and 4 recorded as adding little); paper notes for §5.4 (stages released on a full-span reading) and A.7 (the record's dwells replace "5.1 to 5.7 hours").
- [ ] 5.2 `openspec validate developmental-stimulus-progress --strict` passes.
- [ ] 5.3 Worker first-pass review, then the integrator's independent second review.
