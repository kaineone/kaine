## 1. Implementation

- [x] 1.1 The world model module gains an explicit scenario window; the sleep module opens it before phase 2 and closes it in a `finally` after phase 3; `hypnos.sleep.started` no longer opens it
- [x] 1.2 The world model module answers a replay cue whose timestamp lies inside the latest window even when the poll handles it after the window closed
- [x] 1.3 The sleep module's `shutdown()` cancels and awaits an in-flight sleep, then awaits its held shielded tasks, each wait bounded
- [x] 1.4 A non-finite payload timestamp ranks as 0.0 in `recent_points` on every backend
- [x] 1.5 Tests: the window through a real sleep on the bus, the window closing on a cancel, shutdown during a sleep and during a held reset, non-finite timestamps on the in-memory, sqlite-vec and Qdrant backends
- [x] 1.6 Docs: the world model module, sleep module and sleep pages
- [x] 1.7 Review follow-ups: a cue counts only inside the open window or one of the last four closed windows; the cycle and the supervisor shut the sleep module down first; the world model module's `initialize()` clears the sleep state
