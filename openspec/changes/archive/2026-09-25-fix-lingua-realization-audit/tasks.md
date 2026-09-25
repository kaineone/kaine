## 1. Implementation

- [x] 1.1 Factor the mode-stream record write in `Lingua._produce` into a helper and use it for both utterances and the `realization_failed` record on `INTERNAL_STREAM`; remove the call to the non-existent `self._publish`.
- [x] 1.2 Log a failed audit emission at WARNING.

## 2. Tests

- [x] 2.1 Failing chat client → one `realization_failed` record on `lingua.internal` whose payload has exactly `mode` and `reason_class`, and no record on `lingua.external`.
- [x] 2.2 The record read back from the stream is counted by `classify_realizations` as `realization_failed_count == 1`.
- [x] 2.3 Existing Lingua tests stay green; full offline suite green.
