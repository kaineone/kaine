## ADDED Requirements

### Requirement: Strided clip window avoids redundant frames
Topos SHALL maintain a frame window such that each clip encode advances by `clip_stride` frames, not by rebuilding the entire `clip_len` window each time.

#### Scenario: Strided window advances correctly
- **WHEN** frames 0..15 are encoded and then frame 16 arrives with `clip_stride=3`
- **THEN** the next encode uses frames 3..18, not 1..16

### Requirement: Forward model step runs off the event loop
When `forward_prediction` is enabled, the MLP forward/backward step in `kaine/modules/topos/forward.py` SHALL run via `asyncio.to_thread`.

#### Scenario: Forward step is off-loop
- **WHEN** `ForwardModel.step()` is called from `process_frame`
- **THEN** the call is wrapped in `asyncio.to_thread` and does not block the event loop
