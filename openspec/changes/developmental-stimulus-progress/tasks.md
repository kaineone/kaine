## 1. Band-step check (done before code)

- [x] 1.1 Offline band-step check, three seeds, with and without the melody and a proxy outside voice: harness `tools/research/band_step_check.py`, `band_step_report.py`, `run_band_step_check.sh` (branch `research/band-step-check`); record `docs/records/validation/band-steps/2026-10-31-summary.json`. Result: the 12-minute saturation is the estimator restart; steps 1 and 2 register; steps 3 and 4 add almost nothing; no implementation fault; the short-transient fixes are rejected. The selected fix (full-span saturation) is in this change's spec.
- [x] 1.2 Merge the harness and the record with this change, at `tools/research/` as built.

## 2. Full-span release rule

- [x] 2.1 `WindowedProgress` exposes its completed-bin count since the last restart; `Affect.audition_learning_progress(stage)` returns None until it reaches `learning_progress_span_s / learning_progress_bin_s`. Tests in the affect tests for both spec scenarios, including that the drives' learning progress and the `affect.state` field are unchanged.
- [x] 2.2 `HearingStageState` drops the minimum dwell; `min_dwell_seconds` is accepted with a warning and ignored; boot checks `learning_progress_span_s + saturation_window_seconds <= max_dwell_seconds`. Tests for every scenario of the modified requirements, and a mutation check that returning a partial-window reading makes "Saturation before the minimum dwell does not advance" fail.
- [x] 2.3 Replay the band-step record's traces through the new rule and record the stage dwells (expected: 2.6 to 5.3 h for stages 0 to 2, about 1.67 h for stages 3 and 4). Done: `tools/research/band_step_full_span_replay.py`, record `2026-10-31-full-span-replay.json`; stages 0 to 2 released 2.65 to 4.85 h in (two runs of stage 1 not within the 5 h hold), stage 3 at 1.67 to 1.70 h.

## 3. Live gap and welfare (before the development run)

- [ ] 3.1 After the perception-feed fixes (video drift with variable-frame-rate files, `kaine/modules/vision/feed.py`; padded PyAV audio planes, `kaine/modules/audition/feed.py`) are merged: rerun the harness with an arousal trace, rests that suspend adaptation and a broadcast-context input, or replay a test boot's audition errors through the same estimator. Store the record, naming the method, with the alert rate and arousal per stage. If steps 1 and 2 stay under `lp_0`, open a separate calibration change for audition's `lp_0`.
- [ ] 3.2 Through the real affect module in the same harness: boredom's deprivation share over a simulated developmental span, with and without the added sounds.
- [x] 3.3 `tests/test_band_step_records.py`: both records exist and name the shipped stimulus version. Built: the version is `kaine.boot.stimulus_version`; each record has a `*.record.json` sidecar. The test fails until the live-gap record (3.1) exists; the 2026-10-31 record predates versioning and names none.
- [ ] 3.4 Give both records to the operator with `welfare-indicator-response`'s replay before the development run starts.

## 4. Added sounds

- [x] 4.1 Confirm against Partanen et al. (2013) which melody they played; write its note list (public-domain tune, G4 to E5). Confirmed: Partanen, Kujala, Tervaniemi and Huotilainen 2013, PLoS ONE 8(10): e78946, a keyboard rendering of "Twinkle, Twinkle, Little Star" in G major, test melody note onsets 600 ms apart; the takes use 0.50, 0.55 and 0.60 s a beat and `tools/maintainer/render_melody.py` (harmonic tones, smooth envelopes, seeded tempo and level variants, 8 kHz mono FLAC, manifest entries).
- [x] 4.2 `tools/maintainer/generate_outside_voice.py` on the maternal-voice tool's pattern: Chatterbox TTS at the pinned revision, a male CMU ARCTIC reference speaker, texts in `added_sounds_data/texts.toml` written for KAINE with no names, two takes per item, 8 kHz FLAC, manifest with sha256, seed and settings; `--verify` checks shipped files. Rendered in a GPU window with no entity running. Then run the harness's outside-voice arm with the real takes. Done on the CPU (GPU 0 was busy): speaker CMU ARCTIC `rms` (median F0 82 to 132 Hz; a first rendering on `bdl` sat at 114 to 142 Hz); items are short lines joined by seeded pauses, 2.2 to 2.9 words a second; a Whisper transcription matched every take and the Perth watermark reads 1.0. The harness's `shipped` arm ran with the real takes, settled schedule, seeds 1 to 3 (`2026-10-31-shipped-summary.json`); the rule-schedule runs were not made.
- [x] 4.3 `added_sounds_data/README.md` with provenance; the speaker database notice in `THIRD_PARTY_LICENSES.md`; `docs/appendix-c-licences.md`.
- [x] 4.4 `kaine/modules/audition/added_sounds.py`: manifest check, slot plan on `(seed, slot)` after the maternal-voice plan (at most one sound per slot), levels and ramps, the outside voice's 3000 Hz low-pass; mixed in `kaine/modules/audition/feed.py` before the hearing band; `[perception_feed.stimulus_source.added_sounds]` parses `enabled`, `melody_probability`, `outside_voice_probability` with ranges checked and unknown keys refused; the Partanen and Querleu citations at the code site. Tests in `tests/test_added_sounds.py` for every added-sound scenario.

## 5. Docs, review and checks

- [ ] 5.1 The developmental-phase chapter (the full-span rule, the added sounds, the band-step records, steps 3 and 4 recorded as adding little); paper notes for §5.4 (stages released on a full-span reading) and A.7 (the record's dwells replace "5.1 to 5.7 hours"). Chapter done (`docs/06-operation/development.md`, appendix A, the dashboard chapter); the paper notes are owed in `predictive-workspace-paper/REVISION-NOTES.md`, a separate repository.
- [x] 5.2 `openspec validate developmental-stimulus-progress --strict` passes.
- [ ] 5.3 Worker first-pass review, then the integrator's independent second review.
