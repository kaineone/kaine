## ADDED Requirements

### Requirement: Perception availability survives missing system libraries
The perception status endpoint SHALL report a live sense as unavailable, and still answer successfully, when importing that sense's extra fails because a system library it loads is missing (an `OSError` at import), exactly as when the extra is not installed.

#### Scenario: PortAudio is missing
- **WHEN** importing `sounddevice` raises `OSError("PortAudio library not found")`
- **THEN** `GET /diagnostics/perception.json` answers 200 with `audio_available` false
