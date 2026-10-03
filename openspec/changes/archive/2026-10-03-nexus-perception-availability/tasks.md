## 1. Fix
- [x] 1.1 `kaine/nexus/perception.py` `_availability()`: catch `(ImportError, OSError)` for both the audio and the video imports, with comments saying why.

## 2. Tests
- [x] 2.1 With `sounddevice` made to raise `OSError` on import, `_availability()` reports audio unavailable and `GET /diagnostics/perception.json` answers 200; same for `cv2` and video.
