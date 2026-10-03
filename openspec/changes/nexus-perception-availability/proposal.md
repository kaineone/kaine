# The perception status endpoint reports a missing audio library instead of failing

## Why
`GET /diagnostics/perception.json` reports whether live audio and video can be offered, by trying to import their extras. `sounddevice` is a Python package that loads the PortAudio system library when imported, and when that library is absent it raises `OSError("PortAudio library not found")`, not `ImportError`. `_availability()` catches only `ImportError`, so on a host or image with the Python package but without PortAudio (the Nexus container) the endpoint answers 500. The dashboard cannot show the perception toggles' availability, and the auth script's reconnect probe, which polls this endpoint, logs a server error every time it fires. OpenCV can fail the same way on a missing system library.

Research impact: none (Nexus observation surface).

## What changes
- `_availability()` treats an `OSError` while importing an extra the same as a missing extra: that sense is reported unavailable, and the endpoint answers 200.
