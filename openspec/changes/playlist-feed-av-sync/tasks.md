## 1. Video by presentation timestamp

- [x] 1.1 Add a PyAV video decoder for playlist items in `kaine/modules/vision/feed.py`: media time from `pts × time_base` relative to the container start, missing timestamps filled from the frame interval, non-increasing timestamps held, keyframe seek in stream units, BGR conversion only for presented frames, container duration.
- [x] 1.2 Rewrite `PlaylistSource` on a `decoder_factory` seam (replacing `cv2_module`): present the latest frame at or before the clock offset, hold, seek when more than 2 s behind, hold the last frame after the end, register the container duration (or the last frame's end when there is none). `first_frame()` uses the same decoder.
- [x] 1.3 Update the `PlaylistClock`, `PlaylistSource` and manifest docstrings and `tools/build_playlist_manifest.py`: the manifest `fps` is provenance, not timing.
- [x] 1.4 Add `av` to the `[vision]` extra in `pyproject.toml`.

## 2. Sample-exact audio on the item timeline

- [x] 2.1 Take exactly `frame.samples × channels` int16 values from each resampled frame (packed or planar), and flush the resampler at the end of each item.
- [x] 2.2 Place decoded audio by its timestamps: fill gaps over 40 ms with silence, trim audio more than 40 ms before the position (this replaces the decode-and-drop fallback after a failed seek), pad or trim each item to its length on the shared clock, and play an item with no audio track as silence.

## 3. Drift on the same item

- [x] 3.1 In `kaine/research/ignition_study/analysis.py`, measure drift only where the audio is on the programme's item and count the rest as `audio_on_other_item` in the data-quality block.

## 4. Tests

- [x] 4.1 Port the playlist video tests in `tests/test_vision_feed.py` and `tests/test_perception_transition.py` to a fake decoder; add tests for variable timestamps, missing and duplicate timestamps, seek on open, and the container-duration registration.
- [x] 4.2 Port the fake-PyAV audio tests (`tests/test_vision_feed.py`, `tests/test_preboot_correctness_phase35.py`) to frames with `samples` and `to_ndarray()`; add tests for padded planes, planar frames, timestamp gaps, trimming after a seek, padding to the item length and an item without audio.
- [x] 4.3 Add `tests/test_playlist_av_sync.py`: synthetic constant- and variable-frame-rate clips generated in `tmp_path` with PyAV, carrying matching visual and audible markers; check alignment at several clock offsets and at the end, exact audio duration, seek on open, and the item boundary into a second clip.
- [x] 4.4 Add a real-media check (marked slow, skipped unless `KAINE_PROGRAMME_MEDIA` names the programme's directory) that measures each film's decoded audio duration against its container duration and the presented frame's time against the clock at several offsets.
- [x] 4.5 Add the `audio_on_other_item` case to `tests/test_ignition_analysis.py`.

## 5. Verification

- [x] 5.1 Run the vision, audition, feed, perception and ignition tests, `ruff` and `lint-imports`.
- [x] 5.2 Record the before and after durations and alignment for the four programme films. After: decoded audio equals the container duration within one 30 ms block on all four films (no timestamp gaps filled, nothing trimmed, 4 to 16 ms of end padding), and the presented frame is the one on screen at the clock's offset (37 ms behind it at a 40 ms frame interval, 77 ms at the 80 ms intervals of the two variable-frame-rate films) at 1, 10, 30 and 60 minutes and at the end.
