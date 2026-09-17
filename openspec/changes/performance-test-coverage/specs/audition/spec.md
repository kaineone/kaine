## ADDED Requirements

### Requirement: Spectral features run off the event loop
`SpectralAcousticEncoder.embed`, `detect_speech`, and `_estimate_energy` SHALL run via `asyncio.to_thread` or an equivalent worker mechanism, not directly on the event loop.

#### Scenario: Spectral embedding is off-loop
- **WHEN** `_perceive_acoustic` processes a window
- **THEN** `SpectralAcousticEncoder.embed` is awaited via `asyncio.to_thread`

#### Scenario: VAD and energy share a single spectrum
- **WHEN** the same audio window is analyzed for speech, energy, and spectral embedding
- **THEN** the decode and power-spectrum are computed once and reused
