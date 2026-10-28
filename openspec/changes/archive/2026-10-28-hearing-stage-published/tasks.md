## 1. Implementation

- [x] 1.1 Add the hearing-stage watch: read the shared awake-time provider, log and publish each stage transition, retry a failed publish, stop after the open band
- [x] 1.2 Run the watch beside the stimulus-source presence publisher when the audition module and the hearing band are enabled
- [x] 1.3 Tests: transitions and payloads, agreement with `hearing_stage` over a sweep, the log line, the run loop through stage 4, recovery from a failing provider and a failing publish, the enabling conditions, and the boot wiring
- [x] 1.4 Document the event in docs/06-operation/development.md
