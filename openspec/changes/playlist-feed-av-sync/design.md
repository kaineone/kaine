## Context

The playlist feed has one real-time position authority, the shared `PlaylistClock` (one monotonic origin, per-item lengths, pause holders). The video source reads at the cognitive tick rate and picks a frame for the clock's offset; the audio source runs a producer thread that paces fixed-size PCM blocks at 1x and parks while the clock is paused. Both sources open every item themselves and the first to open an item registers its length on the clock.

The video side decoded with `cv2.VideoCapture` and had no per-frame time: it counted frames and multiplied by the manifest's nominal rate. The audio side counted bytes of padded PyAV planes.

## Goals / Non-Goals

**Goals:**
- At any clock offset the presented frame and the delivered audio come from the same media time, for constant- and variable-frame-rate files.
- The audio delivered for an item is exactly the item's decoded audio, placed on the item's timeline.
- Both surfaces agree on each item's length, and a re-opened source resumes at the clock's position quickly.
- The delivered audio position tracks the clock offset: a stall is caught up or skipped, never kept as a lag.

**Non-Goals:**
- Changing the seeded or stimulus-source feeds, which are generated per frame index by design and have no media timestamps.
- Frame-locking the two module loops.

## Decisions

**Decision 1: decode playlist video with PyAV, not OpenCV.**
PyAV exposes each decoded frame's `pts` and `time_base`, the container duration and keyframe seeking in stream units. OpenCV's FFmpeg backend reports `CAP_PROP_POS_MSEC` from the frame timestamp on the installed build, but its frame count and seek are computed from a nominal rate, so seeking a variable-frame-rate file lands at the wrong time, and the property's meaning differs across backends. PyAV is already required for playlist audio, so a playlist run already has it; it joins the `[vision]` extra so a video-only playlist install works too. Frames are converted with `to_ndarray(format="bgr24")`, the layout the vision module received from OpenCV.
- *Alternative:* keep OpenCV and read `CAP_PROP_POS_MSEC` after each frame. Rejected for the seek and portability reasons above.

**Decision 2: a small decoder seam.**
`PlaylistSource` takes an optional `decoder_factory(path, item)` returning an object with `duration`, `next()` (the next `(seconds, frame)` or `None` at the end), `seek(seconds)`, `image(frame)` and `close()`. The default wraps PyAV; tests inject a fake with scripted timestamps. This replaces the `cv2_module` seam.

**Decision 3: presentation rule.**
Media time is `pts × time_base − container start`. The source keeps the current frame and one decoded frame of lookahead. A read moves forward while the lookahead's time is at or before the clock offset, then presents the current frame; a read that finds no newer frame re-presents the same frame object (hold). Before the first frame's time, the first frame is shown. After the last frame, the last frame is held until the clock moves to the next item. A missing `pts` becomes the previous time plus the stream's frame interval (from its average rate, else the nominal manifest rate, else 1/25 s); a `pts` at or before the previous time is held at the previous time, so of several frames with one timestamp the last is the one shown.

**Decision 3a: damaged media and odd timestamps.**
The decoder demuxes and decodes one packet at a time. A packet that fails to decode is skipped and counted (the first logged at warning, later ones at debug); the picture holds until the next good frame. A single decode generator for the whole stream is finished by its first error, which would freeze the picture for the rest of the item and, for a container without a duration, end the item at the error. After a seek, an untimed first frame takes the seek target as its time, not 0. A timestamp more than 1 s before the previous frame's is either one corrupt stamp or a timestamp reset. A lone frame that far behind is placed as untimed (one frame interval after the previous frame) and the old timeline goes on. When the next frame is also that far behind and in order from it, the timestamps were reset, and the timeline is re-based to continue one frame interval after the previous frame. Holding every later frame at one time would make all of them due at once, so one read would decode the rest of the item. Re-basing on a single outlier would put every later frame seconds late, holding the outlier for the rest of the item.

**Decision 3b: one failing item does not end a surface.**
A video item that cannot be opened shows nothing while the clock is on it, and the source opens the next item when the clock gets there. An audio item that fails to open or decode is logged and heard as silence for the rest of its length on the clock (with no known length, nothing more is delivered and the next item's first block waits for the clock); the producer goes on. An item that neither surface can open, in a container whose length nothing has measured, holds the shared clock on that item, because the clock cannot cross an unmeasured end. Each surface reports an item it could not open to the clock; when the programme has been held on a reported, unmeasured item for 5 s, the clock logs it once at error level, by item index only. The 5 s leave the other surface time to open and measure the item. The playlist audio delivers mono or stereo only: another channel count is refused when the factory is built at boot and when the stream is constructed.

**Decision 3c: logs name items, never media.**
Feed log lines name an item by its index (or manifest order) and an exception by its type. They never carry the media path, the file name or the exception's text, which can embed the path (the mount and the film's title).

**Decision 4: seek when far behind.**
When the clock offset is more than 2 s past the next frame to decode (a source opened partway into an item, or a long stall), the source seeks to the keyframe at or before the offset and decodes forward. If the seek raises, it decodes forward from where it is. The threshold keeps normal reads, which advance a fraction of a second, on the cheap sequential path.

**Decision 5: item length from the container.**
Both surfaces register `container.duration / AV_TIME_BASE`. It covers the longest stream, so neither the picture nor the sound is cut short. When a container has no duration, the video registers its last frame's time plus one frame interval when it reaches the end of the stream; the clock cannot cross the boundary before then, which is the existing behaviour for unmeasured items.

**Decision 6: audio on the item timeline.**
The producer counts the samples it has placed for the item, starting at the resync offset. For each decoded frame with a timestamp it compares the frame's media time with that position. A gap longer than 40 ms is filled with silence; audio more than 40 ms before the position is trimmed from the frame's resampled output. Within 40 ms, samples are appended as decoded, so the resampler's few-sample delay and millisecond timestamp rounding never insert or drop audio. After the item's last frame the resampler is flushed, and the item is padded with silence or trimmed to its registered length. The same rule replaces the separate decode-and-drop path after a failed seek. The 40 ms tolerance is larger than one Vorbis or Opus frame's rounding and smaller than a perceptible lip-sync error (about 45 ms audio-leading, ITU-R BT.1359).

**Decision 7: exact samples.**
Each resampled frame contributes `frame.samples × channels` int16 values: `to_ndarray()` gives `(1, samples × channels)` for packed layouts and `(channels, samples)` for planar ones, which is transposed to interleave. The byte count is checked against `samples × channels × 2`.

**Decision 8: pace the audio against the shared clock.**
The producer paced its blocks on its own monotonic deadlines and, after a late block, re-anchored the next deadline to the present instead of catching up, so every stall (a GC pause, a busy host, slow I/O) added a lag that never went away. Each block now goes out when the shared clock reaches the block's place on the item timeline (its delivered position). A block that is due, or owed up to 0.5 s, goes out at once, so after a stall the owed blocks are emitted back to back and the delivered position returns to the clock. A block owed more than 0.5 s makes the producer drop what is queued and resume at the clock's item and offset through the same seek path as a restart, logging the first skip at warning and later ones at debug, with the owed seconds, item index and offset only. A skip past an item's end resumes in the item the clock is on. The clock's pause holders keep their meaning: while the clock is paused nothing is due and nothing is owed, so a pause never causes a catch-up or a skip. A partial block of the previous item still queued at a boundary starts the next item's timeline that much earlier, so the pacing is exact across the boundary. The 0.5 s bound keeps a catch-up burst short (at most about 17 blocks of 30 ms) while still riding out ordinary stalls without losing sound.
- *Video:* the video source has no deadline to re-anchor. Each read picks the frame from the clock offset, so a stall only makes the next read decode forward (or seek, past 2 s); its position cannot lag. The vision module's capture interval sets the sampling cadence, not the position.

## Risks / Trade-offs

- **[Risk]** A catch-up delivers up to 0.5 s of sound faster than real time. → Bounded, and only after a stall; the alternative is a lag that grows for the rest of the run.

- **[Risk]** PyAV and OpenCV convert YUV to BGR with slightly different defaults, so pixel values can differ by a level or two. → Runs after this change already differ from runs before it in timing; the encoders see the same scene content.
- **[Risk]** Seeking lands on a keyframe that may be several seconds before the target, and decoding forward from it costs time. → Bounded by the keyframe interval; it replaces decoding the whole item from the first frame.
- **[Risk]** An item whose audio is much shorter than its container is padded with long silence. → That is what the film is at that point; skipping it would put the next film's sound under this film's picture.
