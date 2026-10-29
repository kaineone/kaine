## 1. Implementation

- [x] 1.1 Affect: track the last engagement time, request a developmental rest when a boredom goal stalls on a spent stimulus while developing, persist the engagement time as a duration
- [x] 1.2 Sleep: start a `developmental_rest` sleep on the request and hold it to `developmental_rest_s` before the affective reset
- [x] 1.3 Config key `[sleep].developmental_rest_s = 1260.0`, factory validation, research-log curation of `affect.rest_request`
- [x] 1.4 Tests for both sides, the hold, a cancel during the hold, and unchanged ordinary sleeps
- [x] 1.5 Docs: affect and sleep module pages
