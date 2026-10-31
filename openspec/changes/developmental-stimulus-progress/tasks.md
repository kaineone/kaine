## 1. Assets

- [ ] 1.1 Confirm against Partanen et al. (2013) which melody they played; write its note list (public-domain tune, G4 to E5) and `tools/maintainer/render_melody.py` (harmonic tones, smooth envelopes, seeded tempo and level variants, 8 kHz mono FLAC, manifest entries).
- [ ] 1.2 `tools/maintainer/generate_outside_voice.py` on the maternal-voice tool's pattern: Chatterbox TTS at the pinned revision, a male CMU ARCTIC reference speaker, texts in `added_sounds_data/texts.toml` written for KAINE with no names, two takes per item, 8 kHz FLAC, manifest with sha256, seed and settings; `--verify` checks shipped files. Rendered in a GPU window with no entity running.
- [ ] 1.3 `added_sounds_data/README.md` with provenance; the speaker database notice in `THIRD_PARTY_LICENSES.md`; `docs/appendix-c-licences.md`.

## 2. Runtime

- [ ] 2.1 `kaine/modules/audition/added_sounds.py`: manifest check, slot plan on `(seed, slot)` after the maternal-voice plan (at most one sound per slot), levels and ramps, the outside voice's 3000 Hz low-pass; mixed in `kaine/modules/audition/feed.py` before the hearing band; `[perception_feed.stimulus_source.added_sounds]` parses `enabled`, `melody_probability`, `outside_voice_probability` with ranges checked and unknown keys refused; the Partanen and Querleu citations at the code site. Tests in `tests/test_added_sounds.py` for every spec scenario except the offline check.
- [ ] 2.2 The perceptual alert rate per hour with and without the added sounds, in the harness of task 3.

## 3. Band-step check (no entity)

- [ ] 3.1 `scripts/band_step_check.py` as in design D4, three seeds, with and without the added sounds; record under `docs/records/validation/band-steps/`. Add the cause it supports and the selected fix (H1, H2 or H3 of design D4) to this change's spec, with the record, before writing the fix.
- [ ] 3.2 Implement the selected fix with its tests; rerun the check on the fixed stimulus and store the rerun record.
- [ ] 3.3 Through the real affect module in the same harness: boredom's deprivation share over a simulated developmental span, with and without the added sounds; same record.

## 4. Dwell

- [ ] 4.1 If the rerun record meets design D5, put the decision on removing the minimum dwell to the operator with the record; otherwise leave `min_dwell_seconds = 5400` and note why in the record. A test pins the shipped value to the record's outcome.

## 5. Docs, review and checks

- [ ] 5.1 The developmental-phase chapter (the added sounds, the band-step record); paper notes for §5.4, §7 and A.7.
- [ ] 5.2 `openspec validate developmental-stimulus-progress --strict` passes.
- [ ] 5.3 Worker first-pass review, then the integrator's independent second review.
