## 1. Fix the producer + lockstep constants

- [x] 1.1 `kaine/modules/lingua/module.py` `_produce`: publish `"type":
      f"{mode}_speech"` (→ `external_speech` / `internal_speech`) instead of the
      stream name.
- [x] 1.2 `kaine/workspace/volition.py`: `OWN_EXTERNAL_SPEECH_TYPE =
      "external_speech"`, `OWN_INTERNAL_SPEECH_TYPE = "internal_speech"`.

## 2. Tests

- [x] 2.1 New producer-contract test: construct a real `Lingua` with the fake
      chat client; assert `speak()` publishes an event with type
      `external_speech` and `think()` publishes type `internal_speech` (read the
      events back off the streams).
- [x] 2.2 Update volition/drive-policy tests that built events with the old
      `lingua.external`/`lingua.internal` type to the semantic types (correcting
      them to the real contract — not weakening assertions).

## 3. Verify

- [x] 3.1 Full suite green (`.venv/bin/python -m pytest -q`) — no skips/xfails
      added.
- [x] 3.2 `openspec validate "fix-lingua-speech-event-type"` passes.
