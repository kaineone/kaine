## 1. Video by presentation timestamp

- [x] 1.1 Add a PyAV video decoder for playlist items in `kaine/modules/vision/feed.py`: media time from `pts × time_base` relative to the container start, missing timestamps filled from the frame interval, non-increasing timestamps held, keyframe seek in stream units, BGR conversion only for presented frames, container duration.
- [x] 1.2 Rewrite `PlaylistSource` on a `decoder_factory` seam (replacing `cv2_module`): present the latest frame at or before the clock offset, hold, seek when more than 2 s behind, hold the last frame after the end, register the container duration (or the last frame's end when there is none). `first_frame()` uses the same decoder.
- [x] 1.3 Update the `PlaylistClock`, `PlaylistSource` and manifest docstrings and `tools/build_playlist_manifest.py`: the manifest `fps` is provenance, not timing.
- [x] 1.4 Add `av` to the `[vision]` extra in `pyproject.toml`.

## 2. Sample-exact audio on the item timeline

- [x] 2.1 Take exactly `frame.samples × channels` int16 values from each resampled frame (packed or planar), and flush the resampler at the end of each item.
- [x] 2.2 Place decoded audio by its timestamps: fill gaps over 40 ms with silence, trim audio more than 40 ms before the position (this replaces the decode-and-drop fallback after a failed seek), pad or trim each item to its length on the shared clock, and play an item with no audio track as silence.

## 3. Audio paced against the shared clock

- [x] 3.1 Replace the producer's own deadlines (which re-anchored after a late block) with pacing against the shared clock: emit each block when the clock reaches its delivered position; emit owed blocks at once up to 0.5 s; beyond that drop the queue and resume at the clock's item and offset, logging the first skip at warning, content-free; a pause is never owed; a carried partial block starts the next item's timeline earlier.
- [x] 3.2 Check the video source for the same pattern: none (it picks its frame from the clock on every read).
- [x] 3.3 Tests in `tests/test_playlist_av_sync.py`: a 0.3 s stall is caught up with nothing skipped, a 2 s stall skips forward and logs once, a stall past the item end resumes in the next item at the clock, a 5 s pause is not owed; mutations (keep the lag, never skip, skip on any lateness) each fail them.

## 4. Drift on the same item

- [x] 4.1 In `kaine/research/ignition_study/analysis.py`, measure drift only where the audio is on the programme's item and count the rest as `audio_on_other_item` in the data-quality block.

## 5. Tests

- [x] 5.1 Port the playlist video tests in `tests/test_vision_feed.py` and `tests/test_perception_transition.py` to a fake decoder; add tests for variable timestamps, missing and duplicate timestamps, seek on open, and the container-duration registration.
- [x] 5.2 Port the fake-PyAV audio tests (`tests/test_vision_feed.py`, `tests/test_preboot_correctness_phase35.py`) to frames with `samples` and `to_ndarray()`; add tests for padded planes, planar frames, timestamp gaps, trimming after a seek, padding to the item length and an item without audio.
- [x] 5.3 Add `tests/test_playlist_av_sync.py`: synthetic constant- and variable-frame-rate clips generated in `tmp_path` with PyAV, carrying matching visual and audible markers; check alignment at several clock offsets and at the end, exact audio duration, seek on open, and the item boundary into a second clip.
- [x] 5.4 Add a real-media check (marked slow, skipped unless `KAINE_PROGRAMME_MEDIA` names the programme's directory) that measures each film's decoded audio duration against its container duration and the presented frame's time against the clock at several offsets.
- [x] 5.5 Add the `audio_on_other_item` case to `tests/test_ignition_analysis.py`.

## 6. Verification

- [x] 6.1 Run the vision, audition, feed, perception and ignition tests, `ruff` and `lint-imports`.
- [x] 6.2 Record the before and after durations and alignment for the four programme films. After: decoded audio equals the container duration within one 30 ms block on all four films (no timestamp gaps filled, nothing trimmed, 4 to 16 ms of end padding), and the presented frame is the one on screen at the clock's offset (37 ms behind it at a 40 ms frame interval, 77 ms at the 80 ms intervals of the two variable-frame-rate films) at 1, 10, 30 and 60 minutes and at the end.

## 7. Review fixes

- [x] 7.1 Decode playlist video packet by packet; skip and count a packet that fails to decode (one content-free warning, then debug) instead of ending the item (M1). Tested on a damaged 20 s VP8 WebM on which a whole-stream decode stops early.
- [x] 7.2 An audio item that fails to open or decode is silence for the rest of its length and the producer goes on; a video item that cannot be opened no longer ends the picture; channels other than 1 or 2 are refused at boot and at construction (L1).
- [x] 7.3 Feed logs name the item index or order and the exception type, never the path, file name, title or exception text; a test checks every feed log record on these paths (L2).
- [x] 7.4 After a seek, an untimed frame takes the seek target as its time (L3).
- [x] 7.5 A video timestamp more than 1 s back is a discontinuity: re-base the timeline instead of clamping every later frame (L4).
- [x] 7.6 Mutation-check each fix.
- [x] 7.7 Re-base on a backward timestamp jump only when the next frame confirms the reset; a lone far-behind stamp is placed as untimed and the old timeline continues (R1).
- [x] 7.8 Surfaces report an item they could not open to the shared clock; the clock logs once at error, by item index, when such an unmeasured item has held the programme for 5 s; documented (R2).

