## Purpose

Define performance requirements for the cognitive-cycle hot path so the entity does not waste CPU, Redis bandwidth, or event-loop time on redundant work.

## ADDED Requirements

### Requirement: Bus consumers avoid empty-result polling
When a module or the engine has no new events to process, it SHALL wait on Redis (e.g. blocking `XREAD ... BLOCK`) or receive events from a single shared fan-out, rather than issuing repeated non-blocking `XREAD` calls on a fixed poll interval.

#### Scenario: Quiet module does not flood Redis
- **WHEN** no events are published for 10 seconds
- **THEN** the module's Redis `XREAD` call count is bounded by O(1) rather than growing with the poll rate

#### Scenario: Engine read fan-out is consolidated
- **WHEN** the cycle tick reads multiple module streams
- **THEN** it uses one consolidated read path per tick rather than one independent round trip per stream

### Requirement: Mnemos defers embedding until persistence
Mnemos SHALL embed a workspace snapshot only when the entry actually persists (eviction to episodic, consolidation, or explicit recall), not on every tick that merely buffers the entry in short-term memory.

#### Scenario: Buffered snapshot is not embedded
- **WHEN** a snapshot is stored in short-term memory without eviction
- **THEN** the embedder is not invoked for that entry

#### Scenario: Evicted snapshot is embedded once
- **WHEN** a short-term entry is evicted to episodic memory
- **THEN** it is embedded exactly once at eviction time

### Requirement: Topos avoids overlapping clip re-encodes
Topos SHALL maintain a strided window so consecutive clip encodes advance by `clip_stride` frames and do not re-encode the shared tail. The encoder SHALL accept frames in its native format without a per-clip PIL round-trip where the input is already a numpy array or PIL image.

#### Scenario: Consecutive clips share only stride frames
- **WHEN** `clip_len=16` and `clip_stride=3`
- **THEN** the second clip encode processes only 3 new frames, not 16

#### Scenario: Encoder avoids redundant PIL conversion
- **WHEN** the input frames are already ndarrays
- **THEN** the encoder encodes them directly without converting each to PIL and back

### Requirement: Audition spectral work runs off the event loop
`SpectralAcousticEncoder.embed`, `detect_speech`, and `_estimate_energy` SHALL run via `asyncio.to_thread` or an equivalent off-loop mechanism, and SHALL share a single decode/power-spectrum pass over the same buffer.

#### Scenario: Spectral embedding does not block the loop
- **WHEN** a 500 ms audio window is processed
- **THEN** the FFT/filterbank work runs on a worker thread and the event loop remains responsive

#### Scenario: Single decode pass serves all three transforms
- **WHEN** the same buffer needs embedding, VAD, and energy
- **THEN** the WAV decode and power spectrum are computed once and reused

### Requirement: Topos forward model runs off the event loop
The Topos forward-model `step()` (MLP forward + backward + SGD) SHALL run via `asyncio.to_thread` so it does not block frame capture or cycle tasks.

#### Scenario: Forward-model step does not block the camera task
- **WHEN** a clip is processed and the forward model is enabled
- **THEN** the optimizer step runs on a worker thread and the next frame read is not delayed

### Requirement: Novelty scoring is O(1) per event
`NoveltyTracker.observe` SHALL maintain a hash-based count of recent fingerprints so that scoring and update are O(1), not O(window).

#### Scenario: Large burst of events scores in constant time
- **WHEN** 100 events with random fingerprints are observed
- **THEN** the total time scales linearly with event count, not quadratically
