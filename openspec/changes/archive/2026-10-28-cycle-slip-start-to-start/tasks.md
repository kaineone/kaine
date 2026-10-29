## 1. Implementation

- [x] 1.1 Measure `slip_ms` from the previous tick's start to this tick's start against the previous tick's budget, reporting 0 for the first tick and after a pause
- [x] 1.2 Count `overrun_ticks` from the tick body exceeding its budget
- [x] 1.3 Tests: the pacing wait's oversleep shows as slip while the requested waits are unchanged, the first tick and the tick after a pause report 0, a late start is slip without an overrun, and the event payload matches the tick result; the existing slip tests follow the new measurement
- [x] 1.4 Document the measurement in docs/08-cognitive-cycle/README.md
