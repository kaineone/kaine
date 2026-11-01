## Context

The playlist feed has one real-time position authority, the shared `PlaylistClock` (one monotonic origin, per-item lengths, pause holders). The video source reads at the cognitive tick rate and picks a frame for the clock's offset; the audio source runs a producer thread that paces fixed-size PCM blocks at 1x and parks while the clock is paused. Both sources open every item themselves and the first to open an item registers its length on the clock.

The video side decoded with `cv2.VideoCapture` and had no per-frame time: it counted frames and multiplied by the manifest's nominal rate. The audio side counted bytes of padded PyAV planes.

## Goals / Non-Goals

**Goals:**
- At any clock offset the presented frame and the delivered audio come from the same media time, for constant- and variable-frame-rate files.
- The audio delivered for an item is exactly the item's decoded audio, placed on the item's timeline.
- Both surfaces agree on each item's length, and a re-opened source resumes at the clock's position quickly.

**Non-Goals:**
- Changing the seeded or stimulus-source feeds, which are generated per frame index by design and have no media timestamps.
- Changing the audio producer's 1x block pacing. It re-anchors after a late block instead of catching up, so a stall adds a permanent lag; that lag is visible in the ignition log as offset minus delivered position and is left for a follow-up.
- Frame-locking the two module loops.

## Decisions

**Decision 1: decode playlist video with PyAV, not OpenCV.**
PyAV exposes each decoded frame's `pts` and `time_base`, the container duration and keyframe seeking in stream units. OpenCV's FFmpeg backend reports `CAP_PROP_POS_MSEC` from the frame timestamp on the installed build, but its frame count and seek are computed from a nominal rate, so seeking a variable-frame-rate file lands at the wrong time, and the property's meaning differs across backends. PyAV is already required for playlist audio, so a playlist run already has it; it joins the `[vision]` extra so a video-only playlist install works too. Frames are converted with `to_ndarray(format="bgr24")`, the layout the vision module received from OpenCV.
- *Alternative:* keep OpenCV and read `CAP_PROP_POS_MSEC` after each frame. Rejected for the seek and portability reasons above.

**Decision 2: a small decoder seam.**
`PlaylistSource` takes an optional `decoder_factory(path)` returning an object with `duration`, `next()` (the next `(seconds, frame)` or `None` at the end), `seek(seconds)`, `image(frame)` and `close()`. The default wraps PyAV; tests inject a fake with scripted timestamps. This replaces the `cv2_module` seam.

**Decision 3: presentation rule.**
Media time is `pts × time_base − container start`. The source keeps the current frame and one decoded frame of lookahead. A read moves forward while the lookahead's time is at or before the clock offset, then presents the current frame; a read that finds no newer frame re-presents the same frame object (hold). Before the first frame's time, the first frame is shown. After the last frame, the last frame is held until the clock moves to the next item. A missing `pts` becomes the previous time plus the stream's frame interval (from its average rate, else the nominal manifest rate, else 1/25 s); a `pts` at or before the previous time is held at the previous time, so of several frames with one timestamp the last is the one shown.

**Decision 4: seek when far behind.**
When the clock offset is more than 2 s past the next frame to decode (a source opened partway into an item, or a long stall), the source seeks to the keyframe at or before the offset and decodes forward. If the seek raises, it decodes forward from where it is. The threshold keeps normal reads, which advance a fraction of a second, on the cheap sequential path.

**Decision 5: item length from the container.**
Both surfaces register `container.duration / AV_TIME_BASE`. It covers the longest stream, so neither the picture nor the sound is cut short. When a container has no duration, the video registers its last frame's time plus one frame interval when it reaches the end of the stream; the clock cannot cross the boundary before then, which is the existing behaviour for unmeasured items.

**Decision 6: audio on the item timeline.**
The producer counts the samples it has placed for the item, starting at the resync offset. For each decoded frame with a timestamp it compares the frame's media time with that position. A gap longer than 40 ms is filled with silence; audio more than 40 ms before the position is trimmed from the frame's resampled output. Within 40 ms, samples are appended as decoded, so the resampler's few-sample delay and millisecond timestamp rounding never insert or drop audio. After the item's last frame the resampler is flushed, and the item is padded with silence or trimmed to its registered length. The same rule replaces the separate decode-and-drop path after a failed seek. The 40 ms tolerance is larger than one Vorbis or Opus frame's rounding and smaller than a perceptible lip-sync error (about 45 ms audio-leading, ITU-R BT.1359).

**Decision 7: exact samples.**
Each resampled frame contributes `frame.samples × channels` int16 values: `to_ndarray()` gives `(1, samples × channels)` for packed layouts and `(channels, samples)` for planar ones, which is transposed to interleave. The byte count is checked against `samples × channels × 2`.

## Risks / Trade-offs

- **[Risk]** PyAV and OpenCV convert YUV to BGR with slightly different defaults, so pixel values can differ by a level or two. → Runs after this change already differ from runs before it in timing; the encoders see the same scene content.
- **[Risk]** Seeking lands on a keyframe that may be several seconds before the target, and decoding forward from it costs time. → Bounded by the keyframe interval; it replaces decoding the whole item from the first frame.
- **[Risk]** An item whose audio is much shorter than its container is padded with long silence. → That is what the film is at that point; skipping it would put the next film's sound under this film's picture.
